"""Application orchestration for owner-recorded, advisory formal approvals.

Account readiness belongs to App, persistence and target integrity to the
repository, and requirement arithmetic to the shared DevPilot core.
"""

from collections.abc import Awaitable, Callable

from devpilot.qa_signoff_policy import evaluate_signoff_requirement

from app.evaluation.qa_approvals import ApprovalRepository
from app.evaluation.repository import Conflict, NotFound


class ApprovalService:
    def __init__(self, repository: ApprovalRepository, account_ready: Callable[[str], Awaitable[bool]]):
        self.repository = repository
        self.account_ready = account_ready

    async def preview(self, owner, project_id, run_id, assessment_id, approver_id):
        result = await self.repository.preview_approval(owner, project_id, run_id, assessment_id, approver_id)
        if not await self.account_ready(approver_id):
            result["eligible"] = False
            result["blockers"] = sorted({*result["blockers"], "approver_account_not_found"})
        return result

    async def create(self, owner, project_id, run_id, approval_id, payload):
        # Ownership must precede account lookup to avoid exposing account state.
        await self.repository.check_project(owner, project_id)
        if not await self.account_ready(payload.approver_id):
            raise Conflict
        return await self.repository.create_approval(owner, project_id, run_id, approval_id, payload)

    async def signoff_progress(self, owner, project_id, run_id, required=None):
        progress = await self.repository.approval_signoff_progress(owner, project_id, run_id)
        try:
            stored = await self.repository.get_signoff_policy(owner, project_id)
        except NotFound:
            stored = None
        if stored is not None:
            progress["stored_policy"] = stored
        threshold = required if required is not None else (stored["required_distinct_approvers"] if stored else None)
        if threshold is not None:
            progress["requirement"] = evaluate_signoff_requirement(
                required_distinct_approvers=threshold,
                distinct_approved_approvers=progress["distinct_approved_approvers"],
                latest_decision=progress["latest_decision"],
            )
            progress["requirement"]["source"] = "request_only" if required is not None else "stored_advisory"
        return progress
