"""Retry: per-step attempts for the write phase, paced by a Backoff, spent before the OnError policy.
    A Cancelled raised by a step is never retried, and no branch here says so. It is a BaseException, so
    the attempt loop's own `except Exception` structurally cannot catch it and the abort propagates with
    nothing spent asking. The cut-through stopped being code and became a property of the type.
    """
import asyncio
import inspect
from collections.abc import Awaitable, Callable
from typing import cast, final

from .convergence import Backoff
from .drift import Drift
from .step import Step

# A write's outcome: the changes it reports (or None), returned directly by a sync step, or as an
# awaitable by an async one under the Async executor. Retry passes the outcome straight through and
# awaits only its OWN retries, so it stays agnostic to which executor is driving.
Changes = list[Drift] | None
Outcome = Changes | Awaitable[Changes]


@final
class Retry:
    """How many tries a single step's write (apply or prune) gets before its failure counts.

    The Reconciler calls the injected Retry on the write callable before handing it to the executor,
    so the attempts are spent inside the executor's own unit of work, uniformly under Serial,
    Parallel, Pipeline and Async, with no executor aware of them. A failure reaches the OnError
    policy only once every attempt is spent, so retry layers UNDER the error policy: FailFast aborts
    on a step that failed all its tries, BestEffort records exactly one residual entry for it. Only
    the writes are wrapped. The reads (drift, plan, audit, footprint) stay single-try, since the
    re-probe is the proof of the run and a probe that needs retrying is reporting something worth
    seeing. An optional Backoff paces the attempts, the same Fixed and Exponential that pace
    Fixpoint passes. Retry(1) is the neutral single try, and wraps nothing.
    """

    def __init__(self, attempts: int, *, backoff: Backoff | None = None):
        if attempts < 1:
            raise ValueError(f"Retry attempts must be >= 1, got {attempts}")
        self.__attempts = attempts
        self.__backoff = backoff

    def __call__(self, do: Callable[[Step], Outcome]) -> Callable[[Step], Outcome]:
        # Wrap the per-step write callable in the attempt loop and hand back the wrapped form. The
        # neutral single try hands back do itself, so the default costs nothing. A coroutine outcome
        # goes to the async twin, since a coroutine is single-use and its exception only surfaces on await.
        if self.__attempts == 1:
            return do

        def retrying(step: Step) -> Outcome:
            for failed in range(1, self.__attempts):
                try:
                    outcome = do(step)
                except Exception:   # any write failure is a retry candidate, the same net the executor catches
                    self.__pace(failed)
                else:
                    if inspect.isawaitable(outcome):
                        return self.__rerun(step, do, outcome)
                    return outcome
            return do(step)   # the last try: its failure is the real one and propagates to OnError

        return retrying

    def __pace(self, failed: int) -> None:
        # The pause between tries, if any. `failed` counts the consecutive failures so far, the
        # same stall count Fixpoint hands its backoff.
        if self.__backoff is not None:
            self.__backoff.wait(failed)

    async def __rerun(self, step: Step, do: Callable[[Step], Outcome], first: Awaitable[Changes]) -> Changes:
        # The async twin of the attempt loop, for a step whose write is a coroutine. Each retry calls
        # do again for a fresh coroutine (one cannot be re-awaited), and the pause awaits the event
        # loop's own sleep off the backoff's pure delay(), never blocking wave-mates. On this path do
        # yields awaitables (its first outcome was one), so each fresh call is cast back to one.
        pending = first
        for failed in range(1, self.__attempts):
            try:
                return await pending
            except Exception:   # same broad net as the sync loop, only the shape of the wait differs
                if self.__backoff is not None:
                    await asyncio.sleep(self.__backoff.delay(failed))
                pending = cast(Awaitable[Changes], do(step))
        return await pending   # the last try, its failure propagates to OnError
