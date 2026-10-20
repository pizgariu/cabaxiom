"""Isolation. Delta-debugging over the declaration - shrink a failing stack to the smallest edge-closed subset that still shows the charge, then mint the Indictment naming it."""
from abc import ABC, abstractmethod
from collections.abc import Generator, Iterable, Sequence
from typing import final, override

from ...core.declaration.cancellation import Cancellation
from ...core.declaration.step import Step
from ...core.declaration.vocabulary import Vocabulary
from ...core.plan.graph import Graph
from ...core.plan.ordering import Kahn, Ordering
from ...core.record.observer import Observer
from ...core.run.convergence import Convergence
from ...core.run.dispatcher import RunMode
from ...core.run.reconciler import Reconciler
from ...core.run.retry import BaseRetry
from ..proof.idempotence import Idempotence, Proof


class Charge(ABC):
    """The open axis of an isolation: WHICH failure the hunt is chasing, judged over a trial's Proof.

    A charge runs nothing and holds nothing - it is a pure read of the verdict a trial already minted,
    which is what lets one charge serve both colours (a sync trial and an awaited one produce the same
    Proof). Subclass it to hunt your own failure shape - a specific drift name that keeps surviving, a
    churn past a threshold - while the built-ins each read one of the Proof's two channels."""

    @abstractmethod
    def shows(self, proof: Proof) -> bool:
        # Whether the failure under investigation SHOWS in this trial's verdict. The hunt keeps a
        # candidate subset only while it does.
        ...


@final
class Churn(Charge):
    """The idempotence charge, the default. Shows when the trial's second converge still CHANGED
    something - an apply() that keeps working under a clean drift, the failure the residual alone can
    never reveal and the one only this kernel's oracle can even ask about."""

    @override
    def shows(self, proof: Proof) -> bool:
        return bool(proof.churned)


@final
class Stall(Charge):
    """The convergence charge. Shows when the trial never reaches desired state - a residual that
    survives the second converge, a world that will not settle however many passes it gets."""

    @override
    def shows(self, proof: Proof) -> bool:
        return bool(proof.residual)


@final
class Indictment:
    """The verdict of an isolation, closed over four channels. Who stands accused, who was dismissed
    along the way, the evidence and what the hunt cost.

    `accused` holds the per-instance labels of the smallest subset the hunt could not shrink while the
    charge kept showing. Dismissing ANY accused step (together with what stands on it) made the failure
    vanish, so the failure lives in this group's interplay. `dismissed` holds every label dropped while
    the charge still showed - evidence of noninvolvement, never proof, since trials run against a live
    world. `evidence` is the Proof of the last trial in which the accused set showed the charge, attached
    so the conviction is re-runnable. `trials` counts the candidate worlds the hunt built.

    An Indictment is truthy exactly when it accuses someone, so it reads as the assertion it is. A falsy
    one means the charge never showed on the full declaration, so its evidence is that innocent Proof."""
    __slots__ = ("__accused", "__dismissed", "__evidence", "__trials")

    def __init__(self, accused: Sequence[str], dismissed: Sequence[str], evidence: Proof, trials: int):
        # A RECORD, like every verdict the kernel mints. Tuples behind read-only properties, so a caller
        # cannot rewrite a conviction after the hunt that minted it.
        self.__accused = tuple(accused)
        self.__dismissed = tuple(dismissed)
        self.__evidence = evidence
        self.__trials = trials

    @property
    def accused(self) -> tuple[str, ...]:
        return self.__accused

    @property
    def dismissed(self) -> tuple[str, ...]:
        return self.__dismissed

    @property
    def evidence(self) -> Proof:
        return self.__evidence

    @property
    def trials(self) -> int:
        return self.__trials

    def __bool__(self) -> bool:
        return bool(self.__accused)

    def __repr__(self) -> str:
        return (f"Indictment(accused={self.accused!r}, dismissed={self.dismissed!r}, "
                f"trials={self.trials}, evidence={self.evidence!r})")


@final
class Isolation:
    """Delta-debugging over the DECLARATION. Narrow a failing stack to the smallest edge-closed subset
    that still shows the charge, then mint the Indictment naming it - for the operator whose only current
    tool is commenting steps out for an afternoon.

    Every candidate the hunt tries is a down-set of the Graph (a step travels with everything standing on
    it), so every trial is a legal, runnable world - dependencies, required kinds and demanded providers
    all inside - and the charge either shows or it does not, never a construction error. The trial is the
    idempotence protocol. Converge to desired state, converge once more, judge the Proof. That is the same
    second converge Idempotence.prove() runs, generalised into an oracle the Charge reads.

    isolate() is a coroutine now that the engine is async native, driving the shared greedy shrink over
    awaited trials. The shrink lives in __hunting, a generator that yields each candidate subset and is told
    whether the charge showed - the same algorithm-and-driver split as Convergence.passes, so the search is
    never coloured.

    TRIALS ARE REAL RUNS. Every candidate converges twice against whatever world the steps touch, so run an
    isolation against a rehearsal world - a container, a sandbox, a throwaway environment - exactly as you
    would run Idempotence.prove(). And a dismissal is evidence, never proof. Later trials read a world
    earlier trials changed, so the dismissed were not caught, which is weaker than proven innocent."""

    def __init__(self, steps: Iterable[Step], ordering: Ordering | None = None, *,
                 charge: Charge | None = None, mode: RunMode | None = None,
                 convergence: Convergence | None = None, cancellation: Cancellation | None = None,
                 observer: Observer | None = None, retry: BaseRetry | None = None,
                 vocabulary: Vocabulary | None = None):
        # The charge is resolved via None so no shared default instance leaks across isolations (the
        # Priority key precedent). Churn is the default question. The failure only the idempotence oracle
        # can ask about. The reconciler knobs pass straight through to every trial this builds, the
        # dispatcher instance shared across trials - its pool is lock-guarded for that kind of sharing.
        self._steps = tuple(steps)
        self._charge = charge or Churn()
        self._vocabulary = vocabulary
        self._ordering = ordering or Kahn()
        self.__mode = mode
        self.__convergence = convergence
        self.__cancellation = cancellation
        self.__observer = observer
        self.__retry = retry

    def __hunting(self) -> Generator[tuple[Step, ...], bool, tuple[tuple[Step, ...], tuple[Step, ...], int]]:
        # The uncolored hunt - yield a candidate subset, receive whether the charge showed, return the
        # case as (accused, dismissed, trials). Greedy 1-minimal shrink - try dismissing each suspect
        # together with everything standing on it, keep any dismissal the charge survives, then loop until
        # a whole pass dismisses nothing, so no single suspect can leave the accused group.
        graph = Graph(self._steps, self._vocabulary)
        suspects = list(self._steps)
        dismissed: list[Step] = []
        trials = 1
        if not (yield tuple(suspects)):
            return (), (), trials   # the charge never showed on the full declaration: no case
        progress = True
        while progress:
            progress = False
            for suspect in tuple(suspects):
                if suspect not in suspects:
                    continue   # already dismissed this pass, as part of an earlier suspect's fallout
                fallout = Isolation.__standing_on(graph, suspect, suspects)
                candidate = [step for step in suspects if step not in fallout]
                if not candidate:
                    continue   # dismissing the whole case is no trial: the last stand stays accused
                trials += 1
                if (yield tuple(candidate)):
                    dismissed.extend(step for step in suspects if step in fallout)
                    suspects = candidate
                    progress = True
        return tuple(suspects), tuple(dismissed), trials

    @staticmethod
    def __standing_on(graph: Graph, suspect: Step, suspects: list[Step]) -> set[Step]:
        # The suspect plus every remaining suspect standing on it - the transitive dependents, the same
        # walk the Ledger blames with. A candidate must stay a down-set of the Graph, so dismissing a
        # step means dismissing whatever depends on it. Every dependency, required kind and demanded
        # provider of what remains is then still inside, which is what makes every trial a legal,
        # runnable world by construction rather than a resolution error.
        remaining = set(suspects)
        fallout = {suspect}
        frontier = [suspect]
        while frontier:
            for dependent in graph.dependents(frontier.pop()):
                if dependent in remaining and dependent not in fallout:
                    fallout.add(dependent)
                    frontier.append(dependent)
        return fallout

    def __verdict(self, accused: tuple[Step, ...], dismissed: tuple[Step, ...],
                 evidence: Proof, trials: int) -> Indictment:
        # Close the case with the SHARED labeller, over the same RUN order every other reader uses. It
        # tallied over the supplied order here, claiming to apply "the same rule explain() applies" - it
        # applied the same rule to a different order, so `Web#2` on an indictment and `Web#2` on a drawing
        # were different steps, so painting an indictment's accused onto a map reddened the innocent one.
        labels = Step.labelled(self._ordering.flat(Graph(self._steps, self._vocabulary)))
        return Indictment(tuple(labels[step] for step in accused),
                          tuple(labels[step] for step in dismissed), evidence, trials)

    async def isolate(self) -> Indictment:
        # Drive the shared hunt with awaited trials. Each candidate becomes a fresh Reconciler (resolution
        # happens at construction and each candidate is a different world), the idempotence protocol runs,
        # and the charge judges the Proof. The generator owns the algorithm, this driver owns the awaiting
        # - the Convergence.passes split. The evidence tracks the last trial that SHOWED, which is always
        # the accused set's own trial. A failed shrink attempt never overwrites it.
        hunt = self.__hunting()
        candidate = next(hunt)
        evidence = await self.__tried(candidate)
        showing = self._charge.shows(evidence)
        try:
            while True:
                candidate = hunt.send(showing)
                proof = await self.__tried(candidate)
                showing = self._charge.shows(proof)
                if showing:
                    evidence = proof
        except StopIteration as case:
            accused, dismissed, trials = case.value
            return self.__verdict(accused, dismissed, evidence, trials)

    async def __tried(self, candidate: tuple[Step, ...]) -> Proof:
        return await Idempotence(Reconciler(candidate, self._ordering, mode=self.__mode,
                                            convergence=self.__convergence, cancellation=self.__cancellation,
                                            observer=self.__observer, retry=self.__retry, vocabulary=self._vocabulary)).prove()
