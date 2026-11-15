"""多级签核要求的技术投影：纯逻辑、无存储、无强制、无批准。

只回答“在调用方显式提供的策略下，现有聚合计数是否满足要求”。策略本身
不由本模块定义、保存或推断；未定义策略时永不返回满足。
"""

from __future__ import annotations

_MAX_REQUIRED = 10
_DECISIONS = frozenset({"approved", "revoked"})


def evaluate_signoff_requirement(
    *,
    required_distinct_approvers,
    distinct_approved_approvers,
    latest_decision,
):
    """Return a fixed technical requirement projection.

    ``required_distinct_approvers=None`` means no policy is defined. Missing or
    revoked latest decisions and too few distinct approved approvers block.
    The result never constitutes approval.
    """
    if required_distinct_approvers is not None and (
        type(required_distinct_approvers) is not int
        or not 1 <= required_distinct_approvers <= _MAX_REQUIRED
    ):
        raise ValueError("Invalid sign-off requirement")
    if (
        type(distinct_approved_approvers) is not int
        or not 0 <= distinct_approved_approvers <= _MAX_REQUIRED
    ):
        raise ValueError("Invalid approved approver count")
    if latest_decision is not None and (
        type(latest_decision) is not str or latest_decision not in _DECISIONS
    ):
        raise ValueError("Invalid latest decision")
    blockers = set()
    if required_distinct_approvers is None:
        blockers.add("multi_level_policy_not_defined")
    elif distinct_approved_approvers < required_distinct_approvers:
        blockers.add("insufficient_approvers")
    if latest_decision != "approved":
        blockers.add("latest_decision_not_approved")
    satisfied = None if required_distinct_approvers is None else not blockers
    return {
        "schema": "qa-signoff-requirement.v1",
        "scope": "technical_signoff_requirement_only",
        "policy": {
            "defined": required_distinct_approvers is not None,
            "required_distinct_approvers": required_distinct_approvers,
        },
        "observed": {
            "distinct_approved_approvers": distinct_approved_approvers,
            "latest_decision": latest_decision,
        },
        "satisfied": satisfied,
        "blockers": sorted(blockers),
        "approval": "not_approved",
    }


__all__ = ["evaluate_signoff_requirement"]
