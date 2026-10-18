"""Settle - the outer-loop stop condition - how many converge() passes a watch() loop runs before it is done."""
from abc import ABC, abstractmethod
from collections.abc import Generator, Sequence
from typing import final, override

from ..declaration.drift import Drift
from ..declaration.errors import Misconfigured


class Settle(ABC):
    """Strategy for when a watch() loop is done, decided across passes.

    Convergence governs how many apply -> re-probe passes run inside one converge(). Settle governs how many
    converge() passes a caller drives a `Reconciler.watch()` loop through before stopping. The same "how long
    do we keep going?" question at the loop's outer layer. It is a generator, fresh per loop so it carries no
    state between runs. The caller primes it with next(), then feeds each pass's residual through send() and
    the generator yields whether the loop should stop. It never returns - the caller breaks out of watch()
    when the generator yields True.
    """
    @abstractmethod
    def watch(self) -> Generator[bool, Sequence[Drift], None]:
        ...


@final
class Clean(Settle):
    """Stop on the first clean pass. An empty residual means desired state was reached. The default and the
    behaviour a watch() loop takes when its caller applies no other stop condition."""
    @override
    def watch(self) -> Generator[bool, Sequence[Drift], None]:
        stop = False   # the priming yield, before any tick has run
        while True:
            residual = yield stop
            stop = not residual   # a clean residual means desired state reached, so stop


@final
class Stable(Settle):
    """Stop only after `passes` CONSECUTIVE clean passes - proof the world stayed converged, not that it was
    clean once. In a flapping world a single clean re-probe is a false all-clear - external drift can reappear
    on the next observation - so Stable(3) certifies three re-observations in a row found nothing, the real
    difference between "converged once" and "stable". A dirty pass resets the streak, so Stable(1) is Clean."""

    def __init__(self, passes: int = 2):
        if passes < 1:
            raise Misconfigured(f"Stable passes must be >= 1, got {passes}")
        self.__passes = passes

    @override
    def watch(self) -> Generator[bool, Sequence[Drift], None]:
        clean_streak = 0
        stop = False
        while True:
            residual = yield stop
            clean_streak = clean_streak + 1 if not residual else 0   # a dirty tick breaks the streak
            stop = clean_streak >= self.__passes
