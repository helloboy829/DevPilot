"""Owner-scoped persistence for project-external material intake batches."""

from __future__ import annotations

import re
from uuid import uuid4

from sqlalchemy import insert, select, update

from app.evaluation import tables as t
from app.evaluation.material_intake import MaterialBatchCreate
from app.evaluation.repository import Conflict, NotFound, now


class MaterialIntakeRepository:
    def __init__(self, session_factory):
        self.sf = session_factory

    async def create(self, owner: str, manifest: MaterialBatchCreate):
        batch_id = uuid4().hex
        timestamp = now()
        artifact_ids = {item.attachment_id: "mat_" + uuid4().hex for item in manifest.attachments}
        batch = {
            "id": batch_id,
            "owner_id": owner,
            "name": manifest.name,
            "status": "open",
            "component_count": len(manifest.components),
            "created_at": timestamp,
            "updated_at": timestamp,
            "archived_at": None,
        }
        components = [
            {
                "batch_id": batch_id,
                "component_id": item.component_id,
                "name": item.name,
                "kind": item.kind,
                "purpose": item.purpose,
                "status": "pending",
                "reason": None,
            }
            for item in manifest.components
        ]
        artifacts = [
            {
                "id": artifact_ids[item.attachment_id],
                "batch_id": batch_id,
                "file_name": item.file_name,
                "authorization_basis": item.authorization_basis,
                "purpose": item.purpose,
                "sensitivity": item.sensitivity,
                "retention_until": item.retention_until.isoformat(),
                "status": "pending_upload",
                "storage_key": None,
                "sha256": None,
                "size_bytes": None,
                "created_at": timestamp,
                "uploaded_at": None,
                "parse_status": "pending",
                "parser_version": None,
                "parse_result_hash": None,
                "parse_block_count": None,
                "parse_reason": None,
                "parsed_at": None,
            }
            for item in manifest.attachments
        ]
        mappings = [
            {
                "batch_id": batch_id,
                "artifact_id": artifact_ids[attachment_id],
                "component_id": component.component_id,
            }
            for component in manifest.components
            for attachment_id in component.attachment_ids
        ]
        async with self.sf.begin() as session:
            await session.execute(insert(t.material_batches).values(**batch))
            if components:
                await session.execute(insert(t.material_components), components)
            if artifacts:
                await session.execute(insert(t.material_artifacts), artifacts)
            if mappings:
                await session.execute(insert(t.material_artifact_components), mappings)
        return self._serialize(batch, components, artifacts, mappings)

    async def list(self, owner: str, *, limit: int = 50, offset: int = 0):
        if not 1 <= limit <= 100 or offset < 0:
            raise ValueError("Invalid material batch page")
        async with self.sf() as session:
            rows = await session.execute(select(t.material_batches).where(t.material_batches.c.owner_id == owner).order_by(t.material_batches.c.created_at.desc(), t.material_batches.c.id.desc()).limit(limit).offset(offset))
            return [self._serialize_batch(dict(row)) for row in rows.mappings()]

    async def get(self, owner: str, batch_id: str):
        async with self.sf() as session:
            batch = (
                (
                    await session.execute(
                        select(t.material_batches).where(
                            t.material_batches.c.owner_id == owner,
                            t.material_batches.c.id == batch_id,
                        )
                    )
                )
                .mappings()
                .first()
            )
            if batch is None:
                raise NotFound
            components = (await session.execute(select(t.material_components).where(t.material_components.c.batch_id == batch_id).order_by(t.material_components.c.component_id))).mappings().all()
            artifacts = (await session.execute(select(t.material_artifacts).where(t.material_artifacts.c.batch_id == batch_id).order_by(t.material_artifacts.c.id))).mappings().all()
            mappings = (await session.execute(select(t.material_artifact_components).where(t.material_artifact_components.c.batch_id == batch_id))).mappings().all()
        return self._serialize(dict(batch), [dict(row) for row in components], [dict(row) for row in artifacts], [dict(row) for row in mappings])

    async def get_upload_target(self, owner: str, batch_id: str, artifact_id: str):
        async with self.sf() as session:
            row = (
                (
                    await session.execute(
                        select(t.material_batches.c.status.label("batch_status"), t.material_artifacts.c.file_name, t.material_artifacts.c.status.label("artifact_status"), t.material_artifacts.c.retention_until)
                        .join(t.material_artifacts, t.material_artifacts.c.batch_id == t.material_batches.c.id)
                        .where(t.material_batches.c.id == batch_id, t.material_batches.c.owner_id == owner, t.material_artifacts.c.id == artifact_id)
                    )
                )
                .mappings()
                .first()
            )
        if row is None or row["batch_status"] != "open":
            raise NotFound
        return {"file_name": row["file_name"], "status": row["artifact_status"], "retention_until": row["retention_until"]}

    async def record_upload(self, owner: str, batch_id: str, artifact_id: str, *, sha256: str, size_bytes: int):
        if not re.fullmatch(r"[0-9a-f]{64}", sha256) or type(size_bytes) is not int or not 0 <= size_bytes <= 100 * 1024 * 1024:
            raise ValueError("Invalid material upload metadata")
        async with self.sf.begin() as session:
            row = (
                (
                    await session.execute(
                        select(t.material_batches.c.status.label("batch_status"), t.material_artifacts)
                        .join(t.material_artifacts, t.material_artifacts.c.batch_id == t.material_batches.c.id)
                        .where(t.material_batches.c.id == batch_id, t.material_batches.c.owner_id == owner, t.material_artifacts.c.id == artifact_id)
                    )
                )
                .mappings()
                .first()
            )
            if row is None or row["batch_status"] != "open":
                raise NotFound
            if row["status"] == "uploaded":
                if row["sha256"] != sha256 or row["size_bytes"] != size_bytes:
                    raise Conflict
                return
            if row["status"] != "pending_upload":
                raise Conflict
            await session.execute(
                update(t.material_artifacts)
                .where(t.material_artifacts.c.batch_id == batch_id, t.material_artifacts.c.id == artifact_id, t.material_artifacts.c.status == "pending_upload")
                .values(status="uploaded", storage_key=artifact_id, sha256=sha256, size_bytes=size_bytes, uploaded_at=now())
            )

    async def get_preview_target(self, owner: str, batch_id: str, artifact_id: str):
        async with self.sf() as session:
            row = (
                (
                    await session.execute(
                        select(
                            t.material_batches.c.status.label("batch_status"),
                            t.material_artifacts.c.status.label("artifact_status"),
                            t.material_artifacts.c.file_name,
                            t.material_artifacts.c.storage_key,
                            t.material_artifacts.c.sha256,
                            t.material_artifacts.c.size_bytes,
                            t.material_artifacts.c.retention_until,
                        )
                        .join(t.material_artifacts, t.material_artifacts.c.batch_id == t.material_batches.c.id)
                        .where(
                            t.material_batches.c.owner_id == owner,
                            t.material_batches.c.id == batch_id,
                            t.material_artifacts.c.id == artifact_id,
                        )
                    )
                )
                .mappings()
                .first()
            )
        if row is None or row["batch_status"] != "open":
            raise NotFound
        return dict(row)

    async def record_preview(
        self,
        owner: str,
        batch_id: str,
        artifact_id: str,
        *,
        operation_id: str,
        parse_status: str,
        parser_version: str,
        result_hash: str,
        block_count: int,
        reason: str | None,
    ):
        if parse_status not in {"parsed", "blocked"} or not re.fullmatch(r"[0-9a-f]{64}", result_hash):
            raise ValueError("Invalid material preview receipt")
        if type(block_count) is not int or not 0 <= block_count <= 20_000:
            raise ValueError("Invalid material preview block count")
        timestamp = now()
        receipt = {
            "operation_id": operation_id,
            "owner_id": owner,
            "batch_id": batch_id,
            "artifact_id": artifact_id,
            "parse_status": parse_status,
            "parser_version": parser_version,
            "result_hash": result_hash,
            "block_count": block_count,
            "reason": reason,
            "created_at": timestamp,
        }
        async with self.sf.begin() as session:
            target = (
                (
                    await session.execute(
                        select(t.material_artifacts.c.status, t.material_batches.c.status.label("batch_status"))
                        .join(t.material_batches, t.material_batches.c.id == t.material_artifacts.c.batch_id)
                        .where(
                            t.material_batches.c.owner_id == owner,
                            t.material_batches.c.id == batch_id,
                            t.material_artifacts.c.id == artifact_id,
                        )
                    )
                )
                .mappings()
                .first()
            )
            if target is None or target["batch_status"] != "open":
                raise NotFound
            if target["status"] != "uploaded":
                raise Conflict
            existing = (await session.execute(select(t.material_preview_receipts.c.operation_id).where(t.material_preview_receipts.c.operation_id == operation_id))).first()
            if existing is not None:
                raise Conflict
            await session.execute(insert(t.material_preview_receipts).values(**receipt))
            await session.execute(
                update(t.material_artifacts)
                .where(t.material_artifacts.c.id == artifact_id, t.material_artifacts.c.batch_id == batch_id)
                .values(
                    parse_status=parse_status,
                    parser_version=parser_version,
                    parse_result_hash=result_hash,
                    parse_block_count=block_count,
                    parse_reason=reason,
                    parsed_at=timestamp,
                )
            )
            mappings = (await session.execute(select(t.material_artifact_components.c.component_id).where(t.material_artifact_components.c.batch_id == batch_id, t.material_artifact_components.c.artifact_id == artifact_id))).scalars().all()
            for component_id in mappings:
                statuses = (
                    (
                        await session.execute(
                            select(t.material_artifacts.c.parse_status)
                            .join(t.material_artifact_components, t.material_artifact_components.c.artifact_id == t.material_artifacts.c.id)
                            .where(
                                t.material_artifact_components.c.batch_id == batch_id,
                                t.material_artifact_components.c.component_id == component_id,
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                component_status = "blocked" if "blocked" in statuses else "parsed" if statuses and all(item == "parsed" for item in statuses) else "pending"
                if component_status != "pending":
                    await session.execute(
                        update(t.material_components)
                        .where(
                            t.material_components.c.batch_id == batch_id,
                            t.material_components.c.component_id == component_id,
                            t.material_components.c.status.in_(["pending", "parsed", "blocked"]),
                        )
                        .values(status=component_status, reason=reason if component_status == "blocked" else None)
                    )
        return {key: receipt[key] for key in ("operation_id", "parse_status", "parser_version", "result_hash", "block_count", "reason", "created_at")}

    async def get_preview_receipt(self, owner: str, operation_id: str):
        async with self.sf() as session:
            row = (
                (
                    await session.execute(
                        select(t.material_preview_receipts).where(
                            t.material_preview_receipts.c.owner_id == owner,
                            t.material_preview_receipts.c.operation_id == operation_id,
                        )
                    )
                )
                .mappings()
                .first()
            )
        if row is None:
            raise NotFound
        return {key: row[key] for key in ("operation_id", "parse_status", "parser_version", "result_hash", "block_count", "reason", "created_at")}

    @staticmethod
    def _serialize(batch, components, artifacts, mappings):
        artifact_ids_by_component = {}
        for mapping in mappings:
            artifact_ids_by_component.setdefault(mapping["component_id"], []).append(mapping["artifact_id"])
        safe_components = [
            {
                "component_id": component["component_id"],
                "name": component["name"],
                "kind": component["kind"],
                "purpose": component["purpose"],
                "status": component["status"],
                "reason": component["reason"],
                "artifact_ids": sorted(artifact_ids_by_component.get(component["component_id"], [])),
            }
            for component in components
        ]
        safe_artifacts = [
            {
                key: artifact[key]
                for key in (
                    "id",
                    "file_name",
                    "authorization_basis",
                    "purpose",
                    "sensitivity",
                    "retention_until",
                    "status",
                    "sha256",
                    "size_bytes",
                    "created_at",
                    "uploaded_at",
                    "parse_status",
                    "parser_version",
                    "parse_result_hash",
                    "parse_block_count",
                    "parse_reason",
                    "parsed_at",
                )
            }
            for artifact in artifacts
        ]
        safe_batch = MaterialIntakeRepository._serialize_batch(batch)
        return {**safe_batch, "components": safe_components, "artifacts": safe_artifacts}

    @staticmethod
    def _serialize_batch(batch):
        return {key: batch[key] for key in ("id", "name", "status", "component_count", "created_at", "updated_at", "archived_at")}
