"""Deterministic closed-loop scheduling primitives for performance runs."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4


@dataclass(frozen=True, slots=True)
class PerformanceScheduleConfig:
    case_ids: tuple[str, ...]
    concurrency: int
    max_in_flight: int
    warmup_request_count: int
    measured_request_count: int
    wall_time_limit_ns: int
    drain_limit_ns: int
    duration_limit_ns: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.case_ids, tuple):
            raise ValueError("case_ids must be an immutable tuple")
        if not self.case_ids or any(not isinstance(case_id, str) or not case_id for case_id in self.case_ids):
            raise ValueError("case_ids must contain non-empty strings")
        if len(set(self.case_ids)) != len(self.case_ids):
            raise ValueError("case_ids must be unique")
        if type(self.concurrency) is not int or self.concurrency < 1:
            raise ValueError("concurrency must be a positive integer")
        if type(self.max_in_flight) is not int or not 1 <= self.max_in_flight <= self.concurrency:
            raise ValueError("max_in_flight must be between 1 and concurrency")
        if type(self.warmup_request_count) is not int or self.warmup_request_count < 0:
            raise ValueError("warmup_request_count must be a non-negative integer")
        if type(self.measured_request_count) is not int or self.measured_request_count < 1:
            raise ValueError("measured_request_count must be a positive integer")
        if type(self.wall_time_limit_ns) is not int or self.wall_time_limit_ns < 1:
            raise ValueError("wall_time_limit_ns must be a positive integer")
        if type(self.drain_limit_ns) is not int or self.drain_limit_ns < 0:
            raise ValueError("drain_limit_ns must be a non-negative integer")
        if self.duration_limit_ns is not None and (type(self.duration_limit_ns) is not int or self.duration_limit_ns < 1):
            raise ValueError("duration_limit_ns must be a positive integer when set")


@dataclass(frozen=True, slots=True)
class ScheduledDispatch:
    dispatch_id: str
    ordinal: int
    phase: str
    case_id: str
    iteration_index: int


class PerformanceSchedule:
    """Single-coordinator state machine; it does not perform network I/O."""

    def __init__(self, config: PerformanceScheduleConfig) -> None:
        self.config = config
        self._started_at_ns: int | None = None
        self._last_observed_ns: int | None = None
        self._measurement_started_at_ns: int | None = None
        self._window_end_ns: int | None = None
        self._stopped_at_ns: int | None = None
        self._drain_deadline_ns: int | None = None
        self._stop_reason: str | None = None
        self._next_warmup = 0
        self._next_measurement = 0
        self._in_flight: dict[str, ScheduledDispatch] = {}
        self._send_started: set[str] = set()
        self._measurement_resolved: set[str] = set()
        self._unknown: list[ScheduledDispatch] = []
        self._not_started: list[ScheduledDispatch] = []
        self._manifest = self._build_manifest()

    @property
    def manifest(self) -> tuple[ScheduledDispatch, ...]:
        return self._manifest

    def start(self, now_ns: int) -> None:
        if self._started_at_ns is not None:
            raise RuntimeError("schedule has already started")
        self._validate_time(now_ns)
        self._started_at_ns = now_ns
        self._last_observed_ns = now_ns

    def claim(self, now_ns: int) -> ScheduledDispatch | None:
        self._advance(now_ns)
        self._expire_at_deadline(now_ns)
        if self._stop_reason is not None or self.is_finished:
            return None
        if len(self._in_flight) >= self.config.max_in_flight:
            return None

        if self._next_warmup < self.config.warmup_request_count:
            phase = "warmup"
            phase_index = self._next_warmup
            self._next_warmup += 1
        elif self._warmup_complete:
            if self._next_measurement >= self.config.measured_request_count:
                return None
            phase = "measurement"
            phase_index = self._next_measurement
            self._next_measurement += 1
        else:
            return None

        manifest_index = phase_index
        if phase == "measurement":
            manifest_index += self.config.warmup_request_count
        dispatch = self._manifest[manifest_index]
        self._in_flight[dispatch.dispatch_id] = dispatch
        return dispatch

    def send_started(self, dispatch_id: str, now_ns: int) -> None:
        self._advance(now_ns)
        self._expire_at_deadline(now_ns)
        dispatch = self._in_flight.get(dispatch_id)
        if dispatch is None:
            raise KeyError("dispatch is not in flight")
        if dispatch_id in self._send_started:
            raise RuntimeError("dispatch send has already started")
        if self._stop_reason in {"duration", "wall_time_limit"}:
            raise RuntimeError("measurement window is closed")

        self._send_started.add(dispatch_id)
        if dispatch.phase == "measurement":
            if self._measurement_started_at_ns is None:
                self._measurement_started_at_ns = now_ns
            self._measurement_resolved.add(dispatch_id)
            self._stop_if_measurement_budget_resolved(now_ns)

    def cancel_before_send(self, dispatch_id: str, now_ns: int) -> None:
        self._advance(now_ns)
        self._expire_at_deadline(now_ns)
        dispatch = self._in_flight.get(dispatch_id)
        if dispatch is None:
            raise KeyError("dispatch is not in flight")
        if dispatch_id in self._send_started:
            raise RuntimeError("started dispatch cannot be cancelled before send")

        del self._in_flight[dispatch_id]
        self._not_started.append(dispatch)
        if dispatch.phase == "measurement":
            self._measurement_resolved.add(dispatch_id)
            self._stop_if_measurement_budget_resolved(now_ns)
        self._finish_if_drained()

    def complete(self, dispatch_id: str, now_ns: int) -> None:
        self._advance(now_ns)
        self._expire_at_deadline(now_ns)
        if dispatch_id not in self._in_flight:
            raise KeyError("dispatch is not in flight")
        if dispatch_id not in self._send_started:
            raise RuntimeError("dispatch has not started sending")
        del self._in_flight[dispatch_id]
        self._finish_if_drained()

    def expire(self, now_ns: int) -> tuple[str, ...]:
        self._advance(now_ns)
        if self._drain_deadline_ns is None or now_ns < self._drain_deadline_ns:
            return ()
        return self._expire_at_deadline(now_ns)

    @property
    def in_flight_count(self) -> int:
        return len(self._in_flight)

    @property
    def stop_reason(self) -> str | None:
        return self._stop_reason

    @property
    def window_start_ns(self) -> int | None:
        return self._measurement_started_at_ns

    @property
    def window_end_ns(self) -> int | None:
        return self._window_end_ns

    @property
    def drain_deadline_ns(self) -> int | None:
        return self._drain_deadline_ns

    @property
    def unknown_dispatch_ids(self) -> tuple[str, ...]:
        return tuple(dispatch.dispatch_id for dispatch in sorted(self._unknown, key=lambda item: item.ordinal))

    @property
    def not_started_dispatch_ids(self) -> tuple[str, ...]:
        return tuple(dispatch.dispatch_id for dispatch in sorted(self._not_started, key=lambda item: item.ordinal))

    @property
    def is_finished(self) -> bool:
        return self._stop_reason is not None and not self._in_flight and self._stopped_at_ns is not None

    @property
    def _warmup_complete(self) -> bool:
        return self._next_warmup == self.config.warmup_request_count and all(dispatch.phase != "warmup" for dispatch in self._in_flight.values())

    def _advance(self, now_ns: int) -> None:
        if self._started_at_ns is None:
            raise RuntimeError("schedule has not started")
        self._validate_time(now_ns)
        if self._last_observed_ns is not None and now_ns < self._last_observed_ns:
            raise ValueError("monotonic time cannot move backwards")
        self._last_observed_ns = now_ns

        wall_deadline_ns = self._started_at_ns + self.config.wall_time_limit_ns
        if self._stop_reason is None and now_ns >= wall_deadline_ns:
            self._stop("wall_time_limit", wall_deadline_ns)
        elif self._stop_reason is None and self._measurement_started_at_ns is not None:
            duration_ns = self.config.duration_limit_ns
            if duration_ns is not None and now_ns >= self._measurement_started_at_ns + duration_ns:
                self._stop("duration", self._measurement_started_at_ns + duration_ns)

        if self._stop_reason is not None and self._drain_deadline_ns is not None:
            self._drain_deadline_ns = min(self._drain_deadline_ns, wall_deadline_ns)

    def _expire_at_deadline(self, now_ns: int) -> tuple[str, ...]:
        if self._drain_deadline_ns is None or now_ns < self._drain_deadline_ns:
            return ()
        expired_dispatches = sorted(
            (dispatch for dispatch_id, dispatch in self._in_flight.items() if dispatch_id in self._send_started),
            key=lambda item: item.ordinal,
        )
        self._not_started.extend(dispatch for dispatch_id, dispatch in self._in_flight.items() if dispatch_id not in self._send_started)
        self._unknown.extend(expired_dispatches)
        self._in_flight.clear()
        self._finish_if_drained()
        return tuple(dispatch.dispatch_id for dispatch in expired_dispatches)

    def _stop_if_measurement_budget_resolved(self, now_ns: int) -> None:
        if len(self._measurement_resolved) == self.config.measured_request_count:
            self._stop("request_count", now_ns)

    def _stop(self, reason: str, stopped_at_ns: int) -> None:
        if self._stop_reason is not None:
            return
        self._stop_reason = reason
        self._stopped_at_ns = stopped_at_ns
        if reason == "duration":
            self._window_end_ns = stopped_at_ns
        elif reason != "request_count" and self._measurement_started_at_ns is not None:
            self._window_end_ns = stopped_at_ns
        self._drain_deadline_ns = min(
            stopped_at_ns + self.config.drain_limit_ns,
            self._started_at_ns + self.config.wall_time_limit_ns,
        )
        self._finish_if_drained()

    def _finish_if_drained(self) -> None:
        if self._stop_reason is not None and not self._in_flight:
            if self._stopped_at_ns is None:
                self._stopped_at_ns = self._last_observed_ns
            if self._stop_reason == "request_count" and self._window_end_ns is None:
                self._window_end_ns = self._last_observed_ns

    def _build_manifest(self) -> tuple[ScheduledDispatch, ...]:
        entries: list[ScheduledDispatch] = []
        phases = (
            ("warmup", self.config.warmup_request_count),
            ("measurement", self.config.measured_request_count),
        )
        for phase, count in phases:
            for phase_index in range(count):
                entries.append(
                    ScheduledDispatch(
                        dispatch_id=uuid4().hex,
                        ordinal=len(entries),
                        phase=phase,
                        case_id=self.config.case_ids[phase_index % len(self.config.case_ids)],
                        iteration_index=phase_index // len(self.config.case_ids),
                    )
                )
        return tuple(entries)

    @staticmethod
    def _validate_time(now_ns: int) -> None:
        if type(now_ns) is not int or now_ns < 0:
            raise ValueError("monotonic time must be a non-negative integer")
