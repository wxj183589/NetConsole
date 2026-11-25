from __future__ import annotations

from netconsole.services.ground_unattended.heartbeat_supervisor import HeartbeatSupervisor


class _FakeClock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value


class _AdvancingEvent:
    def __init__(self, clock: _FakeClock) -> None:
        self.clock = clock

    def wait(self, timeout: float) -> bool:
        self.clock.value += timeout
        return False

    def clear(self) -> None:
        pass


class _StopAfterTicks:
    def __init__(self, stop_after: int) -> None:
        self.stop_after = stop_after
        self.ticks = 0

    def is_set(self) -> bool:
        return self.ticks >= self.stop_after


def test_scheduler_uses_monotonic_deadlines_and_skips_missed_slots() -> None:
    clock = _FakeClock()
    stop_event = _StopAfterTicks(3)
    supervisor = object.__new__(HeartbeatSupervisor)
    supervisor.monotonic_provider = clock
    supervisor.tick_seconds = 1.0
    supervisor._stop_event = stop_event
    supervisor._wake_event = _AdvancingEvent(clock)
    supervisor._operation_lock = _NullLock()
    supervisor.site_id = "fixture"
    tick_starts: list[float] = []
    tick_durations = iter((0.4, 1.4, 0.1))

    def tick() -> None:
        tick_starts.append(clock())
        clock.value += next(tick_durations)
        stop_event.ticks += 1

    supervisor._tick = tick
    supervisor._failure_count = 0
    supervisor._last_error = ""

    supervisor._run()

    assert tick_starts == [0.0, 1.0, 3.0]


class _NullLock:
    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None
