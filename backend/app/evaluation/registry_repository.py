"""Project links and immutable, non-executable submission inventories."""

from uuid import uuid4

from sqlalchemy import insert, select
from sqlalchemy.exc import IntegrityError

from app.evaluation import tables as t
from app.evaluation.datasets import QASample, dataset_hash
from app.evaluation.registry import ComponentLinkCreate, SubmissionCreate, fingerprint, version_key
from app.evaluation.repository import Conflict, EvaluationRepository, NotFound, now
from deerflow.persistence.component_tests.model import ComponentRow


class RegistryRepository(EvaluationRepository):
    # Select only inventory columns. Never load endpoint, token or arbitrary criteria.
    _source_columns = (ComponentRow.id.label("source_component_id"), ComponentRow.name, ComponentRow.transport, ComponentRow.response_mode, ComponentRow.supports_streaming, ComponentRow.validation_type)

    @staticmethod
    def _candidate(row):
        snapshot = {"schema": "component-inventory.v1", **dict(row)}
        return {**snapshot, "component_fingerprint": fingerprint(snapshot)}

    async def _source(self, session, owner, source_id):
        row = (await session.execute(select(*self._source_columns).where(ComponentRow.user_id == owner, ComponentRow.id == source_id))).mappings().first()
        if row is None:
            raise NotFound
        return self._candidate(row)

    async def component_candidates(self, owner, project_id):
        async with self.sf() as session:
            await self._project(session, owner, project_id)
            rows = await session.execute(select(*self._source_columns).where(ComponentRow.user_id == owner).order_by(ComponentRow.id))
            return [self._candidate(row) for row in rows.mappings()]

    @staticmethod
    async def _registry_event(session, owner, project_id, component_id, action, submission_id=None):
        await session.execute(insert(t.registry_audit).values(id=uuid4().hex, project_id=project_id, component_id=component_id, submission_id=submission_id, actor=owner, action=action, at=now()))

    async def link_component(self, owner, project_id, payload: ComponentLinkCreate):
        try:
            async with self.sf.begin() as session:
                await self._project(session, owner, project_id)
                source = await self._source(session, owner, payload.source_component_id)
                row = {"id": uuid4().hex, "project_id": project_id, "source_component_id": payload.source_component_id, "name_at_link": source["name"], "kind": payload.kind, "created_at": now()}
                await session.execute(insert(t.project_components).values(**row))
                await self._registry_event(session, owner, project_id, row["id"], "component_linked")
            return row
        except IntegrityError:
            raise Conflict from None

    async def list_project_components(self, owner, project_id):
        async with self.sf() as session:
            await self._project(session, owner, project_id)
            rows = await session.execute(select(t.project_components).where(t.project_components.c.project_id == project_id).order_by(t.project_components.c.created_at, t.project_components.c.id))
            return [dict(row) for row in rows.mappings()]

    async def _linked_component(self, session, owner, project_id, component_id):
        await self._project(session, owner, project_id)
        row = (await session.execute(select(t.project_components).where(t.project_components.c.project_id == project_id, t.project_components.c.id == component_id))).mappings().first()
        if row is None:
            raise NotFound
        return dict(row)

    async def create_submission(self, owner, project_id, component_id, payload: SubmissionCreate):
        try:
            async with self.sf.begin() as session:
                component = await self._linked_component(session, owner, project_id, component_id)
                source = await self._source(session, owner, component["source_component_id"])
                dataset = await self._dataset(session, owner, project_id, payload.dataset_id)
                if (
                    source["component_fingerprint"] != payload.component_fingerprint
                    or dataset["status"] != "frozen"
                    or dataset["revision"] != payload.dataset_revision
                    or dataset["content_hash"] != payload.dataset_hash
                    or dataset["sample_count"] < 1
                ):
                    raise Conflict
                # Revalidate persisted content without returning gold to the caller.
                rows = (
                    (
                        await session.execute(
                            select(t.samples, t.references.c.expected)
                            .join(t.references, (t.samples.c.dataset_id == t.references.c.dataset_id) & (t.samples.c.sample_id == t.references.c.sample_id))
                            .where(t.samples.c.dataset_id == dataset["id"])
                        )
                    )
                    .mappings()
                    .all()
                )
                try:
                    samples = [QASample.model_validate({k: v for k, v in row.items() if k != "dataset_id"}) for row in rows]
                    if len(samples) != dataset["sample_count"] or dataset_hash(dataset["source"], dataset["purpose"], samples) != payload.dataset_hash:
                        raise Conflict
                except ValueError:
                    raise Conflict from None
                snapshot = {key: value for key, value in source.items() if key != "component_fingerprint"}
                snapshot["kind"] = component["kind"]
                binding = {
                    "schema": "submission-inventory.v1",
                    "scope": "inventory_only",
                    "project_id": project_id,
                    "component_id": component_id,
                    "version_label": payload.version_label,
                    "dataset_id": dataset["id"],
                    "dataset_revision": dataset["revision"],
                    "dataset_hash": dataset["content_hash"],
                    "dataset_purpose": dataset["purpose"],
                    "component_snapshot": snapshot,
                }
                row = {key: value for key, value in binding.items() if key != "schema"}
                row.update(id=uuid4().hex, label_key=version_key(payload.version_label), submission_hash=fingerprint(binding), created_at=now(), created_by=owner)
                await session.execute(insert(t.submissions).values(**row))
                await self._registry_event(session, owner, project_id, component_id, "submission_created", row["id"])
            return self._public_submission(row)
        except IntegrityError:
            raise Conflict from None

    @staticmethod
    def _public_submission(row):
        return {key: value for key, value in row.items() if key != "label_key"}

    async def list_submissions(self, owner, project_id, component_id):
        async with self.sf() as session:
            await self._linked_component(session, owner, project_id, component_id)
            rows = await session.execute(select(t.submissions).where(t.submissions.c.project_id == project_id, t.submissions.c.component_id == component_id).order_by(t.submissions.c.created_at, t.submissions.c.id))
            return [self._public_submission(row) for row in rows.mappings()]

    async def get_submission(self, owner, project_id, submission_id):
        async with self.sf() as session:
            await self._project(session, owner, project_id)
            row = (await session.execute(select(t.submissions).where(t.submissions.c.id == submission_id, t.submissions.c.project_id == project_id))).mappings().first()
            if row is None:
                raise NotFound
            return self._public_submission(row)

    async def registry_audit(self, owner, project_id):
        async with self.sf() as session:
            await self._project(session, owner, project_id)
            rows = await session.execute(select(t.registry_audit).where(t.registry_audit.c.project_id == project_id).order_by(t.registry_audit.c.at, t.registry_audit.c.id))
            return [dict(row) for row in rows.mappings()]
