"""Gateway-owned execution service, drained before persistence teardown."""

import asyncio
from contextlib import asynccontextmanager

from app.evaluation.execution import ExecutionPolicy, ExecutionRepository, QAExecutionWorker


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
        if task is not None:
            task.cancel()
            # The original worker drains its transaction/network tasks before
            # releasing quota. Hard process death deliberately retains quota.
            await asyncio.gather(task, return_exceptions=True)
        app.state.evaluation_execution_repo = None
