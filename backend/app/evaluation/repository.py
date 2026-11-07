"""Owner-scoped data service. All changes and metadata-only audit commit together."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from pydantic import ValidationError
from sqlalchemy import delete, insert, select, update

from app.evaluation import tables as t
from app.evaluation.datasets import QASample, SourceDeclaration, dataset_hash


class NotFound(Exception):
    pass


class Conflict(Exception):
    pass


def now():
    return datetime.now(UTC).isoformat()


class EvaluationRepository:
    def __init__(self, session_factory):
        self.sf = session_factory

    @staticmethod
    async def _project(session, owner, project_id):
        row = (await session.execute(select(t.projects).where(t.projects.c.id == project_id, t.projects.c.owner_id == owner))).mappings().first()
        if row is None:
            raise NotFound
        return dict(row)

    async def _dataset(self, session, owner, project_id, dataset_id):
        await self._project(session, owner, project_id)
        row = (await session.execute(select(t.datasets).where(t.datasets.c.id == dataset_id, t.datasets.c.project_id == project_id))).mappings().first()
        if row is None:
            raise NotFound
        return dict(row)

    @staticmethod
    async def _audit(session, owner, dataset, action):
        await session.execute(insert(t.audit).values(id=uuid4().hex, project_id=dataset["project_id"], dataset_id=dataset["id"], actor=owner, action=action, revision=dataset["revision"], at=now()))

    async def create_project(self, owner: str, name: str):
        row = {"id": uuid4().hex, "owner_id": owner, "name": name, "created_at": now()}
        async with self.sf.begin() as session:
            await session.execute(insert(t.projects).values(**row))
        return row

    async def list_projects(self, owner):
        async with self.sf() as session:
            rows = await session.execute(select(t.projects).where(t.projects.c.owner_id == owner).order_by(t.projects.c.created_at, t.projects.c.id))
            return [dict(row) for row in rows.mappings()]

    async def create_dataset(self, owner, project_id, name, purpose, source: SourceDeclaration):
        row = {
            "id": uuid4().hex,
            "project_id": project_id,
            "name": name,
            "purpose": purpose,
            "source": source.model_dump(),
            "revision": 1,
            "status": "draft",
            "sample_count": 0,
            "content_hash": None,
            "created_at": now(),
            "frozen_at": None,
            "frozen_by": None,
        }
        async with self.sf.begin() as session:
            await self._project(session, owner, project_id)
            await session.execute(insert(t.datasets).values(**row))
            await self._audit(session, owner, row, "dataset_created")
        return row

    async def list_datasets(self, owner, project_id):
        async with self.sf() as session:
            await self._project(session, owner, project_id)
            rows = await session.execute(select(t.datasets).where(t.datasets.c.project_id == project_id).order_by(t.datasets.c.created_at, t.datasets.c.id))
            return [dict(row) for row in rows.mappings()]

    async def get_dataset(self, owner, project_id, dataset_id):
        async with self.sf() as session:
            return await self._dataset(session, owner, project_id, dataset_id)

    async def read_samples(self, owner, project_id, dataset_id, *, references=False):
        async with self.sf.begin() as session:
            dataset = await self._dataset(session, owner, project_id, dataset_id)
            statement = select(t.samples)
            if references:
                statement = select(t.samples, t.references.c.expected).join(t.references, (t.samples.c.dataset_id == t.references.c.dataset_id) & (t.samples.c.sample_id == t.references.c.sample_id))
                await self._audit(session, owner, dataset, "references_read")
            rows = await session.execute(statement.where(t.samples.c.dataset_id == dataset_id).order_by(t.samples.c.sample_id))
            return [dict(row) for row in rows.mappings()]

    async def replace_samples(self, owner, project_id, dataset_id, revision: int, samples: list[QASample]):
        async with self.sf.begin() as session:
            dataset = await self._dataset(session, owner, project_id, dataset_id)
            digest = dataset_hash(dataset["source"], dataset["purpose"], samples)
            changed = await session.execute(
                update(t.datasets).where(t.datasets.c.id == dataset_id, t.datasets.c.revision == revision, t.datasets.c.status == "draft").values(revision=revision + 1, sample_count=len(samples), content_hash=digest)
            )
            if changed.rowcount != 1:
                raise Conflict
            await session.execute(delete(t.references).where(t.references.c.dataset_id == dataset_id))
            await session.execute(delete(t.samples).where(t.samples.c.dataset_id == dataset_id))
            await session.execute(insert(t.samples), [{"dataset_id": dataset_id, **s.model_dump(exclude={"expected"})} for s in samples])
            await session.execute(insert(t.references), [{"dataset_id": dataset_id, "sample_id": s.sample_id, "expected": s.expected} for s in samples])
            dataset.update(revision=revision + 1, sample_count=len(samples), content_hash=digest)
            await self._audit(session, owner, dataset, "samples_replaced")
        return dataset

    async def freeze(self, owner, project_id, dataset_id, revision, content_hash):
        async with self.sf.begin() as session:
            dataset = await self._dataset(session, owner, project_id, dataset_id)
            timestamp = now()
            changed = await session.execute(
                update(t.datasets)
                .where(t.datasets.c.id == dataset_id, t.datasets.c.revision == revision, t.datasets.c.status == "draft", t.datasets.c.sample_count > 0, t.datasets.c.content_hash == content_hash)
                .values(status="frozen", revision=revision + 1, frozen_at=timestamp, frozen_by=owner)
            )
            if changed.rowcount != 1:
                raise Conflict
            # Recompute from the locked, persisted rows, not client assertions.
            rows = (
                (
                    await session.execute(
                        select(t.samples, t.references.c.expected).join(t.references, (t.samples.c.dataset_id == t.references.c.dataset_id) & (t.samples.c.sample_id == t.references.c.sample_id)).where(t.samples.c.dataset_id == dataset_id)
                    )
                )
                .mappings()
                .all()
            )
            try:
                persisted = [QASample.model_validate({k: v for k, v in row.items() if k != "dataset_id"}) for row in rows]
            except ValidationError:
                raise Conflict from None
            if len(persisted) != dataset["sample_count"] or dataset_hash(dataset["source"], dataset["purpose"], persisted) != content_hash:
                raise Conflict
            dataset.update(status="frozen", revision=revision + 1, frozen_at=timestamp, frozen_by=owner)
            await self._audit(session, owner, dataset, "dataset_frozen")
        return dataset

    async def audit(self, owner, project_id, dataset_id):
        async with self.sf() as session:
            await self._dataset(session, owner, project_id, dataset_id)
            rows = await session.execute(select(t.audit).where(t.audit.c.dataset_id == dataset_id).order_by(t.audit.c.at, t.audit.c.id))
            return [dict(row) for row in rows.mappings()]
