"""Dispatcher strategies - HOW a Partition is run, async native. The event-loop Parallel and Supervised
(waves), the ThreadDispatcher bridge for blocking steps and the RemoteDispatcher wire. The adversary
decorator lives in adversary.py, which imports this module and is never imported by it."""
import asyncio
import inspect
import pickle
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable, Coroutine
from contextlib import AsyncExitStack
from types import MappingProxyType
from typing import Any, ClassVar, NamedTuple, cast, final, override

from ..declaration.cancellation import Cancellation, Cancelled, Deferred, Fault, Skew
from ..declaration.drift import (
    Artifacts,
    Assessment,
    AsyncFlowAssessment,
    AsyncFlowOutcome,
    Changes,
    FlowAssessment,
    FlowOutcome,
)
from ..declaration.errors import Misconfigured, Pairing
from ..declaration.lease import Authority, Permit
from ..declaration.step import Step
from ..plan.arranger import Arranger, Walk, Waves
from ..plan.graph import Graph
from ..plan.ordering import Ordering
from ..plan.partition import Overlap, Partition
from ..record.ledger import Ledger, OnError, Reading, Statement
from ..record.observer import Observer
from .retry import BaseRetry


class BaseDispatcher(ABC):
    """A WORKER - the failure policy and the Ledger it records under. Nothing about the shape.

    ONE responsibility. A worker WALKS a Partition it is handed. It does not choose or verify the shape.
    Which Arranger builds the Partition and whether this worker can safely walk what it built is the
    RunMode's job (see RunMode.resolve). This split is the whole point of the 0.6.0 executor rework. A
    decorator now wraps a worker without ever proxying an arranger, so the shape leaks nowhere.

    A worker holds only its OnError, stored where every execute() reads it (protected _on_error). It also
    opens the run's Ledger. Each concrete worker declares WHERE it overlaps in flight, refused at
    construction and paired against the shape by the RunMode."""

    # WHERE this worker runs things at once. Declared per LEAF rather than per family, because it is the
    # concrete worker's own walking behaviour. Annotated, never defaulted. A permissive default is exactly
    # the silence this exists to end. The worker that forgets to say is the one whose pairing nobody
    # checked. Refused at construction and settled against the shape by RunMode.resolve.
    overlaps: ClassVar[Overlap]

    def __init__(self, on_error: OnError = OnError.FailFast):
        if not hasattr(type(self), "overlaps"):
            raise TypeError(
                f"{self.__class__.__name__} declares no overlaps. A worker says where it runs things at the "
                f"same time, because that is what decides which run shapes are safe for it to walk. Set "
                f"overlaps = Overlap.WITHIN for a fanner over one group, Overlap.ACROSS for a fanner over "
                f"the groups or Overlap.NEITHER for a serial walk."
            )
        self._on_error = on_error    # protected, because every subclass's execute() reads the one stored policy

    def walks(self) -> Overlap:
        # WHERE THE PAIR overlaps, which is what the guard must ask. A leaf answers with its own declaration.
        # A pure decorator fans nothing ITSELF and truthfully declares NEITHER. The pair it forms walks
        # with the worker underneath it, so a decorator overrides this and delegates. Reading the CLASS
        # attribute instead let every decorated mode past the guard entirely. A wave fanner wrapped in a
        # thread bridge or the chaos axis walked a chain shape and reported the run clean.
        return type(self).overlaps

    def _ledger(self, groups: tuple[tuple[Step, ...], ...], observer: Observer, graph: Graph) -> Ledger:
        # Open the run's Ledger over the groups about to be walked. It carries this worker's stored policy,
        # the run's observer (whose stepped() the Ledger fires per settled unit) and the run's DERIVATION.
        # The whole failure semantics lives on the Ledger, so every execute() inherits it.
        return Ledger(groups, self._on_error, observer, graph)


class RunMode:
    """Pairs a PLAN with a WORKER and vouches the two fit - the composition seam the reconciler holds.

    Three responsibilities, three objects. The Arranger PLANS (turns an Ordering into a verified Partition),
    the worker (a Dispatcher) RUNS it and the RunMode PAIRS them. The RunMode also proves the worker can
    actually walk the shape before the run touches the world. resolve() is the one call the reconciler makes.

    This is where the pairing guard lives now, on the REAL partition the arranger returned, so a decorator
    can wrap a pure worker without carrying a shape. The arranger rides here, not on the worker. A caller
    picks a ready pairing (Parallel, Supervised) and never assembles the two halves by hand, so a mismatch
    is impossible to express rather than merely caught."""

    def __init__(self, arranger: Arranger, dispatcher: "Dispatcher"):
        self._arranger = arranger        # PLANS the partition
        self._dispatcher = dispatcher    # RUNS it (a worker with execute/probe)

    @final
    def resolve(self, ordering: Ordering, graph: Graph) -> Partition:
        # Build the shape, then verify THIS worker can walk it - on the partition actually returned, never a
        # promise. @final so a subclass cannot answer with a shape its own guard did not clear.
        partition = self._arranger.arrange(ordering, graph)
        self.__walkable(partition)
        return partition

    def __walkable(self, partition: Partition) -> None:
        # THE PAIRING GUARD. A shape states its ordering rule, from which it derives exactly WHERE it
        # overlaps in flight. Ask the shape for its overlap and compare it to the worker's. A serial worker
        # overlaps nothing and can walk any shape safely.
        worker = self._dispatcher
        # Annotated and named for the thing rather than for the method that answers it. `walks` here read
        # as the bound method one line above it, which is a question a reader should not have to resolve.
        in_flight: Overlap = worker.walks()   # the PAIR's overlap, so a decorator answers for the worker under it
        # NEITHER overlaps nothing and EDGES governs its own, so neither leans on the seating. Every shape
        # is safe for them, so the question the guard exists to ask never arises.
        if in_flight in (Overlap.NEITHER, Overlap.EDGES) or partition.overlap is in_flight:
            return
        raise Pairing(
            f"{worker.__class__.__name__} runs {in_flight.value} at the same time. The shape this "
            f"RunMode composes builds a {partition.__class__.__name__}, whose rule allows a dependency "
            f"{partition.placement.described} (it overlaps {partition.overlap.value}). Under that pairing a "
            f"step could run beside its own prerequisite and the run still reports clean. Compose Waves for "
            f"a worker that overlaps inside one group, Chains for one across them and Walk only for one "
            f"that overlaps nothing."
        )

    @property
    def dispatcher(self) -> "Dispatcher":
        # The worker the reconciler walks the resolved partition on. The arranger stays private - it has
        # done its job by resolve() time and nobody downstream needs it.
        return self._dispatcher


# One settled step's outcome inside a wave. It carries the step, what its write returned (Changes or
# None), the artifacts it produced and the exception it raised - caught into the tuple, never propagated
# out of the coroutine - or None if it ran clean. PUBLIC, because run_wave is a seam on an open base.
type Settled = tuple[Step, Changes, Artifacts, Fault | None]


@final
class Write:
    """The write phase's callable, with its verb spoken.

    execute() is handed ONE callable for the whole run. Which write it performs - apply on a
    converge, prune on a teardown - used to be baked invisibly inside it. That was fine while every
    dispatcher ran the callable in this process. A TRANSPORT cannot ship a closure, so a remote
    dispatcher must say the verb in its envelope and lay the run's layers over its own wire call
    instead of the local hook. This carrier is that and nothing more. It IS the retry-wrapped
    callable, so every existing dispatcher keeps calling exactly what it always called. It SAYS the
    verb. And relay() rebuilds the whole stack around a RELOCATED hook, so attempts are spent on wire
    crossings and capacity is asked per crossing while retryable()/retried still see the real step.
    Built by the reconciler, one per write phase and consumed by any dispatcher that needs more than
    a call.

    A dispatcher that does not perform the write HERE but MOVES it - ThreadDispatcher onto a worker
    thread, RemoteDispatcher onto another process - wants relay(), because it needs the layers this
    carrier holds rebuilt around the moved hook instead of laid over the layers themselves. Which layer
    a decorator got hold of by mistake is the only thing every bug in this file's history had in common.
    A decorator that lays only PART of the stack is that same bug wearing a quieter layer. rewire()
    lays the retry and not the permit, which is how the wire came to declare a capacity that nobody on
    either side of it enforced."""

    __slots__ = ("__retry", "__observer", "__verb", "__wrapped", "__raw", "__hook", "__authority")

    def __init__(self, retry: BaseRetry, observer: Observer, raw: Callable[[Step, Artifacts], AsyncFlowOutcome], verb: str,
                 authority: Authority | None = None):
        self.__retry = retry
        self.__observer = observer
        self.__verb = verb
        self.__authority = authority
        self.__hook = raw
        self.__raw = self.__permitted(raw)
        self.__wrapped = retry(self.__raw, observer=observer)

    def __permitted(self, raw: Callable[[Step, Artifacts], AsyncFlowOutcome]) -> Callable[[Step, Artifacts], AsyncFlowOutcome]:
        # The permit sits INSIDE the retry rather than around it, so a capacity is re-asked per attempt and a
        # pool that frees between two tries lets the second one through. The reason this comment used to give
        # was FALSE. The suite had been proving it false the whole time. It said one denial around the
        # outside would spend a step's whole budget. Nothing reachable does that, because Deferred is a
        # BaseException and ends the write on whichever attempt it lands on wherever the permit sits.
        # test_lease.py asks a permanently empty pool under Retry(5) and counts ONE ask. So the position buys
        # the re-ask and nothing else. A false justification is how the next reader makes the wrong call.
        # A run with no authority gets the raw call back, so the axis costs nothing when nobody uses it -
        # the Retry(1) precedent, one branch at construction instead of one per write.
        if self.__authority is None:
            return raw
        authority = self.__authority

        async def permitted(step: Step, inputs: Artifacts) -> FlowOutcome:
            granted: list[Permit] = []
            holder = f"{id(step):x}/{self.__verb}"
            try:
                for permit in step.leases:
                    if not authority.acquire(permit, holder):
                        raise Deferred(
                            f"{Step.named(step)} needs a permit for {permit.name!r} and the pool of "
                            f"{permit.capacity} had none free, so the {self.__verb} did not run. Nothing "
                            f"broke and nothing changed - the next pass asks again."
                        )
                    granted.append(permit)
                outcome = raw(step, inputs)
                return await outcome if inspect.isawaitable(outcome) else outcome
            finally:
                # Released in reverse and even on the abort that skipped the write, because a slot
                # a dead run still holds is a slot nobody can ever reclaim.
                for permit in reversed(granted):
                    authority.release(permit, holder)

        return permitted

    @property
    def raw(self) -> Callable[[Step, Artifacts], AsyncFlowOutcome]:
        # The call WITHOUT the retry - the permit layer and the step's own hook, nothing else. For a
        # decorator that must spend the attempts around something of its own, which is rewire()'s other
        # half. Calling __call__ instead would spend them around the wrong thing.
        #
        # ITS CALLING CONVENTION IS NOT THE HOOK'S. With an authority injected this is a coroutine
        # FUNCTION whatever colour the step's own apply() wears, because the permit layer has to await the
        # outcome before it may release the slot. A decorator that RELOCATES the work - onto a worker
        # thread, over a wire - must therefore not hand this one to the relocation. Otherwise the relocation only
        # BUILDS a coroutine and the hook runs back where it started. Use relay(), which relocates the
        # hook and re-lays the permit and the retry over it in the right order.
        return self.__raw

    @property
    def verb(self) -> str:
        # The write this run performs, for a transport's envelope. That is "apply" on a converge and
        # "prune" on a teardown. The read side never needs a carrier - a probe's verb is always assess.
        return self.__verb

    def __call__(self, step: Step, inputs: Artifacts) -> AsyncFlowOutcome:
        return self.__wrapped(step, inputs)

    def rewire(self, raw: Callable[[Step, Artifacts], AsyncFlowOutcome]) -> Callable[[Step, Artifacts], AsyncFlowOutcome]:
        # The run's retry and observer laid over a different carrier. NOTHING ELSE. A decorator
        # gets back the same attempt budget the local hook would have had, so a transient failure in
        # whatever it substituted spends an attempt exactly as a transient write does.
        #
        # IT LAYS ONE LAYER, WHICH IS WHY THE WIRE STOPPED USING IT. A dispatcher that substitutes the
        # call is also substituting everything the stack held below the retry and the permit layer was
        # one of them - so a step declaring `leases` crossed to a worker with its pool never asked and
        # a capacity of three was enforced by nobody while every channel read clean. Reach for relay()
        # unless the substituted call must genuinely escape the run's other layers and say why if it
        # must.
        return self.__retry(raw, observer=self.__observer)

    def relay(self, relocate: Callable[[Callable[[Step, Artifacts], AsyncFlowOutcome]], Callable[[Step, Artifacts], AsyncFlowOutcome]]) -> Callable[[Step, Artifacts], AsyncFlowOutcome]:
        # The whole write stack, rebuilt around a RELOCATED hook. A decorator hands in how it moves a call
        # somewhere else and gets back the same stack __call__ has - the retry outside, the permit inside
        # it, the relocated hook innermost - so nothing about attempt budgets or capacity changes because
        # the work moved.
        #
        # It takes the relocation rather than handing out the hook. That is the point. Handing the hook
        # out invites the caller to rebuild the stack themselves. A caller who rebuilds it from `raw`
        # re-relocates the permit layer instead of the hook. That silently runs the work back on the thread
        # it was being moved off. ThreadDispatcher shipped exactly that bug for the authority axis.
        return self.__retry(self.__permitted(relocate(self.__hook)), observer=self.__observer)


class Dispatcher(BaseDispatcher, ABC):
    """The one dispatcher contract, async native. Its execute() is a coroutine awaited on the caller's loop.

    There is no sync twin any more. The deletion is the point - a mirrored sync family meant every fix
    landed twice or drifted. A step whose write blocks rides ThreadDispatcher, which bridges it onto the
    loop, so a blocking DOMAIN is still served while the sync ENGINE is gone. do hands back a FlowOutcome:
    a coroutine step's is awaited, a plain one is taken as-is, so `async def apply()` and a plain apply()
    are both legal typed overrides."""


    @abstractmethod
    async def execute(self, groups: tuple[tuple[Step, ...], ...], graph: Graph, do: Callable[[Step, Artifacts], AsyncFlowOutcome], cancellation: Cancellation, observer: Observer) -> Statement:
        ...

    @abstractmethod
    async def probe(self, groups: tuple[tuple[Step, ...], ...], graph: Graph, read: Callable[[Step, Artifacts], AsyncFlowAssessment], cancellation: Cancellation, observer: Observer) -> Reading:
        ...

    @staticmethod
    def _attempt(do: Callable[[Step, Artifacts], AsyncFlowOutcome]) -> Callable[[tuple[Step, Artifacts]], Coroutine[Any, Any, Settled]]:
        """The ONE write attempt, lifted off the wave base so a dispatcher that walks its own loop inherits
        it instead of copying it.

        Three invariants ride in these lines and every one is quiet. It catches even under FailFast,
        because a wave is a barrier and the first failure in resolved order may only be re-raised once its
        wave-mates have settled - catching here is what keeps a failure from cancelling them mid-flight. It
        awaits an awaitable outcome and takes a plain one as-is, since a sync step is a legal typed override
        on the async contract. And it hands the step back beside its outcome and its produce, because a
        gathered wave settles out of order and the Ledger records by step. The narrowing around the
        awaitable is where a hand copy goes wrong, so the copy is retired and this is the only one."""
        async def attempt(payload: tuple[Step, Artifacts]) -> Settled:
            unit, inputs = payload
            try:
                res = do(unit, inputs)
                if inspect.isawaitable(res):
                    out_produced, out_artifacts = await res
                else:
                    out_produced, out_artifacts = res
                return unit, out_produced, out_artifacts, None
            except (Deferred, Skew, Exception) as failure:
                # Skew and Deferred are named because both are BaseExceptions and this clause would
                # otherwise miss them - the same deliberate pairing work() writes for Cancelled. Neither may
                # be RETRIED and both must still be RECORDED, which is the whole reason they are not
                # Exceptions and the whole reason they are caught here. A protocol skew must not be RETRIED
                # (which is why it is not an Exception) but must still be RECORDED (which is why it is
                # caught here). The retry loop sits inside this try. Escaping that loop and reaching the
                # Ledger are two different questions. The answer differs.
                return unit, None, {}, failure
        return attempt


class WavesDispatcher(Dispatcher, ABC):
    """Shared machinery for the waves-shaped dispatchers. They all build the SAME attempt() closure and
    classify the SAME settled outcomes under the SAME OnError policy through one Ledger. They differ in
    exactly ONE thing. How a single wave is awaited, which is the abstract seam run_wave. Everything around
    it lives here once."""

    overlaps = Overlap.WITHIN

    @override
    async def probe(self, groups: tuple[tuple[Step, ...], ...], graph: Graph, read: Callable[[Step, Artifacts], AsyncFlowAssessment], cancellation: Cancellation, observer: Observer) -> Reading:
        # Fan the read across each wave. A group's coroutine reads overlap on the caller's loop and plain
        # reads run inline. probe_wave preserves input order, so the deviations flatten in resolved order.
        # The wave is a barrier even for a broken read. Every read settles first (exceptions captured), THEN
        # every failure in the wave raises together as one native ExceptionGroup. One diagnostic pass
        # surfaces every broken read at once and no sibling is left running detached on the loop. Reads
        # stay single-try under no OnError policy, because the probe is the run's proof. Single-try is not
        # the same thing as uncancellable, though. The Cancellation is checked between waves exactly as the
        # write side checks it. probe_wave is where Supervised watches a wave of reads in flight, so a
        # Deadline bounds the proof phase as firmly as it bounds the work. Only the deviation channel of
        # each Assessment feeds the residual here. The plan, advice and footprint ride the same record for
        # a caller that wants them, while converge() re-probes for deviation alone.
        artifacts_store: dict[Step, Artifacts] = {}

        async def attempt(payload: tuple[Step, Artifacts]) -> tuple[Step, Assessment, Artifacts]:
            unit, inputs = payload
            res = read(unit, inputs)
            if inspect.isawaitable(res):
                out_assessment, out_arts = await res
            else:
                out_assessment, out_arts = res
            return unit, out_assessment, out_arts

        # Every settled read, kept whole for Reading.gathered to fold. All four channels ride along - the fan
        # used to throw three quarters of what every step computed away, which is why no gate could ask
        # about scale. The store is ALSO filled per wave below, because the next wave mounts from it.
        answered: list[tuple[Step, Assessment, Artifacts]] = []
        for group in groups:
            if cancellation.cancelled():
                raise Cancelled.by(cancellation)
            payloads: list[tuple[Step, Artifacts]] = []
            for step in group:
                # The read fan mounts its payloads through the Ledger's ONE merge, so the probe and the
                # write side cannot disagree about what a step is handed - nor about a collision being
                # refused instead of silently resolved.
                mounted = Ledger.mounted(step, graph.dependencies(step), artifacts_store)
                observer.dispatching(step, MappingProxyType(mounted))
                payloads.append((step, mounted))

            settled: list[tuple[Step, Assessment, Artifacts] | BaseException] = await self.probe_wave(
                [attempt(p) for p in payloads], cancellation)
            broken: list[BaseException] = []
            for result in settled:
                if isinstance(result, (Cancelled, asyncio.CancelledError)):
                    # An abort is never part of the diagnosis. It cuts through instead of folding into the
                    # group, so `except Cancelled` still sees it and a group of ordinary broken reads stays
                    # a plain ExceptionGroup.
                    raise result
                if isinstance(result, BaseException):
                    broken.append(result)
                else:
                    artifacts_store[result[0]] = result[2]
                    answered.append(result)
            if broken:
                raise BaseExceptionGroup(f"{len(broken)} of the wave's {len(settled)} reads failed", broken)
        # The reading closes over BOTH what the probe found and what each assess produced - the store used
        # to die right here as a local. All-or-raise above is what makes it total.
        return Reading.gathered(answered)

    @final
    @override
    async def execute(self, groups: tuple[tuple[Step, ...], ...], graph: Graph, do: Callable[[Step, Artifacts], AsyncFlowOutcome], cancellation: Cancellation, observer: Observer) -> Statement:
        # THE WAVE GUARD, sealed. The barrier, the between-wave Cancellation check and the Ledger recording
        # are the wave contract itself, so a subclass extends run_wave (how ONE wave is awaited), never this.
        # attempt() ALWAYS catches, even under FailFast, so a coroutine blowing up comes back as a clean
        # tuple rather than cancelling its wave-mates mid-flight. The tuple carries the step's own return
        # and produce. Each wave is a barrier and the between-wave Cancellation check holds every declared
        # edge, so under FailFast the first failure in resolved order is re-raised only after the wave
        # finishes. Each step is handed the inputs its prerequisites produced, assembled by the Ledger.
        attempt = self._attempt(do)
        ledger = self._ledger(groups, observer, graph)
        for level in groups:
            if cancellation.cancelled():
                raise Cancelled.by(cancellation)
            admitted = ledger.admit(level)
            payloads = [(step, ledger.assemble(step)) for step in admitted]
            for unit, mounted in payloads:
                # The START moment, fired as the wave fans. The step and a read-only view of the very
                # payload it is about to be handed, so a trace can pair this with stepped for a duration
                # without ever being able to rewrite what the run is about to read.
                observer.dispatching(unit, MappingProxyType(mounted))
            for step_res, prod_res, arts_res, exc_res in await self.run_wave(payloads, attempt, cancellation):
                ledger.record(step_res, prod_res, arts_res, exc_res)
        return ledger.outcome()

    @abstractmethod
    async def run_wave(self, level_payloads: list[tuple[Step, Artifacts]], attempt: Callable[[tuple[Step, Artifacts]], Coroutine[Any, Any, Settled]], cancellation: Cancellation) -> list[Settled]:
        ...

    async def probe_wave(self, attempts: list[Coroutine[Any, Any, "tuple[Step, Assessment, Artifacts]"]], cancellation: Cancellation) -> list["tuple[Step, Assessment, Artifacts] | BaseException"]:
        # How ONE wave of reads is awaited, the read twin of run_wave. Not abstract, because the honest
        # default exists - gather every read, capture what broke, keep input order - and only a dispatcher
        # that must watch a wave IN FLIGHT (Supervised) overrides it. run_wave has no such default, since
        # how writes fan is the whole difference between the shipped wave dispatchers.
        return await asyncio.gather(*attempts, return_exceptions=True)

    @staticmethod
    def _collect(level_payloads: list[tuple[Step, Artifacts]], tasks: "list[asyncio.Task[Settled]]") -> list[Settled]:
        # The shared collection at a wave's end. The settled tuples in resolved order, with a task that
        # ended CANCELLED converted into a failure. Both run_wave paths raise before any collection, so a
        # cancelled task HERE is unambiguously a step defect. Either the step cancelled itself or a library
        # leaked CancelledError out of its write. It becomes a value for the ONE Ledger rule to classify
        # rather than vaporising the wave-mates' settled outcomes from the record.
        outcomes: list[Settled] = []
        for (step_unit, _), task in zip(level_payloads, tasks):
            if task.cancelled():
                outcomes.append((step_unit, None, {}, RuntimeError(
                    f"{Step.named(step_unit)} write ended cancelled although the run was not - the step or a "
                    f"library inside it raised or leaked CancelledError on its own"
                )))
            else:
                outcomes.append(task.result())
        return outcomes


@final
class _Gather(WavesDispatcher):
    """The event-loop wave worker behind Parallel. Runs each dependency wave on the asyncio event loop, awaiting a wave's
    coroutines concurrently and barring between waves so every declared edge holds.

    Unbounded by design. A wave's coroutines all run at once under one TaskGroup, since coroutines are
    cheap and a wave is one group of mutually-independent steps. A domain with enormous waves that must
    throttle its own I/O should bound it inside apply() (its own asyncio.Semaphore). The Cancellation is
    checked only BETWEEN waves - reach for Supervised when an apply() can hang and a Deadline must stay
    enforceable."""

    @override
    async def run_wave(self, level_payloads: list[tuple[Step, Artifacts]], attempt: Callable[[tuple[Step, Artifacts]], Coroutine[Any, Any, Settled]], cancellation: Cancellation) -> list[Settled]:
        # The TaskGroup awaits the whole wave at once, the ordered tasks list keeps collection in resolved
        # order. attempt() catches Exception, so the only escapes left are BaseExceptions - which includes
        # a step RAISING the kernel's Cancelled. On any abort the group cancels the rest of the wave and
        # awaits EVERYTHING before it continues out, so no attempt task outlives the run it belonged to.
        try:
            async with asyncio.TaskGroup() as group:
                tasks = [group.create_task(attempt(payload)) for payload in level_payloads]
        except BaseExceptionGroup as settled_group:
            # A step raising the kernel's Cancelled is cooperating with an abort. `except Cancelled` is
            # the caller's contract. So an abort continues out as itself. A group wrapper would break it.
            # Anything besides aborts propagates as the group it is.
            aborts, rest = settled_group.split(Cancelled)
            if aborts is not None and rest is None:
                raise next(iter(aborts.exceptions)) from None
            raise
        return self._collect(level_payloads, tasks)


@final
class _Watch(WavesDispatcher):
    """The supervising wave worker behind Supervised. Same waves shape as _Gather. It SUPERVISES a wave's coroutines while they run instead of just
    awaiting them. _Gather checks the Cancellation only between waves, so a single apply() or assess()
    that hangs blocks the whole fan forever and a Deadline can never fire. Supervised polls the
    Cancellation while the wave is in flight - writes and reads through the one supervision loop. When it
    fires, Supervised cancels the outstanding coroutines and raises Cancelled. That is what lets a Deadline
    actually BOUND a hung wave, the proof phase included.

    The cost is the poll. The Cancellation is a cooperative bool, so a hung wave is re-checked every `poll`
    seconds. The abort is bounded end to end - the drain waits at most `grace` seconds, so a step that
    mishandles cancellation cannot re-hang the wave. A straggler that ignores its cancel through the whole
    grace is abandoned, the one deliberate trade. A detached pathological task beats an abort that never
    returns."""

    def __init__(self, on_error: OnError = OnError.FailFast, *, poll: float = 0.05, grace: float = 1.0):
        # poll must be strictly positive. A zero or negative slice would busy-spin the supervise loop.
        # grace must be too. Zero or negative would abandon every cancelled task unawaited, the orphaning
        # the drain exists to prevent.
        if poll <= 0:
            raise Misconfigured(f"Supervised poll must be > 0 seconds, got {poll}")
        if grace <= 0:
            raise Misconfigured(f"Supervised grace must be > 0 seconds, got {grace}")
        super().__init__(on_error)
        self.__poll = poll     # how often (seconds) a hung wave re-checks the Cancellation
        self.__grace = grace   # how long (seconds) an abort waits for its cancelled tasks to settle

    @override
    async def run_wave(self, level_payloads: list[tuple[Step, Artifacts]], attempt: Callable[[tuple[Step, Artifacts]], Coroutine[Any, Any, Settled]], cancellation: Cancellation) -> list[Settled]:
        # Launch each coroutine as a task and hand the set to the one supervision loop. The ordered tasks
        # list keeps collection in resolved order.
        tasks = [asyncio.create_task(attempt(payload)) for payload in level_payloads]
        await self.__supervise(set(tasks), cancellation)
        return self._collect(level_payloads, tasks)

    @override
    async def probe_wave(self, attempts: list[Coroutine[Any, Any, "tuple[Step, Assessment, Artifacts]"]], cancellation: Cancellation) -> list["tuple[Step, Assessment, Artifacts] | BaseException"]:
        # The read twin of run_wave, through the SAME supervision loop - which is the whole point of this
        # dispatcher having one. Before this override a hung assess() blocked the probe's fan forever and a
        # Deadline could bound the work but never the proof, so converge under Supervised hung in exactly
        # the phase nobody could interrupt. The reads keep their own error contract - what broke is captured
        # per task and raised together by the caller, never folded into a Settled the Ledger would swallow.
        tasks = [asyncio.create_task(attempt) for attempt in attempts]
        await self.__supervise(set(tasks), cancellation)
        return [failure if (failure := task.exception()) is not None else task.result() for task in tasks]

    async def __supervise(self, pending: "set[asyncio.Task[Any]]", cancellation: Cancellation) -> None:
        # The supervision loop itself, blind to what the tasks carry. Wait in `poll`-second slices so a hung
        # task cannot outlast the Cancellation. asyncio.wait returns as soon as one settles OR the slice
        # elapses. Either way the Cancellation is re-checked. On abort, drain then raise.
        try:
            while pending:
                _done, pending = await asyncio.wait(pending, timeout=self.__poll, return_when=asyncio.FIRST_COMPLETED)
                if pending and cancellation.cancelled():
                    await self.__drain(pending)
                    raise Cancelled.by(cancellation)
        except asyncio.CancelledError:
            await self.__drain(pending)
            raise

    async def __drain(self, pending: "set[asyncio.Task[Any]]") -> None:
        # Cancel what is still pending and await it up to `grace`, so an aborted wave leaves nothing running
        # detached. A straggler that ignores its cancel through the whole grace is abandoned.
        for task in pending:
            task.cancel()
        await asyncio.wait(pending, timeout=self.__grace)


@final
class _Walker(Dispatcher):
    """The serial worker behind Serial. One step at a time, in resolved order, on the caller's loop.

    It fans NOTHING, which is what makes it the only worker safe against every shape. It is also the whole
    of the "trivial custom dispatcher" the Walk arranger's docstring points at - shipped, because a caller
    who wants a deterministic single-file run had to write this by hand while the shape it walks was
    already public.

    It asks blocked() PER STEP where the wave workers ask admit() per wave. That is the correct gate for
    a serial walk rather than a preference. A Walk shape's rule is "earlier in the walk", so a dependency
    may legally share a group with its dependent. A per-group admission would ask about a prerequisite
    whose own outcome is not recorded yet. Everything else - the Ledger, the one raise-or-
    collect rule, the Cancellation between units, the artifact merge - is inherited rather than re-derived,
    so a serial run carries the identical failure semantics a fanned one does."""

    overlaps = Overlap.NEITHER

    @override
    async def execute(self, groups: tuple[tuple[Step, ...], ...], graph: Graph, do: Callable[[Step, Artifacts], AsyncFlowOutcome], cancellation: Cancellation, observer: Observer) -> Statement:
        attempt = self._attempt(do)
        ledger = self._ledger(groups, observer, graph)
        for leg in groups:
            for step in leg:
                if cancellation.cancelled():
                    raise Cancelled.by(cancellation)
                if ledger.blocked(step):
                    continue
                mounted = ledger.assemble(step)
                observer.dispatching(step, MappingProxyType(mounted))
                ledger.record(*await attempt((step, mounted)))
        return ledger.outcome()

    @override
    async def probe(self, groups: tuple[tuple[Step, ...], ...], graph: Graph, read: Callable[[Step, Artifacts], AsyncFlowAssessment], cancellation: Cancellation, observer: Observer) -> Reading:
        # The read twin, serial for the same reason. The payloads are mounted through the Ledger's ONE
        # merge, so the read side and the write side cannot disagree about what a step is handed. The
        # deviations flatten in resolved order because that is the order they are taken in. A broken read
        # propagates as itself here rather than as a group, since nothing else in the leg is in flight to
        # settle first - the wave fan's ExceptionGroup exists only because a wave is a barrier.
        produced: dict[Step, Artifacts] = {}
        answered: list[tuple[Step, Assessment, Artifacts]] = []
        for leg in groups:
            for step in leg:
                if cancellation.cancelled():
                    raise Cancelled.by(cancellation)
                mounted = Ledger.mounted(step, graph.dependencies(step), produced)
                observer.dispatching(step, MappingProxyType(mounted))
                answer = read(step, mounted)
                assessment, artifacts = await answer if inspect.isawaitable(answer) else answer
                produced[step] = artifacts      # mounted into the NEXT step's payload, so it stays live here
                answered.append((step, assessment, artifacts))
        return Reading.gathered(answered)


@final
class _Flow(Dispatcher):
    """The barrier-free worker behind Flow. Every step starts the moment ITS OWN prerequisites settle.

    THE BARRIER IS THE COST THIS REMOVES. A wave is a barrier, so wave N+1 waits for the SLOWEST member of
    wave N even when a given step in it depends on only one, already-finished member. The Graph knows that -
    it derived the per-step edges and verified them - and the grouping then throws the knowledge away. This
    worker reads the edges back. It awaits `graph.dependencies(step)` per step and nothing else, so a long
    chain and a slow straggler stop blocking each other. On a wide, uneven declaration that is the whole
    win. On a flat or a strictly linear one there is nothing to win, so this only costs an Event per step.

    IT LEANS ON NO SEATING, which is why it declares Overlap.EDGES rather than borrowing NEITHER's word.
    The wave and chain workers are safe because the ARRANGER seated the steps for them, so the pairing
    guard has to check that the shape and the worker agree. This one ignores the grouping entirely and
    re-derives its ordering from the Graph, so every shape is safe for it - and the two constraints seating
    used to carry it must now carry itself:

    - the EDGES, awaited per step through the Event map below.
    - CONTENTION, which is otherwise enforced only by the arranger pushing rivals apart (see Arranger._apart).
      A worker that ignores the seating would silently run two steps that declared `contends` at once, so
      this one holds a lock per label instead. Same promise to the domain, kept by the only party that can.

    UNDER FailFast IT RAISES THE FIRST FAILURE TO SETTLE, not the first in resolved order. The wave family's
    determinism there is a property of the barrier - it settles a whole wave, then records in order - so it
    is exactly what this worker gives up. The record stays honest either way. The group is drained before
    the failure leaves, so no attempt outlives the run."""

    overlaps = Overlap.EDGES

    @override
    async def execute(self, groups: tuple[tuple[Step, ...], ...], graph: Graph, do: Callable[[Step, Artifacts], AsyncFlowOutcome], cancellation: Cancellation, observer: Observer) -> Statement:
        attempt = self._attempt(do)
        ledger = self._ledger(groups, observer, graph)
        every = [step for group in groups for step in group]
        # One Event per step, set the moment that step is FINISHED WITH - recorded, skipped or blocked
        # alike. Every path below sets it, because a dependent waiting on an event nobody sets is a hang,
        # and a hang is the one failure mode a barrier can never have.
        settled = {step: asyncio.Event() for step in every}
        held: dict[str, asyncio.Lock] = {label: asyncio.Lock() for step in every for label in step.contends}
        # THE HANDED SHAPE SAYS THE DIRECTION, THE GRAPH SAYS THE EDGES. A teardown is the same partition
        # INVERTED (prune walks partition.inverse()), so a worker that read `dependencies` and nothing else
        # would tear a thing down while its dependent still stood. Measured and backwards every time. The
        # seat index below is the only thing that knows which way this walk runs, so an edge counts as a
        # blocker exactly when its other end sits EARLIER in the order this run was handed. On a converge
        # that selects a step's prerequisites, on a teardown its dependents, with one rule and no flag.
        seat = {step: index for index, step in enumerate(every)}
        before = {
            step: tuple(other for other in (*graph.dependencies(step), *graph.dependents(step))
                        if other in seat and seat[other] < seat[step])
            for step in every
        }

        async def unit(step: Step) -> None:
            try:
                for prerequisite in before[step]:
                    await settled[prerequisite].wait()
                if cancellation.cancelled():
                    raise Cancelled.by(cancellation)
                if ledger.blocked(step):   # asked AFTER the wait, so the prerequisite's fate is recorded
                    return
                async with AsyncExitStack() as rivals:
                    for label in sorted(step.contends):
                        await rivals.enter_async_context(held[label])
                    mounted = ledger.assemble(step)
                    observer.dispatching(step, MappingProxyType(mounted))
                    ledger.record(*await attempt((step, mounted)))
            finally:
                settled[step].set()

        try:
            async with asyncio.TaskGroup() as group:
                for step in every:
                    group.create_task(unit(step))
        except BaseExceptionGroup as raised:
            # An abort cooperates and continues out as itself, exactly as the wave fan lets it. A single
            # ordinary failure is FailFast's and it leaves BARE. A caller's `except RuntimeError` is the
            # contract every other dispatcher keeps, so a group wrapper here would break it for this one.
            aborts, rest = raised.split(Cancelled)
            if aborts is not None and rest is None:
                raise next(iter(aborts.exceptions)) from None
            if rest is not None and len(rest.exceptions) == 1:
                raise rest.exceptions[0] from None
            raise
        return ledger.outcome()

    @override
    async def probe(self, groups: tuple[tuple[Step, ...], ...], graph: Graph, read: Callable[[Step, Artifacts], AsyncFlowAssessment], cancellation: Cancellation, observer: Observer) -> Reading:
        # The read side keeps the WAVE fan deliberately. A probe writes nothing, so there is no barrier cost
        # worth removing and no contention to hold, while the wave's all-or-raise ExceptionGroup is the read
        # contract every other dispatcher speaks. Reusing it keeps a Flow run's diagnosis identical.
        return await _Gather(self._on_error).probe(groups, graph, read, cancellation, observer)


@final
class Parallel(RunMode):
    """The default run mode. The Waves shape walked on the asyncio event loop by _Gather - a wave's
    coroutines awaited concurrently, barred between waves so every declared edge holds."""

    def __init__(self, on_error: OnError = OnError.FailFast):
        super().__init__(Waves(), _Gather(on_error))


@final
class Flow(RunMode):
    """Barrier-free. Every step starts the moment its OWN prerequisites settle, not when its whole wave does.

    The mode for a WIDE, UNEVEN declaration - one slow step in a wave stops holding up everything behind it,
    because the worker awaits the per-step edges the Graph already derived instead of the grouping that
    threw them away. On a flat or a strictly linear declaration there is nothing to win and it costs an
    Event per step, so Parallel stays the default.

    It reads the Graph rather than the seating, so it enforces `contends` itself with a lock per label and
    under FailFast it raises the first failure to SETTLE rather than the first in resolved order - the wave
    family's determinism there is a property of the barrier this mode exists to remove."""

    def __init__(self, on_error: OnError = OnError.FailFast):
        super().__init__(Walk(), _Flow(on_error))


@final
class Supervised(RunMode):
    """The Waves shape walked under SUPERVISION by _Watch - the Cancellation polled while a wave is in
    flight, so a Deadline can bound a hung apply() or assess(). poll is how often (seconds) a hung wave
    re-checks the Cancellation, grace how long an abort waits for its cancelled tasks to settle."""

    def __init__(self, on_error: OnError = OnError.FailFast, *, poll: float = 0.05, grace: float = 1.0):
        super().__init__(Waves(), _Watch(on_error, poll=poll, grace=grace))


@final
class Serial(RunMode):
    """The Walk shape walked one step at a time by _Walker - no concurrency anywhere, deterministic order.

    Reach for this mode when a run must be reproducible above all. A single-file order to read in a log,
    a domain whose writes must not overlap even when the graph says they may, a failure being narrowed
    where a fan would move under you between runs. It is the slowest shape by construction and the only
    one that overlaps nothing, so it can walk any partition safely."""

    def __init__(self, on_error: OnError = OnError.FailFast):
        super().__init__(Walk(), _Walker(on_error))


@final
class _ThreadWorker(Dispatcher):
    """The worker behind ThreadDispatcher. Runs a step's synchronous apply()/assess() on a worker thread
    through asyncio.to_thread, so a domain whose work is blocking I/O still rides the async engine without
    pinning the event loop.

    A DECORATOR over an underlying WORKER, not a waves family of its own. It wraps the write and the read in
    asyncio.to_thread and hands them to the worker it composes, so it inherits that one's wave mechanics
    rather than copying them. That is what lets WavesDispatcher.execute stay sealed @final. It is also what lets a
    caller thread a Parallel run OR a Supervised one. It carries NO arranger - the shape rides on the RunMode
    now, so a thread bridge never proxies one, which is the whole point of the 0.6.0 split."""

    # A pure decorator fans nothing itself and carries NO arranger - the underlying it wraps is a
    # correct-by-construction pairing (Parallel or Supervised) - so like the chaos decorator it declares
    # NEITHER and walks any shape the worker it wraps could.
    overlaps = Overlap.NEITHER

    def __init__(self, underlying: Dispatcher):
        self._underlying = underlying
        super().__init__(underlying._on_error)

    @override
    def walks(self) -> Overlap:
        # The bridge relocates the write, it does not change WHERE the pair overlaps - the worker underneath
        # still fans exactly as it did, so the guard must see that one's answer and not this decorator's.
        return self._underlying.walks()

    @override
    async def execute(self, groups: tuple[tuple[Step, ...], ...], graph: Graph, do: Callable[[Step, Artifacts], AsyncFlowOutcome], cancellation: Cancellation, observer: Observer) -> Statement:
        # The step's own HOOK is what goes on the worker thread. The run's layers are laid back over the
        # threaded form, not the other way round. Threading a wrapped callable instead was a real bug and a
        # loud one. Write.__call__ under Retry(n) hands back a coroutine, asyncio.to_thread returned it
        # unawaited and the wave then tried to unpack a coroutine object as an outcome. The step's apply()
        # never ran at all, so the blocking bridge and the retry were mutually exclusive - which nothing
        # noticed, because no test had ever composed the two.
        #
        # Laying the retry OUTSIDE the threading is also the only correct order on its own terms. An attempt
        # must cover one whole crossing to the blocking world, while a backoff must sleep on the event loop
        # rather than hold a worker thread idle. The PERMIT layer wants the same order for the same kind of
        # reason - an Authority answers immediately by contract and Local counts in a plain dict, so asking
        # it belongs on the one thread the run already serialises on, not on four workers at once.
        #
        # relay() is what gets that order right. Going through `do.raw` instead was the second shape of
        # the bug above. With an authority injected `raw` is a coroutine function, so to_thread only BUILT a
        # coroutine on the worker and the blocking write ran back on the event loop. Nothing raised and the
        # outcome was correct, which is why no residual, applied or ordering assertion could see it - a
        # four-step wave of 0.15s writes just took 0.60s instead of 0.15s and starved everything sharing
        # the loop.
        def relocate(raw: Callable[[Step, Artifacts], AsyncFlowOutcome]) -> Callable[[Step, Artifacts], AsyncFlowOutcome]:
            async def threaded_raw(step: Step, inputs: Artifacts) -> FlowOutcome:
                # An async step under this dispatcher builds its coroutine on the worker and is awaited here, so
                # the bridge tolerates both colours instead of silently mangling one. A blocking step - what this
                # dispatcher is FOR - returns its outcome directly and never reaches the await.
                outcome = await asyncio.to_thread(raw, step, inputs)
                return await outcome if inspect.isawaitable(outcome) else outcome

            return threaded_raw

        threaded_do = do.relay(relocate) if isinstance(do, Write) else relocate(do)
        return await self._underlying.execute(groups, graph, threaded_do, cancellation, observer)

    @override
    async def probe(self, groups: tuple[tuple[Step, ...], ...], graph: Graph, read: Callable[[Step, Artifacts], AsyncFlowAssessment], cancellation: Cancellation, observer: Observer) -> Reading:
        raw = cast(Callable[[Step, Artifacts], FlowAssessment], read)

        async def threaded_read(step: Step, inputs: Artifacts) -> FlowAssessment:
            # The same both-colours tolerance the write bridge has, for the same reason it has it. An async
            # step under this dispatcher builds its coroutine on the worker and is awaited here - before
            # this line, its assess() came back as an unawaited coroutine and the probe fell over unpacking
            # it, so the read side mangled exactly the step the write side had already learned to carry.
            reading = await asyncio.to_thread(raw, step, inputs)
            return await reading if inspect.isawaitable(reading) else reading

        return await self._underlying.probe(groups, graph, threaded_read, cancellation, observer)


@final
class ThreadDispatcher(RunMode):
    """The bridge for a blocking step, as a run mode. Wraps another RunMode and threads its worker through
    asyncio.to_thread while keeping the wrapped mode's shape. Defaults to Parallel when handed nothing, so
    ThreadDispatcher() threads a default parallel run - and ThreadDispatcher(Supervised()) threads a
    supervised one."""

    def __init__(self, underlying: "RunMode | None" = None):
        underlying = underlying if underlying is not None else Parallel()
        super().__init__(underlying._arranger, _ThreadWorker(underlying.dispatcher))


@final
class Crossing(NamedTuple):
    """One unit of work as it crosses a wire, versioned in the open.

    It replaced an anonymous three-tuple and the reason is the reason every distributed protocol
    eventually learns. A positional tuple pays for each new field twice - once when the shape changes and
    once when a peer on the old shape misreads the new one silently - and a lease token is exactly the kind
    of field that must never be misread. So the shape is named, the version rides at the front where a
    reader meets it first and `work()` REFUSES a version it does not know rather than dropping what it
    cannot see.

    That refusal is the whole design decision and it is not a preference. A worker that ignored an unknown
    field would run the hook without the token it was told to hold, so a capacity of three would be enforced
    by nobody while every log line said the run went fine. This project has already named that failure once,
    in its own words - "a fence the storage does not enforce is a suggestion". The price is a loud error on
    version skew, which makes deployment order load-bearing. Workers before coordinators. That is the right
    side of the trade for a field shaped like a permission.

    It pickles as cheaply as the tuple it replaced, being a tuple, so the byte ceiling that measures
    `len(payload)` is untouched and stays blind to what is inside.

    The three optional slots are here BEFORE their features are, deliberately. A lease token, a deadline and
    a trace id all have to cross. Paying one break now is cheaper than breaking the protocol once per
    feature. They ride as None until the axes that fill them ship.

    THE PERMIT AXIS SHIPPED AND `token` STILL RIDES AS None, which is a decision rather than an omission. A
    declared capacity is asked on the COORDINATOR before the envelope goes out, because that is the one party
    a run serialises on and the only one that can see a `Local` pool - a worker asking for itself would race
    a capacity it cannot count. So the slot waits for the OTHER half, a worker-side lease that narrows the
    window between dispatch and reply. That half needs a clock and a store this protocol deliberately does
    not have."""

    version: int
    verb: str
    step: Step
    inputs: Artifacts
    token: str | None = None       # a worker-side lease, once that half exists
    deadline: float | None = None  # a monotonic budget the far side may honour
    trace: str | None = None       # correlation for a caller's own tracing


# THE WIRE PROTOCOL'S OWN FACTS, one home for both halves of it. The worker vets what arrives and the
# coordinator stamps what leaves, so both sides read these - and while they lived on the worker, the
# coordinator reached into another class's privates to say what it itself speaks. A protocol is not the
# property of either end of it.
#
# The whole verb vocabulary of the step contract, which is the protocol's own guard. A coordinator only
# ever ships these three, so anything else in an envelope is version skew between the two sides.
#
# Written in the order a run SPENDS them - read the world, close the gap, tear it down. The set itself is
# unordered, so this is for the reader. A reader who meets `apply` first has to work out where the read
# went.
_WIRE_VERBS = frozenset({"assess", "apply", "prune"})

# The version this build speaks, shipped in every envelope and vetted on arrival. A CONSTANT rather than a
# parameter, because two peers negotiating a version per instance is a negotiation nobody audits - the
# version is a property of the code, while skew is a deployment fact.
_WIRE_VERSION = 1


@final
class _RemoteWorker(Dispatcher):
    """The wire worker behind RemoteDispatcher. A decorator whose transport carries each unit of work to a worker that does
    not share this process - with the verb in the envelope.

    A DECORATOR over an underlying wave dispatcher (Parallel, Supervised or the chaos axis wrapping
    one). The underlying keeps its wave mechanics. Every Graph and Ledger lookup inside them runs on the
    ORIGINAL steps, so the kernel never learns a step left the machine. What crosses is an envelope -
    (verb, step, inputs), pickled. What returns is the outcome or the exception the clone raised,
    re-raised here as if the hook had run locally. Correlation is the call's own stack,
    so no clone is ever used as a key. A queue-shaped transport correlates by its own token underneath
    this same call.

    The domain supplies ONE thing, the transport. A callable taking the envelope bytes and answering
    the reply bytes, plain or async - an HTTP client, a queue round trip, a subprocess pipe. The worker
    half ships here too. Work() runs one envelope and answers one reply, so the far side is a single
    call inside whatever framework already runs there.

    Retry rides the wire. So does the PERMIT. execute() reads the verb off the Write the reconciler
    built and relays the run's whole write stack around the crossing, so a transient network failure
    spends an attempt exactly as a transient write does, retryable()/retried keep seeing the real step,
    and a step's declared capacity is asked before the envelope leaves. Reads are never retried and ask
    for no capacity, as everywhere - the permit layer belongs to the write.

    THE POOL IS ASKED ON THIS SIDE OF THE WIRE, per crossing. The slot is released when the crossing
    returns. The coordinator is the one party a run serialises on and a `Local` authority lives in its
    memory. A worker asking for itself would race a capacity in a pool it cannot see, so the ask belongs
    here and the envelope's `token` slot stays reserved for a worker-side lease. A denial defers
    the step exactly as it does in-process, which means the envelope is never built, so a full pool
    costs the wire nothing at all.

    What crosses must be WIRE-SAFE. The step ships out, so the frozen declaration must pickle. The reply
    ships back, so changes, artifacts and ferried exceptions must too - a reply that cannot cross
    comes back as a LOUD protocol note naming what refused, never as a silent success and never
    impersonating the hook. And an abort only ferries one way. A worker-raised Cancelled crosses and
    cuts through here. A coordinator-side abort severs the WAIT, not the remote work - an in-flight
    crossing may land its write after this run has already raised. A transport that can cancel remotely
    does so itself.

    THE CHAOS AXIS DOES NOT REACH THIS ONE, in either order. The recommendation that used to stand here
    was the sharper half of the problem. Chaos OUTSIDE strips the verb from the envelope, so the first write
    is refused. Chaos INSIDE constructs and runs and gets the outcomes right. Its strikes are invisible to
    the retry and to the permit - measured, an injected drop announces zero retries and asks the pool zero
    times, where a REAL dropped crossing on the same composition announces one and asks twice. Two relocations
    both want to be innermost and a crossing has to be, so this is the same impossibility ChaosDispatcher
    refuses a ThreadDispatcher underlying for, one layer over. Sabotage a wire by breaking its TRANSPORT,
    which is a parameter of this class and needs no decorator at all. ThreadDispatcher does not compose here
    either. The wire awaits its transport,
    so there is nothing for a thread to bridge. A worker whose hooks block is the worker process's
    own concern.

    THE ENVELOPE IS A PICKLE. Loading one executes code by design - a step IS code. The transport
    must carry it between trusted peers running the same cabaxiom. Authentication and encryption belong
    to the transport, exactly as they do for any RPC. Version skew does NOT, any more - the envelope is a
    versioned `Crossing` and `work()` refuses a version it does not speak, because the one field whose
    silent loss would matter is a lease token and a limit enforced by nobody is not a limit."""

    # A pure decorator fans nothing itself and carries NO arranger - the underlying it wraps is a
    # correct-by-construction pairing (Parallel or Supervised) - so like the chaos decorator it declares
    # NEITHER and walks any shape the worker it wraps could.
    overlaps = Overlap.NEITHER

    # Re-exposed off the module constants so the worker half keeps the names its own guards and every
    # test reach for, without either end of the wire owning the protocol.
    _VERBS = _WIRE_VERBS
    _VERSION = _WIRE_VERSION

    def __init__(self, transport: Callable[[bytes], bytes | Awaitable[bytes]], underlying: Dispatcher,
                 *, limit: int | None = None):
        # The transport and the byte ceiling ride the worker, the coordinator side of the wire. The limit
        # validation and the ThreadDispatcher refusal live on RemoteDispatcher, the user-facing run mode
        # that composes this worker, since that is where a caller's mistake is actually made.
        self._transport = transport
        self._limit = limit
        self._underlying = underlying
        super().__init__(underlying._on_error)

    @override
    def walks(self) -> Overlap:
        # The wire relocates the crossing, it does not change WHERE the pair overlaps - the worker underneath
        # still fans exactly as it did, so the guard must see that one's answer and not this decorator's.
        return self._underlying.walks()

    @staticmethod
    def work(payload: bytes) -> bytes:
        """One envelope, run where it landed. The worker half of the protocol.

        Decodes a `Crossing`, runs the verb on the deserialized clone - driving a coroutine hook to
        completion on a fresh loop of its own - and answers one of three fates, pickled. ("outcome", what
        the hook returned), ("raised", what it raised) or ("skew", a sentence) when the reply itself
        cannot cross. A worker-raised abort ferries like a failure and re-raises at the coordinator, so
        Cancelled cuts through the wire from that side. A worker that already runs an event loop writes
        its own pump over the same envelope instead of calling this.

        THE ENVELOPE IS VETTED BEFORE THE HOOK IS TOUCHED, in three questions and in this order. Is it a
        Crossing at all, is its version one this side speaks and is its verb one the step contract has.
        Each is answered by refusing rather than by guessing, because every one of them is a symptom of the
        two sides running different code. The only field whose loss would be silent is exactly the kind
        of field this envelope exists to carry."""
        landed = pickle.loads(payload)
        if not isinstance(landed, Crossing):
            raise Skew(
                f"The envelope is a {type(landed).__name__} rather than a Crossing. The protocol carried an "
                f"anonymous three-tuple before this version, so a peer still shipping one is running older "
                f"code than this worker. Update the coordinator or pin both sides to one release."
            )
        if landed.version != _WIRE_VERSION:
            raise Skew(
                f"The envelope speaks protocol version {landed.version} and this worker speaks "
                f"{_WIRE_VERSION}. The version is refused rather than read past, because an "
                f"unknown field is a field this worker would drop in silence. The envelope exists to "
                f"carry a lease token whose loss nobody would notice until a capacity limit stopped holding. "
                f"Deploy workers before coordinators."
            )
        verb, step, inputs = landed.verb, landed.step, landed.inputs
        if verb not in _WIRE_VERBS:
            raise Skew(
                f"The envelope names {verb!r}, which is no verb of the step contract. A coordinator "
                f"ships apply, prune or assess, so anything else is protocol skew between the two sides."
            )
        fate = "outcome"
        ferried: object
        try:
            ferried = getattr(step, verb)(inputs)
            if inspect.isawaitable(ferried):
                try:
                    asyncio.get_running_loop()
                except RuntimeError:
                    ferried = asyncio.run(cast(Coroutine[Any, Any, object], ferried))
                else:
                    cast(Coroutine[Any, Any, object], ferried).close()
                    raise RuntimeError(
                        f"The {verb} is a coroutine and work() landed on a thread already running an "
                        f"event loop - the in-process loopback. Carry work() through asyncio.to_thread "
                        f"or run it in a worker process, so the coroutine gets the fresh loop it needs."
                    )
        except BaseExceptionGroup as grouped:
            # The worker-side twin of run_wave's sift. A pure abort ferries as the abort itself, so
            # Cancelled still cuts through the wire even out of a hook's own TaskGroup.
            aborts, rest = grouped.split(Cancelled)
            fate = "raised"
            ferried = next(iter(aborts.exceptions)) if aborts is not None and rest is None else grouped
        except (Cancelled, Exception) as failure:
            fate, ferried = "raised", failure
        try:
            return pickle.dumps((fate, ferried))
        except Exception as refused:
            # The hook ALREADY RAN. Saying "step failed" here would impersonate it and hand retry a
            # write that landed, so the truth crosses instead. A sentence, which always pickles.
            told = (
                f"The {verb} raised {ferried!r}. That exception itself refuses to pickle ({refused})."
                if fate == "raised"
                else f"The {verb} ran on the worker. Its reply refuses to pickle ({refused})."
            )
            return pickle.dumps(("skew", f"{told} Changes, artifacts and ferried exceptions must be "
                                         f"wire-safe data - keep handles and open resources out of them."))

    async def __crossing(self, verb: str, step: Step, inputs: Artifacts) -> object:
        # ONE crossing - envelope out, reply in, the ferried exception re-raised as if the hook had run
        # here. The transport is taken in both colours, like every hook the kernel accepts. The reply's
        # fate is guarded as strictly as the outbound verb. A reply this coordinator does not recognise
        # is protocol skew said out loud, never a silent success for dependents to build on.
        envelope = pickle.dumps(Crossing(_WIRE_VERSION, verb, step, inputs))
        if self._limit is not None and len(envelope) > self._limit:
            # NOTHING has crossed yet, so this is an ordinary refusal the policy classifies - and it is
            # deterministic, so a retry budget spent on it is a budget wasted, which the sentence says.
            raise ValueError(
                f"The {verb} envelope for {Step.named(step)} is {len(envelope)} bytes against the "
                f"wire's limit of {self._limit}. Artifacts carry pointers, not payloads - a URI belongs "
                f"in the artifact where the data frame does not - and the same envelope will exceed the "
                f"same limit on every retry."
            )
        reply = self._transport(envelope)
        if inspect.isawaitable(reply):
            reply = await reply
        if self._limit is not None and len(reply) > self._limit:
            # The hook ALREADY RAN on the worker - only its reply exceeds the ceiling - so this crosses
            # as Skew, the fate a retry structurally cannot spend. Re-shipping would re-run a landed
            # write to fetch the same oversized reply.
            raise Skew(
                f"The {verb} ran on the worker. Its reply is {len(reply)} bytes against the wire's "
                f"limit of {self._limit}. Artifacts carry pointers, not payloads - hand back a URI and "
                f"let the data plane move the data."
            )
        fate, payload = cast(tuple[str, object], pickle.loads(reply))
        if fate == "outcome":
            return payload
        if fate == "raised":
            if isinstance(payload, BaseException):
                raise payload
            raise Skew(
                f"The reply says the {verb} raised but ferries {payload!r} instead of an exception - "
                f"protocol skew between the two sides."
            )
        if fate == "skew":
            raise Skew(str(payload))
        raise Skew(
            f"The reply names fate {fate!r}, which is no fate of the wire protocol (outcome, raised, "
            f"skew) - version skew between the two sides."
        )

    @override
    async def execute(self, groups: tuple[tuple[Step, ...], ...], graph: Graph, do: Callable[[Step, Artifacts], AsyncFlowOutcome], cancellation: Cancellation, observer: Observer) -> Statement:
        if not isinstance(do, Write):
            raise ValueError(
                f"{self.__class__.__name__} needs the verb in its envelope. A bare callable does "
                f"not carry one. Drive it from a Reconciler, whose write phases arrive as a Write - or "
                f"hand execute() a Write of your own. A wrapping dispatcher that rebuilds the callable "
                f"strips the carrier (ChaosDispatcher does), so compose such a wrapper INSIDE this one, "
                f"never outside."
            )
        verb = do.verb

        async def crossed(step: Step, inputs: Artifacts) -> FlowOutcome:
            # AWAITED HERE rather than handed back unawaited, which is what the read path one method down
            # already did. The old shape cast the coroutine itself across the union. A coroutine of
            # `object` is the WIDER type - the cast narrowed the thing it was carrying rather than the
            # thing it returned, which is the shape of a cast that can quietly be wrong. A coroutine
            # function satisfies the same callable, because the fan awaits what it gets either way.
            return cast(FlowOutcome, await self.__crossing(verb, step, inputs))

        def relocate(_hook: Callable[[Step, Artifacts], AsyncFlowOutcome]) -> Callable[[Step, Artifacts], AsyncFlowOutcome]:
            # THE CROSSING IS A RELOCATION, a total one, which is why the local hook is answered
            # rather than called. The code that runs is the worker's own clone of this step, so there is
            # nothing here to wrap - but everything the carrier lays AROUND a hook still applies and
            # laying it is relay()'s job rather than this decorator's.
            return crossed

        # THE AUTHORITY IS ASKED HERE, ON THE COORDINATOR, BEFORE THE CROSSING. Going through rewire()
        # laid the retry alone, so a step declaring `leases` crossed the wire with its pool never asked
        # once - the write LANDED, the run reported clean and a declared capacity of three was enforced
        # by nobody. This kernel already wrote the verdict on that shape one class up, ruling that a
        # fence the storage does not enforce is a suggestion.
        #
        # THIS SIDE and not the far side. That is the load-bearing half of the fix. The coordinator
        # is the one party a run serialises on and a Local authority counts in its own memory. A worker
        # asking for itself would race a capacity in a pool it cannot see, so the ask happens where the
        # answer means something, exactly as the thread bridge keeps it off its workers. The slot is
        # released when the crossing returns. A denial raises Deferred before the envelope is built, so
        # nothing crosses for a step that never ran.
        return await self._underlying.execute(groups, graph, do.relay(relocate), cancellation, observer)

    @override
    async def probe(self, groups: tuple[tuple[Step, ...], ...], graph: Graph, read: Callable[[Step, Artifacts], AsyncFlowAssessment], cancellation: Cancellation, observer: Observer) -> Reading:
        # The Cancellation stays LOCAL - a cooperative bool has no meaning on the far side of a wire - so it
        # rides to the underlying fan, where it bounds the waves of crossings exactly as it bounds local reads.
        async def crossed(step: Step, inputs: Artifacts) -> FlowAssessment:
            return cast(FlowAssessment, await self.__crossing("assess", step, inputs))

        return await self._underlying.probe(groups, graph, crossed, cancellation, observer)


@final
class RemoteDispatcher(RunMode):
    """The wire, shipped, as a run mode. Wraps another RunMode and carries each unit of work over a
    transport to a worker that does not share this process, keeping the wrapped mode's shape. The wire
    mechanics live on the composed _RemoteWorker (see its docstring for the protocol, the permit and the
    byte ceiling). This run mode is the user-facing seam that pairs the worker with the shape and vouches
    the composition.

    The domain supplies ONE thing, the transport. The worker half ships here too, as the static work(),
    re-exposed from the worker so a remote process runs RemoteDispatcher.work on the envelope bytes."""

    # Re-exposed from the worker so the worker half and the protocol version keep their user-facing home -
    # the name a remote process and every test reach for.
    _VERBS = _WIRE_VERBS
    _VERSION = _WIRE_VERSION
    work = staticmethod(_RemoteWorker.work)

    def __init__(self, transport: Callable[[bytes], bytes | Awaitable[bytes]], underlying: "RunMode | None" = None,
                 *, limit: int | None = None):
        # The two caller mistakes live here, at the user-facing seam. A non-positive byte ceiling is a
        # nonsense limit. Wrapping a ThreadDispatcher is the one composition the wire refuses - the thread
        # bridge narrows every write to a synchronous call while a crossing is a coroutine, so each
        # envelope would come back un-awaited and the run would blame the steps.
        if limit is not None and limit < 1:
            raise Misconfigured(f"RemoteDispatcher limit must be a positive byte count or None, got {limit}.")
        underlying = underlying if underlying is not None else Parallel()
        if isinstance(underlying, ThreadDispatcher):
            raise Pairing(
                "RemoteDispatcher cannot wrap a ThreadDispatcher - the thread bridge narrows every write "
                "to a synchronous call while a crossing is a coroutine, so each envelope would come back "
                "un-awaited and the run would blame the steps. The wire awaits its transport and needs "
                "no thread. Wrap Parallel or Supervised and let a blocking hook be the worker process's "
                "own concern."
            )
        super().__init__(underlying._arranger, _RemoteWorker(transport, underlying.dispatcher, limit=limit))


