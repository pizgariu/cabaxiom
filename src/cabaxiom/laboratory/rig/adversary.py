"""The Adversary axis - chaos engineering with the kernel's own shape. Extracted from dispatcher.py as an
independent concern - it decorates a real Dispatcher rather than being one of the execution strategies,
so it imports the dispatcher family and the dispatcher never imports it."""
import asyncio
import inspect
import random
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable
from typing import final, override

from ...core.declaration.cancellation import Cancellation, Cancelled
from ...core.declaration.drift import Artifacts, AsyncFlowAssessment, AsyncFlowOutcome, FlowOutcome
from ...core.declaration.errors import Pairing
from ...core.declaration.step import Step
from ...core.plan.graph import Graph
from ...core.plan.partition import Overlap
from ...core.record.ledger import Reading, Statement
from ...core.record.observer import Observer
from ...core.run.dispatcher import Dispatcher, RunMode, ThreadDispatcher, Write


class Adversary(ABC):
    """The strategy for chaos. Injected into a ChaosDispatcher to sabotage a run before each write."""

    @abstractmethod
    async def strike(self, step: Step) -> None:
        # Sabotage a unit of work before it starts. Delay it, drop it or abort it.
        ...


class BaseSabotage:
    """The shared probabilities and decision logic for the sabotage adversary.

    The source of randomness is INJECTED and defaults to a fresh `random.Random`, exactly as `Jitter` takes
    its own - so a chaos run can be SEEDED and replayed. Rolling the module-global `random` instead made a
    strike sequence depend on every unrelated draw the process happened to make in between, so the run that
    broke a domain could not be re-run, so a chaos finding was a story rather than a reproduction."""

    def __init__(self, drop_rate: float = 0.0, abort_rate: float = 0.0, max_delay: float = 0.0,
                 *, rng: random.Random | None = None):
        self._drop_rate = drop_rate
        self._abort_rate = abort_rate
        self._max_delay = max_delay
        self._rng = rng or random.Random()

    def _decide(self, _step: Step) -> float:
        # Returns the delay to wait or raises the fault immediately. One roll decides all three so the
        # rates partition a single interval rather than compounding.
        roll = self._rng.random()
        if roll < self._abort_rate:
            raise Cancelled("The injected adversary aborted the step")
        if roll < self._abort_rate + self._drop_rate:
            raise ConnectionError("The injected adversary dropped the connection")
        if self._max_delay > 0:
            return self._rng.uniform(0, self._max_delay)
        return 0.0


@final
class Sabotage(BaseSabotage, Adversary):
    """An adversary that rolls the dice for each step. A drop is a ConnectionError the Ledger records, an
    abort is a Cancelled that cuts the run, a delay just slows the step so a Deadline can catch it."""

    @override
    async def strike(self, step: Step) -> None:
        delay = self._decide(step)
        if delay > 0:
            await asyncio.sleep(delay)


@final
class Targeted(Adversary):
    """An adversary that strikes exactly the steps it was handed, nothing else.

    The DETERMINISTIC sibling of Sabotage and the one a hunt can shrink. Sabotage rolls dice, so two runs
    of one declaration strike different steps and no subset of its behaviour can be compared with another -
    seeding makes a run repeatable, it does not make a fault set enumerable. This one names its targets, so
    a fault set is a VALUE: it can be halved, re-run and compared, which is the whole ground a Siege stands
    on. Hand it steps, not labels, because identity is the kernel's addressing everywhere else and two
    instances of one kind must be strikeable apart."""

    def __init__(self, marked: Iterable[Step], fault: Callable[[Step], BaseException] | None = None):
        # The fault is injected and defaults to a dropped connection, the weather a retry is written for.
        # Pass your own to hunt a different shape - an abort, a domain error, a timeout.
        self.__marked = frozenset(marked)
        self.__fault = fault or (lambda step: ConnectionError(f"The siege dropped the connection to {Step.named(step)}"))

    @property
    def marked(self) -> frozenset[Step]:
        return self.__marked

    @override
    async def strike(self, step: Step) -> None:
        if step in self.__marked:
            raise self.__fault(step)


@final
class _ChaosWorker(Dispatcher):
    """The worker behind ChaosDispatcher. A worker decorator that sabotages the run to prove the Ledger and
    the backoff work. It intercepts execute() to poison the write attempts and delegates probe() to the
    worker it wraps, assuming its exact overlap semantics.

    THE STRIKE LANDS INSIDE THE RUN'S OWN LAYERS, through relay(). Getting that wrong is the reason
    this class is named in the dispatcher family's list of one repeated bug. A decorator that rebuilds the
    write callable around the whole stack puts its own fault OUTSIDE the retry, so the backoff this class
    exists to prove never sees the strike at all - Retry(4) against a drop at rate one spent one attempt
    and announced no retry, while the identical ConnectionError raised by the step itself spent four and
    announced three. relay() hands the strike to the CARRIER instead, which lays it innermost, so an
    injected drop is retried exactly as a real one is and a strike costs the permit slot it would really
    have held.

    IT ONLY OWNS THE ORDER WHEN IT IS THE OUTERMOST DECORATOR. That is a real limit rather than a
    quiet one. relay() answers a plain callable, so a chaos decorator composed INSIDE another one is
    handed a stack that is already flat and has no carrier to lay a layer through - its strike then sits
    outside the retry again. ThreadDispatcher(ChaosDispatcher(...)) is exactly that shape. Closing
    that would mean a carrier that survives relay, which is a seam on Write rather than a change here."""

    # Walk overlaps nothing, which makes it safe to pass ANY partition the underlying dispatcher verified.
    overlaps = Overlap.NEITHER

    def __init__(self, underlying: Dispatcher, adversary: Adversary):
        super().__init__(underlying._on_error)
        self._underlying = underlying
        self._adversary = adversary

    @override
    def walks(self) -> Overlap:
        # The strike poisons the write, it does not change WHERE the pair overlaps - the worker underneath
        # still fans exactly as it did, so the guard must see that one's answer and not this decorator's.
        return self._underlying.walks()

    @override
    async def execute(
        self,
        groups: tuple[tuple[Step, ...], ...],
        graph: Graph,
        do: Callable[[Step, Artifacts], AsyncFlowOutcome],
        cancellation: Cancellation,
        observer: Observer,
    ) -> Statement:

        def relocate(hook: Callable[[Step, Artifacts], AsyncFlowOutcome]) -> Callable[[Step, Artifacts], AsyncFlowOutcome]:
            async def struck(run_step: Step, run_inputs: Artifacts) -> FlowOutcome:
                # The strike, then the hook it sabotages, awaited here so both colours of write flatten
                # for Dispatcher._attempt exactly as they did before.
                await self._adversary.strike(run_step)
                outcome = hook(run_step, run_inputs)
                return await outcome if inspect.isawaitable(outcome) else outcome

            return struck

        # relay() when the carrier is here, so the strike goes INNERMOST and the run's retry and permit are
        # laid back over it - the order the carrier owns and no decorator should be reconstructing. Without
        # one there is nothing to lay, so a flat wrap is all that is available, which is what a chaos
        # decorator composed inside another one gets. The same two-shape line the thread bridge writes.
        poisoned = do.relay(relocate) if isinstance(do, Write) else relocate(do)
        return await self._underlying.execute(groups, graph, poisoned, cancellation, observer)

    @override
    async def probe(self, groups: tuple[tuple[Step, ...], ...], graph: Graph, read: Callable[[Step, Artifacts], AsyncFlowAssessment], cancellation: Cancellation, observer: Observer) -> Reading:
        return await self._underlying.probe(groups, graph, read, cancellation, observer)


@final
class ChaosDispatcher(RunMode):
    """Chaos engineering as a run mode. Wraps another RunMode and poisons its write attempts through the
    injected Adversary while keeping the wrapped mode's shape. Compose the chaos INSIDE a thread bridge,
    ThreadDispatcher(ChaosDispatcher(inner, adversary)), never the other way round - the strike rebuilds
    the write callable, so a bridge outside it would thread a rebuilt closure instead of the step's hook."""

    def __init__(self, underlying: RunMode, adversary: Adversary):
        # The one composition the chaos axis refuses, said at the user-facing seam where the mistake is
        # made. A thread bridge OUTSIDE the strike would thread the rebuilt closure instead of the step's
        # own hook, so a blocking write would run back on the event loop with nothing raising.
        if isinstance(underlying, ThreadDispatcher):
            raise Pairing(
                "ChaosDispatcher cannot wrap a ThreadDispatcher - the strike rebuilds the write callable, "
                "so the bridge inside would thread a rebuilt closure instead of the step's own hook and a "
                "blocking write would run back on the event loop with nothing raising. Compose the chaos "
                "INSIDE the bridge, ThreadDispatcher(ChaosDispatcher(inner, adversary)), which is the "
                "order the kernel supports and pins."
            )
        super().__init__(underlying._arranger, _ChaosWorker(underlying.dispatcher, adversary))
