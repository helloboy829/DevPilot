"""App-owned request-version vault. No HTTP execution or plaintext read API."""

import asyncio
import hashlib
import hmac
from uuid import uuid4

from devpilot.request_templates import RequestTemplate
from devpilot.request_versions import FrozenRequest
from sqlalchemy import insert, select
from sqlalchemy.exc import IntegrityError

from app.evaluation import tables as t
from app.evaluation.registry import version_key
from app.evaluation.registry_repository import RegistryRepository
from app.evaluation.repository import Conflict, NotFound, now
from app.evaluation.request_protection import RequestProtection, RequestProtectionError
from app.evaluation.request_versions import RequestVersionCreate


class RequestVersionRepository(RegistryRepository):
    _public_columns = tuple(column for column in t.request_versions.c if column.name not in {"encrypted_payload", "label_key"})

    def __init__(self, sf, *, protection=None):
        super().__init__(sf)
        self.protection = protection

    def _protection(self):
        return self.protection if self.protection is not None else RequestProtection.from_environment()

    @staticmethod
    def _binding(owner, row):
        return {"owner_id": owner, "project_id": row["project_id"], "component_id": row["component_id"], "request_version_id": row["id"]}

    @staticmethod
    async def _request_event(session, owner, row, action):
        await session.execute(insert(t.request_version_audit).values(id=uuid4().hex, project_id=row["project_id"], request_version_id=row["id"], actor=owner, action=action, at=now()))

    async def create_request_version(self, owner, project_id, component_id, payload: RequestVersionCreate):
        # Revalidate the full DTO: model_copy and nested dicts can bypass validators.
        payload = RequestVersionCreate.model_validate(payload.model_dump())
        frozen = FrozenRequest.from_protected_dict(payload.request)
        try:
            async with self.sf.begin() as session:
                await self._linked_component(session, owner, project_id, component_id)
                row = {
                    "id": uuid4().hex,
                    "project_id": project_id,
                    "component_id": component_id,
                    "version_label": payload.version_label,
                    "label_key": version_key(payload.version_label),
                    "scope": "request_definition_only",
                    "request_template": frozen.template.to_dict(),
                    "created_by": owner,
                    "created_at": now(),
                }
                token = await asyncio.to_thread(self._protection().seal, frozen, self._binding(owner, row))
                row.update(encrypted_payload=token, protected_hash=hashlib.sha256(token.encode()).hexdigest())
                await session.execute(insert(t.request_versions).values(**row))
                await self._request_event(session, owner, row, "request_version_created")
            return {key: value for key, value in row.items() if key not in {"encrypted_payload", "label_key"}}
        except IntegrityError:
            raise Conflict from None

    @staticmethod
    def _public(row):
        try:
            RequestTemplate.from_dict(row["request_template"])
            if row["scope"] != "request_definition_only":
                raise ValueError
        except (ValueError, TypeError, KeyError):
            raise RequestProtectionError("Protected request metadata is invalid") from None
        return {key: value for key, value in row.items() if key not in {"encrypted_payload", "label_key"}}

    async def list_request_versions(self, owner, project_id, component_id):
        async with self.sf() as session:
            await self._linked_component(session, owner, project_id, component_id)
            rows = await session.execute(
                select(*self._public_columns).where(t.request_versions.c.project_id == project_id, t.request_versions.c.component_id == component_id).order_by(t.request_versions.c.created_at, t.request_versions.c.id)
            )
            return [self._public(row) for row in rows.mappings()]

    async def _request_version(self, session, owner, project_id, version_id, *, protected=False):
        await self._project(session, owner, project_id)
        statement = select(t.request_versions) if protected else select(*self._public_columns)
        row = (await session.execute(statement.where(t.request_versions.c.project_id == project_id, t.request_versions.c.id == version_id))).mappings().first()
        if row is None:
            raise NotFound
        return dict(row)

    async def get_request_version(self, owner, project_id, version_id):
        async with self.sf() as session:
            return self._public(await self._request_version(session, owner, project_id, version_id))

    async def _open_request_row(self, session, owner, row) -> FrozenRequest:
        """Use an already owner-scoped row; audit in the caller's transaction."""
        try:
            actual = hashlib.sha256(row["encrypted_payload"].encode()).hexdigest()
            if not hmac.compare_digest(actual, row["protected_hash"]):
                raise RequestProtectionError("Protected request integrity check failed")
            frozen = await asyncio.to_thread(self._protection().open, row["encrypted_payload"], self._binding(owner, row))
            if row["scope"] != "request_definition_only" or row["request_template"] != frozen.template.to_dict():
                raise RequestProtectionError("Protected request metadata changed")
        except (ValueError, TypeError, AttributeError):
            raise RequestProtectionError("Protected request integrity check failed") from None
        await self._request_event(session, owner, row, "request_version_opened")
        return frozen

    async def open_request_version(self, owner, project_id, version_id) -> FrozenRequest:
        """Internal-only audited access, not authorization to execute a request."""
        async with self.sf.begin() as session:
            row = await self._request_version(session, owner, project_id, version_id, protected=True)
            return await self._open_request_row(session, owner, row)

    async def request_version_audit(self, owner, project_id, version_id):
        async with self.sf() as session:
            await self._request_version(session, owner, project_id, version_id)
            rows = await session.execute(
                select(t.request_version_audit).where(t.request_version_audit.c.project_id == project_id, t.request_version_audit.c.request_version_id == version_id).order_by(t.request_version_audit.c.at, t.request_version_audit.c.id)
            )
            return [dict(row) for row in rows.mappings()]
