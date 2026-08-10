"""Convergence strategies for how many times to repeat apply -> re-probe: Once, Fixpoint, and the Backoff that paces Fixpoint's retries."""
import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import final

from ._compat import override
from .drift import Drift


class Convergence(ABC):
    """Strategy for how many times to repeat the apply -> re-probe cycle.

    converge is a zero-arg callable that runs one cycle and returns its residual Drift. The
    strategy invokes it as its policy dictates and returns the final residual. Injected at
    construction so the public converge() stays argument-free.
    """
    @abstractmethod
    def __call__(self, converge: Callable[[], list[Drift]]) -> list[Drift]:
        ...


@final
class Once(Convergence):
    """Run exactly one apply -> re-probe cycle."""
    @override
    def __call__(self, converge: Callable[[], list[Drift]]) -> list[Drift]:
        return converge()


class Backoff(ABC):
    """How long to pause before a retry, as a function of how many times in a row it has stalled.

    Fixpoint stops the moment a pass leaves the residual unchanged, reading it as settled or stuck.
    That is right for an in-process convergence, where re-probing at once cannot change the answer.
    It is wrong for a step whose drift clears only once some external state catches up (a rollout
    finishing, a cache expiring, a queue draining): there the same drift now can be gone in a moment.
    Hand Fixpoint a Backoff and an unchanged pass no longer ends the loop. Fixpoint waits, then
    retries, still bounded by max_passes, giving the world time to settle. Retry paces a single
    step's write attempts with the same vocabulary. delay() is the pure policy, the seconds to
    pause before retrying the nth consecutive stall (1 on the first). wait() is the blocking form
    built on it, which Fixpoint and the sync write paths use on the calling thread. An async
    consumer reads delay() and awaits the event loop's own sleep instead, so a pause never blocks
    the coroutines sharing the loop.
    """
    @abstractmethod
    def delay(self, stalled: int) -> float:
        ...

    def wait(self, stalled: int) -> None:
        time.sleep(self.delay(stalled))


@final
class Fixed(Backoff):
    """Pause the same number of seconds before every retry, however long the stall has run."""
    def __init__(self, seconds: float):
        if seconds < 0:
            raise ValueError(f"Fixed backoff seconds must be >= 0, got {seconds}")
        self.__seconds = seconds

    @override
    def delay(self, stalled: int) -> float:
        return self.__seconds


@final
class Exponential(Backoff):
    """Double the pause on each consecutive stall, from base up to cap seconds.

    The nth stall pauses base * 2 ** (n - 1), clamped to cap, so a loop that keeps meeting the
    same drift steps back further each time instead of re-probing at full tilt. cap bounds the
    single longest pause, the consumer's own ceiling (max_passes, attempts) bounds how many there
    can be.
    """
    def __init__(self, base: float, cap: float):
        if base < 0:
            raise ValueError(f"Exponential backoff base must be >= 0, got {base}")
        if cap < base:
            raise ValueError(f"Exponential backoff cap must be >= base, got cap={cap}, base={base}")
        self.__base = base
        self.__cap = cap

    @override
    def delay(self, stalled: int) -> float:
        return float(min(self.__base * 2 ** (stalled - 1), self.__cap))


@final
class Fixpoint(Convergence):
    """Repeat the apply -> re-probe cycle until the residual stops changing or max_passes is reached.

    Some steps only reach desired state once an earlier step's apply() has made room: one pass
    clears what it can, the next clears what the first unblocked, and so on. Settling is by value:
    two residuals are equal when their (name, message) multisets match, so the loop stops as soon
    as a pass changes nothing (converged clean, or genuinely stuck). max_passes is the hard ceiling
    that guarantees termination even when a step never settles.

    An optional backoff changes what an unchanged pass means. Without one it is terminal. With one
    it becomes a paced retry: Fixpoint waits (growing the wait as stalls repeat) and re-probes again,
    up to max_passes, for drift that clears only once external state catches up. See Backoff.
    """

    def __init__(self, max_passes: int = 10, *, backoff: Backoff | None = None):
        if max_passes < 1:
            raise ValueError(f"Fixpoint max_passes must be >= 1, got {max_passes}")
        self.__max_passes = max_passes
        self.__backoff = backoff

    @override
    def __call__(self, converge: Callable[[], list[Drift]]) -> list[Drift]:
        residual = converge()
        stalled = 0
        for _ in range(self.__max_passes - 1):
            if not residual:
                break  # converged clean
            previous = sorted((item.name, item.message) for item in residual)
            residual = converge()
            if sorted((item.name, item.message) for item in residual) != previous:
                stalled = 0   # progress this pass, so a later stall backs off from scratch
                continue
            # The pass changed nothing: settled or stuck. Terminal, unless a backoff turns it into a
            # paced retry for drift that is only waiting on external state to catch up.
            if self.__backoff is None:
                break
            stalled += 1
            self.__backoff.wait(stalled)
        return residual
