from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable


@dataclass
class ScheduledJob:
    name: str
    interval: float
    next_due: float = 0.0


@dataclass
class MRClientScheduler:
    jobs: dict[str, ScheduledJob]
    clock: Callable[[], float] = time.monotonic
    loop_sleep_seconds: float = 0.2
    max_catch_up_ticks: int = 1

    @classmethod
    def from_intervals(cls, intervals: dict[str, int], clock: Callable[[], float] | None = None) -> "MRClientScheduler":
        now_clock = clock or time.monotonic
        return cls(
            jobs={
                name: ScheduledJob(name=name, interval=max(0.1, float(interval)), next_due=0.0)
                for name, interval in intervals.items()
                if int(interval) > 0
            },
            clock=now_clock,
        )

    def due_jobs(self, now: float | None = None) -> list[str]:
        current = self.clock() if now is None else now
        return [name for name, job in self.jobs.items() if current + 1e-9 >= job.next_due]

    def due_tasks(self, now: float | None = None) -> list[str]:
        return self.due_jobs(now)

    def mark_ran(self, name: str, started_at: float, finished_at: float | None = None) -> None:
        job = self.jobs[name]
        current = self.clock() if finished_at is None else finished_at
        next_due = job.next_due
        ticks = 0
        while next_due <= started_at + 1e-9 and ticks < self.max_catch_up_ticks:
            next_due += job.interval
            ticks += 1
        if next_due <= current:
            next_due = current + job.interval
        job.next_due = next_due

    def sleep_duration(self, now: float | None = None) -> float:
        if not self.jobs:
            return self.loop_sleep_seconds
        current = self.clock() if now is None else now
        wait = min(job.next_due for job in self.jobs.values()) - current
        return max(0.0, min(self.loop_sleep_seconds, wait))
