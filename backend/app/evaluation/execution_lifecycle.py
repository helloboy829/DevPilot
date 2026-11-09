"""Gateway-owned execution service, drained before persistence teardown."""

import asyncio
from contextlib import asynccontextmanager

from app.evaluation.execution import ExecutionPolicy, ExecutionRepository, QAExecutionWorker


async def _stop_and_drain_worker(task):
    # Cancel the original Worker once. Repeated cancellation of Gateway shutdown
    # must not cancel its in-flight network/DB cleanup or permit DB teardown.
    task.cancel()
    waiter = asyncio.gather(task, return_exceptions=True)
    cancelled = False
    while True:
        try:
            await asyncio.shield(waiter)
            break
        except asyncio.CancelledError:
            cancelled = True
    # Do not swallow shutdown cancellation; propagate only after the same Worker
    # has finished draining. A dead process still retains unresolved quota.
    if cancelled:
        raise asyncio.CancelledError


@asynccontextmanager
async def qa_execution_runtime(app, session_factory, config, config_getter):
    # Operator-owned and restart-required. Never synthesize an encryption key,
    # enable paid models, or send requests outside explicitly admitted runs.
    policy = ExecutionPolicy.model_validate(getattr(config, "evaluation_execution", {}))
    repository = ExecutionRepository(session_factory, policy=policy, config_getter=config_getter)
    await repository.initialize()
    app.state.evaluation_execution_repo = repository
    task = asyncio.create_task(QAExecutionWorker(repository, config_getter).serve(), name="qa-json-execution") if policy.enabled else None
    try:
        yield
    finally:
        try:
            if task is not None:
                await _stop_and_drain_worker(task)
        finally:
            app.state.evaluation_execution_repo = None
