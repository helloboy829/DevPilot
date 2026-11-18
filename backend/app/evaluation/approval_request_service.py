"""App account checks for assigned signatures; no reviewer account role."""

from collections.abc import Awaitable, Callable

from app.evaluation.approval_requests import ApprovalRequestRepository
from app.evaluation.repository import Conflict


class ApprovalRequestService:
    def __init__(self, repository: ApprovalRequestRepository, account_ready: Callable[[str], Awaitable[bool]]):
        self.repository = repository
        self.account_ready = account_ready

    async def create_request(self, owner, project_id, run_id, request_id, payload):
        # Exact account lookup only after ownership; never expose a directory.
        await self.repository.check_project(owner, project_id)
        if not await self.account_ready(payload.approver_id):
            raise Conflict
        return await self.repository.create_request(owner, project_id, run_id, request_id, payload)

    async def decide(self, actor, request_id, operation_id, payload):
        request = await self.repository.get_request(actor, request_id)
        if actor != request["approver_id"] or not await self.account_ready(actor):
            raise Conflict
        return await self.repository.decide(actor, request_id, operation_id, payload)
