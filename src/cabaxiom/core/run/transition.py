"""Transition. Converge from one declaration to the next - prune what left the declaration, then converge the rest."""
from collections.abc import Iterable, Sequence
from typing import final

from ..declaration.cancellation import Cancellation
from ..declaration.drift import Drift
from ..declaration.step import Step
from ..declaration.vocabulary import Vocabulary
from ..plan.ordering import Ordering
from ..record.observer import Observer
from ..record.records import Residual
from .convergence import Convergence
from .dispatcher import RunMode
from .reconciler import Reconciler
from .retry import BaseRetry


@final
class Cutover:
    """The verdict of a transition, over its two halves. What survived the leavers' teardown and what is
    still wrong after the desired set converged.

    `pruned` is the residue the departing steps' prune() left behind - empty when everything they owned is
    gone. `residual` is the desired set's converge outcome - empty when the new declaration is verified
    clean (and its `applied` channel still carries what changed). `clean` is true only when BOTH are empty:
    the old world was torn down completely AND the new one converged, which is what "the transition worked"
    means. A Cutover is truthy exactly when clean, so it reads as the assertion it is."""

    __slots__ = ("__pruned", "__residual", "__clean")

    def __init__(self, pruned: Sequence[Drift], residual: Residual):
        # A RECORD, like every verdict the kernel mints. Pruned is captured as a tuple and both channels
        # sit behind read-only properties. residual stays the Residual value converge() returned, applied
        # channel and all - held rather than copied, because that channel is a documented affordance.
        #
        # The VERDICT is settled here, at mint time, rather than computed from the held list on every read.
        # Holding a live list and deriving `clean` from it meant a caller could append to `cutover.residual`
        # after the fact and flip a clean transition to dirty - the record promised it could not be
        # falsified in place and it could. What was true when the run ended stays true.
        self.__pruned = tuple(pruned)
        self.__residual = residual
        self.__clean = not self.__pruned and not residual

    @property
    def pruned(self) -> tuple[Drift, ...]:
        return self.__pruned

    @property
    def residual(self) -> Residual:
        return self.__residual

    @property
    def clean(self) -> bool:
        return self.__clean

    def __bool__(self) -> bool:
        return self.clean

    def __repr__(self) -> str:
        return f"Cutover(clean={self.clean}, pruned={self.pruned!r}, residual={self.residual!r})"


@final
class Transition:
    """Move a world from its PREVIOUS declaration to the DESIRED one, without a state store.

    A reconciler converges the steps it is handed - but a step REMOVED from the declaration just stops
    being mentioned, so whatever it built leaks forever, since nothing prunes what is no longer declared.
    Full ownership tracking needs persistence, which this kernel deliberately refuses. The stateless form
    does not. The caller still holds the previous declaration, so the difference is computable. A
    Transition tears down exactly the steps present before but absent now (the leavers, in their own
    reverse dependency order, self-verifying like every prune), then converges the desired set and
    returns both proofs as one Cutover.

    It holds the two reconcilers - one over the leavers for the teardown, one over the desired set for the
    converge - and converge() is a coroutine now that the engine is async native. Teardown runs FIRST. A
    leaver may hold what the desired set needs to claim (a port, a path, a name), so the room is made
    before the new world builds.

    WHO IS A LEAVER is `Step.paired`'s answer and not this class's own, which is what lets a successor be
    rebuilt rather than shared. A step that names itself is recognised across the change even as a fresh
    object. Object identity stays the fallback, so a declaration written before identifiers existed
    transitions exactly as it always did. A rebuilt declaration of UNNAMED steps is refused at construction
    rather than torn down, since the two are indistinguishable from here and only one of them is survivable."""

    def __init__(self, previous: Iterable[Step], desired: Iterable[Step], ordering: Ordering | None = None, *,
                 mode: RunMode | None = None, convergence: Convergence | None = None,
                 cancellation: Cancellation | None = None, observer: Observer | None = None,
                 retry: BaseRetry | None = None, vocabulary: Vocabulary | None = None):
        # Both internal reconcilers share the knobs and the dispatcher instance. Scope is deliberately
        # absent. The two sets ARE the selection. ONE vocabulary for both sides, since a cutover spoken in
        # two languages would compare nothing.
        previous, desired = tuple(previous), tuple(desired)
        self._teardown = Reconciler(self.__leavers(previous, desired), ordering, mode=mode,
                                    cancellation=cancellation, observer=observer, retry=retry, vocabulary=vocabulary)
        self._converge = Reconciler(desired, ordering, mode=mode, convergence=convergence,
                                    cancellation=cancellation, observer=observer, retry=retry, vocabulary=vocabulary)

    @staticmethod
    def __leavers(previous: tuple[Step, ...], desired: tuple[Step, ...]) -> tuple[Step, ...]:
        # The set difference, read off the ONE home for the correspondence (Step.paired). Every step declared
        # before and not any more, in the previous declaration's order - its own resolution reverses them.
        # The pairing is what makes a rebuilt successor safe. Matching by instance alone, a declaration
        # reassembled from data made EVERY step a leaver, so the teardown half tore down the whole world and
        # the converge half rebuilt it, which for a real prune is not a misreading but a demolition.
        staying = set(Step.paired(previous, desired).values())
        return tuple(step for step in previous if step not in staying)

    async def converge(self) -> Cutover:
        # Teardown first (make room), then converge, then both proofs as one verdict.
        pruned = await self._teardown.prune()
        return Cutover(pruned, await self._converge.converge())
