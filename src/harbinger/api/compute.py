"""Bounded FIFO admission for in-process model computation.

Waiting is finite; timeout bounds only admission, never interrupts a running model.
The gate is per worker, as are the in-memory upload sessions.
"""

from collections import deque
from contextlib import contextmanager
from threading import Condition

from fastapi import HTTPException


class ComputeGate:
    def __init__(self, slots=2, waiting=4, timeout=10.0):
        if slots < 1 or waiting < 0 or timeout <= 0:
            raise ValueError("Compute limits must have positive slots/timeout and nonnegative waiting")
        self.slots, self.waiting, self.timeout = slots, waiting, timeout
        self.condition = Condition()
        self.active = 0
        self.queue = deque()

    def reject(self, reason):
        raise HTTPException(
            429,
            "계산 요청이 많습니다. 잠시 뒤 다시 시도하세요.",
            headers={"Retry-After": "1", "X-Harbinger-Capacity": reason},
        )

    @contextmanager
    def slot(self):
        with self.condition:
            if self.active >= self.slots or self.queue:
                if len(self.queue) >= self.waiting:
                    self.reject("queue_full")
                ticket = object()
                self.queue.append(ticket)
                self.condition.notify_all()
                acquired = False
                try:
                    acquired = self.condition.wait_for(
                        lambda: self.active < self.slots and self.queue[0] is ticket,
                        timeout=self.timeout,
                    )
                finally:
                    self.queue.remove(ticket)
                    self.condition.notify_all()
                if not acquired:
                    self.reject("wait_timeout")
            self.active += 1
        try:
            yield
        finally:
            with self.condition:
                self.active -= 1
                self.condition.notify_all()
