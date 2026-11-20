import pytest
from sqlalchemy import insert, update
from sqlalchemy.exc import IntegrityError
from test_dispatch_journal import prepared as prepared
from test_dispatch_journal import record

from app.evaluation import tables as t


@pytest.mark.asyncio
async def test_response_artifact_manifest_checks_status_hash_and_encryption_receipt(prepared):
    repo, _, project, _, _ = prepared
    run = await record(prepared)
    base = {
        "id": "a" * 32,
        "project_id": project,
        "run_id": run["id"],
        "ordinal": 1,
        "status": "pending",
        "hash_scope": "none",
        "request_body_sha256": None,
        "request_body_bytes": None,
        "request_contract_version": None,
        "response_sha256": None,
        "captured_prefix_sha256": None,
        "captured_bytes": 0,
        "observed_bytes": 0,
        "content_type": None,
        "content_encoding": None,
        "key_version": None,
        "sealed_sha256": None,
        "sealed_bytes": None,
        "receipt_hash": None,
        "created_at_ms": 1_800_000_000_001,
        "updated_at_ms": 1_800_000_000_001,
    }

    async with repo.sf.begin() as session:
        await session.execute(insert(t.response_artifacts).values(**base))
        await session.execute(
            update(t.response_artifacts)
            .where(t.response_artifacts.c.id == base["id"])
            .values(
                status="write_failed",
                hash_scope="full",
                response_sha256="d" * 64,
                captured_bytes=4,
                observed_bytes=4,
                request_body_sha256="a" * 64,
                request_body_bytes=128,
                request_contract_version="qa-json-request.v1",
                updated_at_ms=base["updated_at_ms"] + 1,
            )
        )

    lower_run = await record(prepared)
    lower_bound = {
        **base,
        "id": "b" * 32,
        "run_id": lower_run["id"],
        "ordinal": 1,
        "status": "complete",
        "hash_scope": "full",
        "request_body_sha256": "a" * 64,
        "request_body_bytes": 128,
        "request_contract_version": "qa-json-request.v1",
        "response_sha256": "e" * 64,
        "captured_bytes": 4,
        "observed_bytes": 4,
        "key_version": "a" * 16,
        "sealed_sha256": "f" * 64,
        "sealed_bytes": 4 + 28,
        "receipt_hash": "1" * 64,
    }
    async with repo.sf.begin() as session:
        await session.execute(insert(t.response_artifacts).values(**lower_bound))

    upper_run = await record(prepared)
    upper_bound = {
        **base,
        "id": "e" * 32,
        "run_id": upper_run["id"],
        "ordinal": 1,
        "status": "complete",
        "hash_scope": "full",
        "request_body_sha256": "a" * 64,
        "request_body_bytes": 128,
        "request_contract_version": "qa-json-request.v1",
        "response_sha256": "e" * 64,
        "captured_bytes": 4,
        "observed_bytes": 4,
        "key_version": "a" * 16,
        "sealed_sha256": "f" * 64,
        "sealed_bytes": 4 + 2113,
        "receipt_hash": "1" * 64,
    }
    async with repo.sf.begin() as session:
        await session.execute(insert(t.response_artifacts).values(**upper_bound))

    missing_request_run = await record(prepared)
    with pytest.raises(IntegrityError):
        async with repo.sf.begin() as session:
            await session.execute(
                insert(t.response_artifacts).values(
                    {
                        **upper_bound,
                        "id": "3" * 32,
                        "run_id": missing_request_run["id"],
                        "request_body_sha256": None,
                        "request_body_bytes": None,
                        "request_contract_version": None,
                    }
                )
            )

    over_run = await record(prepared)
    with pytest.raises(IntegrityError):
        async with repo.sf.begin() as session:
            await session.execute(insert(t.response_artifacts).values({**upper_bound, "id": "2" * 32, "run_id": over_run["id"], "sealed_bytes": 4 + 2114}))

    invalid = [
        {"status": "green"},
        {"status": "complete"},
        {"request_body_sha256": None, "request_body_bytes": 128, "request_contract_version": "qa-json-request.v1"},
        {"request_body_sha256": "g" * 64},
        {"request_body_sha256": "A" * 64},
        {"request_body_bytes": -1},
        {"request_body_bytes": 262145},
        {"request_contract_version": ""},
        {"request_contract_version": "v" * 33},
        {"hash_scope": "full", "response_sha256": "a" * 64},
        {"hash_scope": "prefix", "captured_prefix_sha256": "b" * 64},
        {"sealed_sha256": "c" * 64},
        {"captured_bytes": -1},
        {"observed_bytes": 1_048_578},
        {"content_encoding": "x" * 17},
        {"updated_at_ms": base["created_at_ms"] - 1},
    ]
    for index, changes in enumerate(invalid, start=1):
        with pytest.raises(IntegrityError):
            async with repo.sf.begin() as session:
                await session.execute(insert(t.response_artifacts).values({**base, "id": f"{index:032x}", **changes}))

    with pytest.raises(IntegrityError):
        async with repo.sf.begin() as session:
            await session.execute(insert(t.response_artifacts).values({**base, "id": "f" * 32}))
