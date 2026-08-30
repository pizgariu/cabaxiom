"""Retry - per-step attempts for the write phase, paced by a Backoff, spent before the OnError policy.
    A Cancelled raised by a step is never retried, yet no branch here says so. It is a BaseException, so
    the attempt loop's own `except Exception` structurally cannot catch it and the abort propagates with
    nothing spent asking. The cut-through stopped being code and became a property of the type.
    """
import asyncio
import inspect
from collections.abc import Callable
from typing import final

from .convergence import Backoff
from .drift import Changes, Outcome
from .step import Step

# A write's outcome. The changes it reports (or None), returned directly by a sync step or as an
# awaitable by an async one under the Async dispatcher. Retry passes the outcome straight through and
# awaits only its OWN retries, so it stays agnostic to which dispatcher is driving.


@final
class Retry:
    """How many tries a single step's write (apply or prune) gets before its failure counts.

    The Reconciler calls the injected Retry on the write callable before handing it to the dispatcher,
    so the attempts are spent inside the dispatcher's own unit of work, uniformly under Serial,
    Parallel, Pipeline and Async, with no dispatcher aware of them. A failure reaches the OnError
    policy only once every attempt is spent, so retry layers UNDER the error policy. FailFast aborts
    on a step that failed all its tries, BestEffort records exactly one residual entry for it. Only
    the writes are wrapped. The reads (drift, plan, audit, footprint) stay single-try, since the
    re-probe is the proof of the run and a probe that needs retrying is reporting something worth
    seeing. An optional Backoff paces the attempts, the same Fixed and Exponential that pace
    Fixpoint passes. Retry(1) is the neutral single try that wraps nothing.
    """

    def __init__(self, attempts: int, *, backoff: Backoff | None = None):
        if attempts < 1:
            raise ValueError(f"Retry attempts must be >= 1, got {attempts}")
        self.__attempts = attempts
        self.__backoff = backoff

    def __call__(self, do: Callable[[Step], Outcome]) -> Callable[[Step], Outcome]:
        # Wrap the per-step write callable in the attempt loop and hand back the wrapped form. The neutral
        # single try hands back do itself, so the default costs nothing.
        if self.__attempts == 1:
            return do

        async def retrying(step: Step) -> Changes:
            # ONE loop, because the engine is one colour now. A write that raises synchronously on the call
            # (a connection setup dying before the coroutine is even built) and one that raises on await
            # both land in the same try and spend one attempt, so neither escapes the budget or the pacing.
            # The two loops this replaces differed only in the shape of their wait, while a mirror is two
            # implementations of one idea with the second one always slightly wrong.
            for failed in range(1, self.__attempts):
                try:
                    outcome = do(step)
                    return await outcome if inspect.isawaitable(outcome) else outcome
                except Exception:   # any write failure is a retry candidate, the net the dispatcher also uses
                    await self.__pace(failed)
            last = do(step)   # the last try, its failure is the real one and propagates to OnError
            return await last if inspect.isawaitable(last) else last

        return retrying

    async def __pace(self, failed: int) -> None:
        # The pause between tries, if any, awaited on the event loop's own sleep off the pure delay(), so a
        # paced retry never blocks the wave-mates it shares the loop with. `failed` counts the consecutive
        # failures so far, the same stall count Fixpoint hands its backoff, so both axes speak one vocabulary.
        if self.__backoff is not None:
            await asyncio.sleep(self.__backoff.delay(failed))
