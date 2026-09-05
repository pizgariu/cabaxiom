"""Settle - the outer loop's stop condition. How many converge() passes a watch() runs before it is done."""
from abc import ABC, abstractmethod
from collections.abc import Sequence

from ._compat import override
from .drift import Drift


class Settle(ABC):
    """WHEN a standing run is finished, asked once per pass with that pass's residual.

    Distinct from Convergence, which is the INNER loop and decides how many apply-then-probe cycles make
    up ONE converge. This is the outer one. It decides how many converges make a session. Keeping
    them apart is what lets a caller pace the retries of a single reconciliation differently from the
    patience of the loop watching for the world to move again.

    An injected axis rather than a flag, because "done" is a domain judgement. A deploy is done at the
    first clean pass. A soak wants several in a row before it believes the world settled. A monitor is
    never done at all and says so by never returning True."""

    @abstractmethod
    def settled(self, residual: Sequence[Drift]) -> bool:
        # Asked once per pass, with what that pass could not fix. Returning True ends the loop.
        ...


class Clean(Settle):
    """Done at the first pass that leaves nothing behind. The default and the honest reading of
    "empty means verified" - one clean pass IS the proof, so waiting for a second asks for more than
    the kernel claims."""

    @override
    def settled(self, residual: Sequence[Drift]) -> bool:
        return not residual


class Stable(Settle):
    """Done after `passes` CONSECUTIVE clean passes, where the counter resets on any pass that is not.

    For a world with slow external actors, where one clean reading can be a gap between two writes
    somebody else is making rather than the end of them. Stable(1) is Clean with more ceremony, so it
    refuses anything below 2 rather than quietly being a synonym."""

    def __init__(self, passes: int = 2):
        if passes < 2:
            raise ValueError(f"Stable passes must be >= 2, got {passes} - one clean pass is Clean()")
        self.__passes = passes
        self.__clean = 0

    @override
    def settled(self, residual: Sequence[Drift]) -> bool:
        # The reset is the point. Consecutive means consecutive, so a dirty pass in the middle of a
        # streak puts the count back to nothing rather than merely failing to advance it.
        self.__clean = self.__clean + 1 if not residual else 0
        return self.__clean >= self.__passes
