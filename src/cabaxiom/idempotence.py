"""Idempotence. Prove a Reconciler settles to a fixpoint and STAYS there - a second converge is a clean no-op."""
from collections.abc import Sequence
from typing import final

from .drift import Drift
from .reconciler import Reconciler
from .records import Residual


@final
class Proof:
    """The verdict of an idempotence check, over the second converge's two channels. What it CHANGED and what
    it left WRONG. The two catch different failures and keeping them apart says which one happened.

    `churned` is what the second converge's apply() reported doing. On an idempotent reconciler it is empty -
    the first converge reached desired state, the second found nothing left to do. A non-empty `churned` is the
    tell of an apply() that keeps working even when drift() reads clean. The residual alone hides that, since
    the residual is empty whenever drift() is clean, so it is the second converge's APPLIED channel that catches
    the churn.

    `residual` is what was still wrong after that second converge. It is empty when the reconciler actually
    reached desired state. A non-empty residual means it never converged at all - a different failure from
    churn. It is also the reason both channels are surfaced rather than collapsed to one flag.

    `stable` is true only when BOTH are empty. The second converge changed nothing (idempotent) AND left
    nothing wrong (converged). A Proof is truthy exactly when stable, so it reads as the assertion it is."""

    __slots__ = ("__churned", "__residual")

    def __init__(self, churned: Sequence[Drift], residual: Sequence[Drift]):
        # A RECORD, like every verdict the kernel mints. The channels are captured as tuples behind
        # read-only properties, so a caller cannot falsify the proof in place after it was minted.
        self.__churned = tuple(churned)
        self.__residual = tuple(residual)

    @property
    def churned(self) -> tuple[Drift, ...]:
        return self.__churned

    @property
    def residual(self) -> tuple[Drift, ...]:
        return self.__residual

    @property
    def stable(self) -> bool:
        return not self.churned and not self.residual

    def __bool__(self) -> bool:
        return self.stable

    def __repr__(self) -> str:
        return f"Proof(stable={self.stable}, churned={self.churned!r}, residual={self.residual!r})"


# NOT @final. A custom harness subclasses this to shape its own proving protocol, inheriting the
# wrapped reconciler and the shared _verdict rule - which tests/test_idempotence.py exercises and
# which a @final here would forbid outright.
class Idempotence:
    """Proves a Reconciler is idempotent, wrapping one (has-a, never is-a). prove() converges to
    desired state, then converges ONCE MORE and checks the second pass was a clean no-op. It ships the
    property both examples hand-roll - "a second converge on a settled world changes nothing" - as a
    first-class check that catches a non-idempotent apply() that churns while assess() reads clean, which no
    single converge reveals.

    prove() is a coroutine, since the engine is async native. It awaits two converges on the caller's own
    event loop and returns a Proof."""

    def __init__(self, reconciler: Reconciler):
        self._reconciler = reconciler

    @staticmethod
    def _verdict(second: Residual) -> Proof:
        # The closing rule. Pair what the second converge changed (the churn) with what it left wrong (the
        # residual), so the Proof says WHICH failure it found - or that neither happened. Proof snapshots
        # its channels itself, so no defensive copy is owed here.
        return Proof(second.applied, second)

    async def prove(self) -> Proof:
        # First converge reaches desired state. The second must be a clean no-op and _verdict reads it.
        await self._reconciler.converge()
        return self._verdict(await self._reconciler.converge())

