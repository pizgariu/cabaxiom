"""Siege. Delta-debugging over the FAULT - shrink an injected failure to the smallest one that still breaks
convergence, then mint the Breach naming it."""
from collections.abc import Generator, Iterable, Sequence
from typing import final

from .adversary import ChaosDispatcher, Targeted
from .cancellation import Cancellation
from .convergence import Convergence
from .dispatcher import Parallel, RunMode
from .graph import Graph
from .idempotence import Idempotence, Proof
from .isolation import Charge, Churn
from .ledger import OnError
from .observer import Observer
from .ordering import Kahn, Ordering
from .reconciler import Reconciler
from .retry import BaseRetry
from .step import Step
from .vocabulary import Vocabulary


@final
class Breach:
    """The verdict of a siege, closed over four channels. Which faults broke the run, which the run
    survived, the evidence and what the hunt cost.

    `breached` holds the per-instance labels of the smallest fault set the hunt could not shrink while the
    charge kept showing. Lifting ANY of them let the declaration converge, so THIS is the weather your
    stack cannot take. `survived` holds every fault lifted while the charge still showed - the failures the
    declaration absorbed, which is a claim worth as much as the one it could not. `evidence` is the Proof
    of the last trial the surviving fault set broke, attached so the finding is re-runnable. `trials`
    counts the worlds the hunt built.

    A Breach is truthy exactly when something breached, so it reads as the assertion it is. A falsy one
    means the declaration converged even under EVERY fault the siege could lay, so its evidence is that
    unbroken Proof - which is the stronger result and the one worth asserting in a suite."""

    __slots__ = ("__breached", "__survived", "__evidence", "__trials")

    def __init__(self, breached: Sequence[str], survived: Sequence[str], evidence: Proof, trials: int):
        # A RECORD, like every verdict the kernel mints. Tuples behind read-only properties, so a caller
        # cannot rewrite a finding after the hunt that minted it.
        self.__breached = tuple(breached)
        self.__survived = tuple(survived)
        self.__evidence = evidence
        self.__trials = trials

    @property
    def breached(self) -> tuple[str, ...]:
        return self.__breached

    @property
    def survived(self) -> tuple[str, ...]:
        return self.__survived

    @property
    def evidence(self) -> Proof:
        return self.__evidence

    @property
    def trials(self) -> int:
        return self.__trials

    def __bool__(self) -> bool:
        return bool(self.__breached)

    def __repr__(self) -> str:
        broke = ", ".join(self.__breached) or "nothing"
        return f"Breach(breached={broke}, survived={len(self.__survived)}, trials={self.__trials})"


@final
class Siege:
    """Lay every fault the world could throw, then take them away one at a time until the run survives.

    THE TWIN OF Isolation, on the other axis. Isolation holds the world still and shrinks the DECLARATION,
    asking which step breaks the stack. A Siege holds the declaration still and shrinks the FAULT, asking
    which failure the stack cannot take. Both drive the same oracle - a trial converges twice and the
    injected Charge reads the Proof - and both mint a record rather than a verdict a caller has to
    interpret, because a hunt that answers in prose is a hunt nobody can assert on.

    IT IS DETERMINISTIC BY CONSTRUCTION, which is the whole reason it can shrink at all. The strikes are
    NAMED (see Targeted), never rolled, so a fault set is a value. Halve it, re-run it, compare. A seeded
    Sabotage makes a random run repeatable, which is what you want while HUNTING for a failure - this is
    what you reach for once you have one and want it minimal. The two are siblings, not stages.

    THE TRIALS ARE REAL RUNS, exactly as an Isolation's are. Every candidate converges a live world with
    faults injected into it, so lay a siege against a rehearsal world and never against production. And a
    survival is evidence, never proof. A fault this hunt lifted is one this declaration absorbed on the
    trials it ran, not one it can absorb always.

    The default siege drops the connection to every step in turn, the weather a retry is written for. Pass
    your own `fault` to hunt another shape - an abort, a domain exception, a timeout."""

    def __init__(self, steps: Iterable[Step], ordering: Ordering | None = None, *,
                 charge: Charge | None = None, mode: RunMode | None = None,
                 convergence: Convergence | None = None, cancellation: Cancellation | None = None,
                 observer: Observer | None = None, retry: BaseRetry | None = None,
                 vocabulary: Vocabulary | None = None, fault: object | None = None):
        # Resolved via None so no shared default instance leaks across sieges, the Priority key precedent.
        # Churn is the default question, the failure only the idempotence oracle can ask about. The knobs
        # pass straight through to every trial, while the mode is the one each trial's chaos decorator wraps.
        self._steps = tuple(steps)
        self._charge = charge or Churn()
        self._vocabulary = vocabulary
        self._ordering = ordering or Kahn()
        # BestEffort by default. That is a requirement rather than a taste. A trial must SURVIVE the
        # fault to be judged. Under FailFast the first strike leaves as an exception, so there is no Proof
        # for the charge to read and the hunt cannot tell a fault that breaks convergence from one the run
        # merely felt. A caller who passes their own mode owns that choice.
        self.__mode = mode or Parallel(OnError.BestEffort)
        self.__convergence = convergence
        self.__cancellation = cancellation
        self.__observer = observer
        self.__retry = retry
        self.__fault = fault

    def __besieging(self) -> Generator[tuple[Step, ...], bool, tuple[tuple[Step, ...], tuple[Step, ...], int]]:
        # The uncolored hunt - yield a fault set, receive whether the charge showed, return the case as
        # (breached, survived, trials). Greedy 1-minimal shrink - try lifting each fault, keep any lift the
        # charge survives, then loop until a whole pass lifts nothing, so no single fault can leave the set.
        #
        # NO CLOSURE HERE. That is the one structural difference from Isolation's hunt. A declaration
        # candidate must stay a down-set of the Graph, since a step cannot run without what it stands on.
        # A fault set has no such obligation. Striking a step says nothing about whether its dependents are
        # struck, so any subset is a legal world and the shrink is free to take faults away one at a time.
        laid = list(self._steps)
        lifted: list[Step] = []
        trials = 1
        if not (yield tuple(laid)):
            return (), (), trials   # the declaration converged under every fault: no breach
        progress = True
        while progress:
            progress = False
            for fault in tuple(laid):
                # No "already lifted this pass" guard, so its absence is the same structural fact as the
                # missing closure. Isolation needs one because dismissing a suspect takes its whole fallout
                # with it, so a later suspect in the snapshot may already be gone. A lift here takes exactly
                # ONE fault, so nothing else can vanish underneath the walk.
                candidate = [struck for struck in laid if struck is not fault]
                trials += 1
                if (yield tuple(candidate)):
                    lifted.append(fault)
                    laid = candidate
                    progress = True
        return tuple(laid), tuple(lifted), trials

    def __verdict(self, breached: tuple[Step, ...], survived: tuple[Step, ...],
                  evidence: Proof, trials: int) -> Breach:
        # Close the case with the SHARED labeller, over the same RUN order every other reader uses, so a
        # label on a Breach and a label on a drawing are the same step - the lesson the Indictment paid for.
        labels = Step.labelled(self._ordering(Graph(self._steps, self._vocabulary)))
        return Breach(tuple(labels[step] for step in breached),
                      tuple(labels[step] for step in survived), evidence, trials)

    async def lay(self) -> Breach:
        # Drive the shared hunt with awaited trials, the Isolation driver's shape. The generator owns the
        # algorithm, this owns the awaiting. The evidence tracks the last trial that SHOWED, which is
        # always the surviving fault set's own trial, so a failed lift never overwrites it.
        hunt = self.__besieging()
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
            breached, survived, trials = case.value
            return self.__verdict(breached, survived, evidence, trials)

    async def __tried(self, struck: tuple[Step, ...]) -> Proof:
        # One candidate world - the WHOLE declaration, converged twice, with the faults laid at exactly this
        # set. The chaos decorator goes INSIDE nothing and outside the mode, which is the composition the
        # kernel supports - the strike then rides innermost through the carrier, so an injected drop is
        # retried exactly as a real one is.
        besieged = ChaosDispatcher(self.__mode, Targeted(struck, self.__fault))   # type: ignore[arg-type]
        return await Idempotence(Reconciler(self._steps, self._ordering, mode=besieged,
                                            convergence=self.__convergence, cancellation=self.__cancellation,
                                            observer=self.__observer, retry=self.__retry,
                                            vocabulary=self._vocabulary)).prove()

