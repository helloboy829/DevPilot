import unittest

from devpilot.performance_schedule import (
    PerformanceSchedule,
    PerformanceScheduleConfig,
)


class PerformanceScheduleTests(unittest.TestCase):
    def make_schedule(self, **overrides: object) -> PerformanceSchedule:
        values: dict[str, object] = {
            "case_ids": ("case-a", "case-b"),
            "concurrency": 2,
            "max_in_flight": 2,
            "warmup_request_count": 2,
            "measured_request_count": 3,
            "wall_time_limit_ns": 100_000,
            "drain_limit_ns": 10_000,
        }
        values.update(overrides)
        return PerformanceSchedule(PerformanceScheduleConfig(**values))

    def test_measurement_waits_for_all_warmup_requests_to_complete(self) -> None:
        schedule = self.make_schedule()
        schedule.start(0)

        warmup_a = schedule.claim(1)
        warmup_b = schedule.claim(1)
        self.assertEqual((warmup_a.phase, warmup_b.phase), ("warmup", "warmup"))
        schedule.send_started(warmup_a.dispatch_id, 1)
        schedule.send_started(warmup_b.dispatch_id, 1)
        self.assertIsNone(schedule.claim(1))

        schedule.complete(warmup_a.dispatch_id, 2)
        self.assertIsNone(schedule.claim(2))
        schedule.complete(warmup_b.dispatch_id, 3)

        measurement = schedule.claim(4)
        self.assertEqual(measurement.phase, "measurement")
        self.assertEqual(measurement.case_id, "case-a")
        self.assertIsNone(schedule.window_start_ns)
        schedule.send_started(measurement.dispatch_id, 5)
        self.assertEqual(schedule.window_start_ns, 5)

    def test_claims_respect_concurrency_and_cycle_frozen_cases(self) -> None:
        schedule = self.make_schedule(warmup_request_count=0, measured_request_count=5)
        frozen_manifest = schedule.manifest
        schedule.start(0)

        first = schedule.claim(10)
        second = schedule.claim(10)
        self.assertEqual((first.case_id, second.case_id), ("case-a", "case-b"))
        schedule.send_started(first.dispatch_id, 10)
        schedule.send_started(second.dispatch_id, 10)
        self.assertIsNone(schedule.claim(10))

        schedule.complete(first.dispatch_id, 11)
        third = schedule.claim(12)
        self.assertEqual((third.case_id, third.iteration_index), ("case-a", 1))
        self.assertEqual((first, second, third), frozen_manifest[:3])
        self.assertEqual(schedule.in_flight_count, 2)

    def test_manifest_is_complete_before_start_and_cycles_each_phase(self) -> None:
        schedule = self.make_schedule(warmup_request_count=3, measured_request_count=3)
        manifest = schedule.manifest

        self.assertEqual(len(manifest), 6)
        self.assertEqual(
            tuple((item.phase, item.case_id, item.iteration_index) for item in manifest),
            (
                ("warmup", "case-a", 0),
                ("warmup", "case-b", 0),
                ("warmup", "case-a", 1),
                ("measurement", "case-a", 0),
                ("measurement", "case-b", 0),
                ("measurement", "case-a", 1),
            ),
        )

    def test_request_count_first_limit_stops_dispatch_and_drains(self) -> None:
        schedule = self.make_schedule(
            warmup_request_count=0,
            measured_request_count=2,
            concurrency=1,
            max_in_flight=1,
        )
        schedule.start(0)

        first = schedule.claim(10)
        schedule.send_started(first.dispatch_id, 10)
        schedule.complete(first.dispatch_id, 11)
        second = schedule.claim(12)
        schedule.send_started(second.dispatch_id, 15)

        self.assertEqual(schedule.stop_reason, "request_count")
        self.assertIsNone(schedule.window_end_ns)
        self.assertIsNone(schedule.claim(16))
        self.assertEqual(schedule.drain_deadline_ns, 10_015)

        schedule.complete(second.dispatch_id, 17)
        self.assertTrue(schedule.is_finished)
        self.assertEqual(schedule.window_end_ns, 17)
        self.assertEqual(schedule.unknown_dispatch_ids, ())

    def test_duration_first_limit_marks_remaining_dispatch_unknown_at_drain_deadline(
        self,
    ) -> None:
        schedule = self.make_schedule(
            warmup_request_count=0,
            measured_request_count=20,
            concurrency=2,
            max_in_flight=2,
            duration_limit_ns=50,
            drain_limit_ns=20,
        )
        schedule.start(0)
        first = schedule.claim(100)
        second = schedule.claim(100)
        self.assertIsNotNone(first)
        schedule.send_started(first.dispatch_id, 100)
        schedule.send_started(second.dispatch_id, 100)

        self.assertIsNone(schedule.claim(150))
        self.assertEqual(schedule.stop_reason, "duration")
        self.assertEqual(schedule.window_end_ns, 150)
        self.assertEqual(schedule.drain_deadline_ns, 170)

        schedule.complete(first.dispatch_id, 160)
        self.assertEqual(schedule.expire(170), (second.dispatch_id,))
        self.assertEqual(schedule.unknown_dispatch_ids, (second.dispatch_id,))
        self.assertTrue(schedule.is_finished)
        with self.assertRaises(KeyError):
            schedule.complete(second.dispatch_id, 171)
        self.assertIsNone(schedule.claim(171))

    def test_wall_time_limit_caps_drain_and_never_reclaims_unknown_work(self) -> None:
        schedule = self.make_schedule(
            warmup_request_count=0,
            measured_request_count=20,
            concurrency=2,
            max_in_flight=2,
            duration_limit_ns=500,
            wall_time_limit_ns=120,
            drain_limit_ns=100,
        )
        schedule.start(0)
        first = schedule.claim(100)
        queued = schedule.claim(100)
        schedule.send_started(first.dispatch_id, 100)

        self.assertIsNone(schedule.claim(120))
        self.assertEqual(schedule.stop_reason, "wall_time_limit")
        self.assertEqual(schedule.drain_deadline_ns, 120)
        self.assertEqual(schedule.expire(120), ())
        self.assertEqual(schedule.unknown_dispatch_ids, (first.dispatch_id,))
        self.assertEqual(schedule.not_started_dispatch_ids, (queued.dispatch_id,))
        self.assertTrue(schedule.is_finished)
        self.assertIsNone(schedule.claim(121))

    def test_measurement_duration_starts_at_send_and_blocks_late_send(self) -> None:
        schedule = self.make_schedule(
            warmup_request_count=0,
            measured_request_count=4,
            concurrency=2,
            max_in_flight=2,
            duration_limit_ns=50,
            drain_limit_ns=20,
        )
        schedule.start(0)
        first = schedule.claim(10)
        self.assertIsNone(schedule.window_start_ns)

        schedule.send_started(first.dispatch_id, 20)
        queued = schedule.claim(69)
        self.assertIsNone(schedule.stop_reason)
        with self.assertRaises(RuntimeError):
            schedule.send_started(queued.dispatch_id, 70)

        self.assertEqual(schedule.stop_reason, "duration")
        self.assertEqual(schedule.window_start_ns, 20)
        self.assertEqual(schedule.window_end_ns, 70)
        schedule.cancel_before_send(queued.dispatch_id, 70)
        self.assertEqual(schedule.not_started_dispatch_ids, (queued.dispatch_id,))
        self.assertEqual(schedule.unknown_dispatch_ids, ())

    def test_measurement_count_limit_ends_on_last_send_started(self) -> None:
        schedule = self.make_schedule(
            warmup_request_count=0,
            measured_request_count=2,
            concurrency=2,
            max_in_flight=2,
        )
        schedule.start(0)
        first = schedule.claim(10)
        second = schedule.claim(10)
        schedule.send_started(first.dispatch_id, 12)
        self.assertIsNone(schedule.stop_reason)
        schedule.send_started(second.dispatch_id, 15)

        self.assertEqual(schedule.stop_reason, "request_count")
        self.assertEqual(schedule.window_start_ns, 12)
        self.assertIsNone(schedule.window_end_ns)
        self.assertIsNone(schedule.claim(16))
        schedule.complete(first.dispatch_id, 16)
        self.assertIsNone(schedule.window_end_ns)
        schedule.complete(second.dispatch_id, 19)
        self.assertEqual(schedule.window_end_ns, 19)

    def test_count_limited_window_ends_when_drain_classifies_unknown(self) -> None:
        schedule = self.make_schedule(
            warmup_request_count=0,
            measured_request_count=2,
            concurrency=2,
            max_in_flight=2,
            drain_limit_ns=20,
        )
        schedule.start(0)
        first = schedule.claim(10)
        second = schedule.claim(10)
        schedule.send_started(first.dispatch_id, 11)
        schedule.send_started(second.dispatch_id, 12)
        schedule.complete(first.dispatch_id, 15)

        self.assertIsNone(schedule.window_end_ns)
        self.assertEqual(schedule.expire(32), (second.dispatch_id,))
        self.assertEqual(schedule.window_end_ns, 32)
        self.assertEqual(schedule.unknown_dispatch_ids, (second.dispatch_id,))

    def test_send_started_requires_a_claim_and_is_one_time(self) -> None:
        schedule = self.make_schedule(warmup_request_count=0)
        schedule.start(0)
        with self.assertRaises(KeyError):
            schedule.send_started("unknown-dispatch", 1)

        dispatch = schedule.claim(1)
        schedule.send_started(dispatch.dispatch_id, 2)
        with self.assertRaises(RuntimeError):
            schedule.send_started(dispatch.dispatch_id, 3)

    def test_invalid_limits_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            PerformanceScheduleConfig(
                case_ids=(),
                concurrency=0,
                max_in_flight=0,
                warmup_request_count=0,
                measured_request_count=0,
                wall_time_limit_ns=0,
                drain_limit_ns=0,
            )

    def test_case_ids_must_be_an_immutable_tuple(self) -> None:
        with self.assertRaises(ValueError):
            self.make_schedule(case_ids=["case-a", "case-b"])


if __name__ == "__main__":
    unittest.main()
