"""多级签核要求纯核心单测：不存储策略、不强制、不代表批准。"""

from __future__ import annotations

import unittest

from devpilot.qa_signoff_policy import evaluate_signoff_requirement


class SignoffRequirementTest(unittest.TestCase):
    def test_explicit_policy_is_satisfied_by_enough_approved_approvers(self):
        result = evaluate_signoff_requirement(
            required_distinct_approvers=2,
            distinct_approved_approvers=2,
            latest_decision="approved",
        )
        self.assertEqual(result["schema"], "qa-signoff-requirement.v1")
        self.assertEqual(result["scope"], "technical_signoff_requirement_only")
        self.assertTrue(result["satisfied"])
        self.assertEqual(result["blockers"], [])
        self.assertEqual(result["approval"], "not_approved")

    def test_undefined_policy_is_never_satisfied(self):
        result = evaluate_signoff_requirement(
            required_distinct_approvers=None,
            distinct_approved_approvers=2,
            latest_decision="approved",
        )
        self.assertIsNone(result["satisfied"])
        self.assertEqual(result["blockers"], ["multi_level_policy_not_defined"])
        self.assertIsNone(result["policy"]["required_distinct_approvers"])

    def test_insufficient_approvers_block(self):
        result = evaluate_signoff_requirement(
            required_distinct_approvers=3,
            distinct_approved_approvers=2,
            latest_decision="approved",
        )
        self.assertFalse(result["satisfied"])
        self.assertEqual(result["blockers"], ["insufficient_approvers"])

    def test_latest_revocation_or_missing_decision_blocks(self):
        for latest in ("revoked", None):
            result = evaluate_signoff_requirement(
                required_distinct_approvers=1,
                distinct_approved_approvers=1,
                latest_decision=latest,
            )
            self.assertFalse(result["satisfied"])
            self.assertEqual(result["blockers"], ["latest_decision_not_approved"])

    def test_multiple_blockers_are_sorted_and_deduplicated(self):
        result = evaluate_signoff_requirement(
            required_distinct_approvers=3,
            distinct_approved_approvers=0,
            latest_decision="revoked",
        )
        self.assertFalse(result["satisfied"])
        self.assertEqual(
            result["blockers"],
            ["insufficient_approvers", "latest_decision_not_approved"],
        )

    def test_zero_required_is_invalid(self):
        with self.assertRaises(ValueError):
            evaluate_signoff_requirement(
                required_distinct_approvers=0,
                distinct_approved_approvers=0,
                latest_decision="approved",
            )

    def test_type_spoofing_and_unknown_decisions_fail_closed(self):
        for required, approved, latest in (
            (True, 1, "approved"),
            (1, True, "approved"),
            (1, -1, "approved"),
            (11, 1, "approved"),
            (1, 1, "approved "),
            (1, 1, "unknown"),
        ):
            with self.assertRaises(ValueError):
                evaluate_signoff_requirement(
                    required_distinct_approvers=required,
                    distinct_approved_approvers=approved,
                    latest_decision=latest,
                )


if __name__ == "__main__":
    unittest.main()
