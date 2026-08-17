from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from deerflow.persistence.component_tests.model import ComponentRow, ComponentTestRunRow
from deerflow.utils.time import coerce_iso

_COMPONENT_DATETIME_FIELDS = ("created_at", "updated_at")
_RUN_DATETIME_FIELDS = ("created_at", "started_at", "completed_at")


class ComponentRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    @staticmethod
    def _row_to_dict(row: ComponentRow) -> dict[str, Any]:
        data = row.to_dict()
        for key in _COMPONENT_DATETIME_FIELDS:
            if data.get(key) is not None:
                data[key] = coerce_iso(data[key])
        return data

    async def create(
        self,
        *,
        component_id: str,
        user_id: str,
        name: str,
        component_code: str | None,
        transport: str,
        api_url: str,
        api_token: str | None,
        response_mode: str,
        supports_streaming: bool,
        validation_type: str,
        acceptance_criteria: dict[str, Any],
    ) -> dict[str, Any]:
        now = datetime.now(UTC)
        row = ComponentRow(
            id=component_id,
            user_id=user_id,
            name=name,
            component_code=component_code,
            transport=transport,
            api_url=api_url,
            api_token=api_token,
            response_mode=response_mode,
            supports_streaming=supports_streaming,
            validation_type=validation_type,
            acceptance_criteria=acceptance_criteria,
            created_at=now,
            updated_at=now,
        )
        async with self._sf() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return self._row_to_dict(row)

    async def get(self, component_id: str, *, user_id: str) -> dict[str, Any] | None:
        async with self._sf() as session:
            row = await session.get(ComponentRow, component_id)
            if row is None or row.user_id != user_id:
                return None
            return self._row_to_dict(row)

    async def list_by_user(self, user_id: str) -> list[dict[str, Any]]:
        stmt = select(ComponentRow).where(ComponentRow.user_id == user_id).order_by(ComponentRow.created_at.desc(), ComponentRow.id.desc())
        async with self._sf() as session:
            result = await session.execute(stmt)
            return [self._row_to_dict(row) for row in result.scalars()]

    async def update(
        self,
        component_id: str,
        *,
        user_id: str,
        updates: dict[str, Any],
    ) -> dict[str, Any] | None:
        async with self._sf() as session:
            row = await session.get(ComponentRow, component_id)
            if row is None or row.user_id != user_id:
                return None
            for key, value in updates.items():
                if hasattr(row, key):
                    setattr(row, key, value)
            row.updated_at = datetime.now(UTC)
            await session.commit()
            await session.refresh(row)
            return self._row_to_dict(row)

    async def delete(self, component_id: str, *, user_id: str) -> bool:
        async with self._sf() as session:
            row = await session.get(ComponentRow, component_id)
            if row is None or row.user_id != user_id:
                return False
            await session.delete(row)
            await session.commit()
            return True


class ComponentTestRunRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    @staticmethod
    def _row_to_dict(row: ComponentTestRunRow) -> dict[str, Any]:
        data = row.to_dict()
        for key in _RUN_DATETIME_FIELDS:
            if data.get(key) is not None:
                data[key] = coerce_iso(data[key])
        return data

    async def create(
        self,
        *,
        run_id: str,
        user_id: str,
        component_id: str,
        test_type: str,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        now = datetime.now(UTC)
        row = ComponentTestRunRow(
            id=run_id,
            user_id=user_id,
            component_id=component_id,
            test_type=test_type,
            params=params,
            created_at=now,
        )
        async with self._sf() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return self._row_to_dict(row)

    async def get(self, run_id: str, *, user_id: str) -> dict[str, Any] | None:
        async with self._sf() as session:
            row = await session.get(ComponentTestRunRow, run_id)
            if row is None or row.user_id != user_id:
                return None
            return self._row_to_dict(row)

    async def list_by_user(self, user_id: str) -> list[dict[str, Any]]:
        stmt = select(ComponentTestRunRow).where(ComponentTestRunRow.user_id == user_id).order_by(ComponentTestRunRow.created_at.desc(), ComponentTestRunRow.id.desc())
        async with self._sf() as session:
            result = await session.execute(stmt)
            return [self._row_to_dict(row) for row in result.scalars()]

    async def list_by_component(self, component_id: str, *, user_id: str) -> list[dict[str, Any]]:
        stmt = (
            select(ComponentTestRunRow)
            .where(
                ComponentTestRunRow.user_id == user_id,
                ComponentTestRunRow.component_id == component_id,
            )
            .order_by(ComponentTestRunRow.created_at.desc(), ComponentTestRunRow.id.desc())
        )
        async with self._sf() as session:
            result = await session.execute(stmt)
            return [self._row_to_dict(row) for row in result.scalars()]

    async def update(
        self,
        run_id: str,
        *,
        user_id: str,
        updates: dict[str, Any],
    ) -> dict[str, Any] | None:
        async with self._sf() as session:
            row = await session.get(ComponentTestRunRow, run_id)
            if row is None or row.user_id != user_id:
                return None
            for key, value in updates.items():
                if hasattr(row, key):
                    setattr(row, key, value)
            await session.commit()
            await session.refresh(row)
            return self._row_to_dict(row)
