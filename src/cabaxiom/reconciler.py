"""Reconciler - resolves Steps once, then reports drift or converges and self-verifies. A Controller drives it in a loop."""
import asyncio
from collections.abc import AsyncIterator, Callable, Iterable
from typing import final

from .cancellation import Cancellation
from .convergence import Convergence, Once
from .dispatcher import Dispatcher, Serial, Write
from .drift import Drift, Outcome
from .observer import Observer
from .ordering import Kahn, Ordering
from .retry import Retry
from .scope import Scope
from .settle import Clean, Settle
from .step import Step


@final
class Residual(list[Drift]):
    """The list converge() returns (empty == verified success), also carrying the applied channel.

    It is a list of the residual Drift, so callers that test truthiness, iterate or compare
    against [] behave unchanged. `applied` records what apply() changed this run - the transaction
    summary the residual cannot give, since the residual answers "what is STILL wrong", not "what
    did you touch".
    """
    def __init__(self, residual: list[Drift], applied: list[Drift]):
        super().__init__(residual)
        self.applied: list[Drift] = list(applied)

    def __repr__(self) -> str:
        # The inherited list repr hides the applied channel, so show both.
        return f"Residual({super().__repr__()}, applied={self.applied!r})"


@final
class Explanation:
    """What the Reconciler resolved, surfaced read-only: the groups the dispatcher walks in run order plus the
    `Step.after` edges behind that order.

    `groups` is the resolved run structure, each inner tuple one group of step type names - a wave (independent
    within, sequential between) under a level dispatcher or a chain (sequential within, concurrent between)
    under Pipeline. `edges` pairs each step type with the types it declares in `after`, in the same run order.
    This is exactly the partition drift() and converge() walk, so it explains the real run and re-resolves
    nothing.
    """
    def __init__(self, groups: tuple[tuple[str, ...], ...], edges: tuple[tuple[str, tuple[str, ...]], ...]):
        self.groups = groups
        self.edges = edges

    def __repr__(self) -> str:
        # One line. Each group a parenthesised set of type names, the groups joined in run order.
        flow = " -> ".join("(" + ", ".join(group) + ")" for group in self.groups) or "()"
        return f"Explanation({flow})"


@final
class Reconciler:
    """Resolves an explicit, ordered set of Steps once, then either reports drift (read-only) or
    converges actual -> desired (idempotent) and self-verifies by re-probing for the residual.

    No registry, no auto-discovery, no capability probing. The kernel takes the steps it is handed.
    Ordering is an injected strategy (Kahn by default). The self-verifying converge is the core.
    """

    def __init__(self, steps: Iterable[Step], ordering: Ordering | None = None, *,
                 scope: Scope | None = None, dispatcher: Dispatcher | None = None,
                 convergence: Convergence | None = None, cancellation: Cancellation | None = None,
                 observer: Observer | None = None, retry: Retry | None = None):
        # Resolve defaults here, not as mutable default args. A default instance in the signature
        # would be built once at import and shared across every Reconciler, a trap the moment a
        # default holds state (a pool, a flag).
        scope = scope or Scope()   # the base keeps every step, the run-everything default
        ordering = ordering or Kahn()
        dispatcher = dispatcher or Serial()
        convergence = convergence or Once()
        cancellation = cancellation or Cancellation()
        observer = observer or Observer()
        retry = retry or Retry(1)   # the neutral single try, which wraps nothing
        # The scope first decides WHICH of the handed steps take part, resolved once here so every
        # verb sees the same set. Then the dispatcher builds and verifies the partition shape it can
        # run (Serial - a serial walk of levels, Parallel - independent waves, Pipeline - independent
        # chains). An dispatcher that cannot run the Ordering it was handed raises from arrange(),
        # naming the fix.
        self.__partition = dispatcher.arrange(ordering, scope.select(tuple(steps)))
        self.__dispatcher = dispatcher
        self.__convergence = convergence
        self.__cancellation = cancellation
        self.__observer = observer
        self.__retry = retry

    async def drift(self) -> list[Drift]:
        # Flatten every step's drift, in resolved order. [] == fully in desired state.
        return await self.__probe(self.__partition, "deviation")

    async def plan(self) -> list[Drift]:
        # The dry run. What converge WOULD do, without doing it. Flatten every step's plan() preview
        # in resolved order, reusing the Drift channel. [] == nothing to do. Read-only, so it is safe
        # to call before converge() to show the work.
        return await self.__probe(self.__partition, "plan")

    async def audit(self) -> list[Drift]:
        # The advisory read. Flatten every step's audit() (findings about a system that meets desired
        # state yet still deserves attention) in resolved order, through the same read engine as drift
        # and plan. [] == nothing to advise. converge() never calls this and its findings never enter
        # the residual, so the empty residual stays the proof desired state was reached. A consumer
        # opts in by calling audit() itself, typically alongside drift().
        return await self.__probe(self.__partition, "advisory")

    async def footprint(self) -> list[Drift]:
        # The teardown preview. Everything the steps own that exists now, flattened in the order
        # prune() would tear it down. Read-only through the same engine as the other reads, and
        # prune() never consults it.
        return await self.__probe(self.__partition.inverse(), "footprint")

    def explain(self) -> Explanation:
        # The structural read (returns an Explanation, not Drift). What the injected Ordering resolved and the
        # dispatcher will walk, as step type names in run order plus the Step.after edges behind them. Reads the
        # same resolved partition every other verb uses, so it explains the actual run and re-resolves nothing.
        groups = tuple(tuple(Step.named(step) for step in group) for group in self.__partition)
        edges = tuple(
            (Step.named(step), tuple(dependency.__name__ for dependency in type(step).after))
            for group in self.__partition for step in group
        )
        return Explanation(groups, edges)

    async def converge(self) -> Residual:
        # Apply every step and re-probe for what is STILL out of desired state. The returned residual
        # is the proof it worked, `applied` the record of what changed.
        #
        # CQS - a command returning its own outcome (this run's failures + a fresh re-probe + applied),
        # none reconstructible by a later read. Splitting into a query would need a persistent store to
        # read the post-state back, which this kernel deliberately lacks. Persistence is a consumer
        # concern. The pure queries are drift/plan/audit.
        #
        # The injected Convergence strategy decides how many times to repeat the apply -> re-probe
        # cycle. Once (default) runs it a single time, Fixpoint loops until the residual settles, for
        # steps that only come good once an earlier step's apply() has cleared the way.
        #
        # A step's apply() may RAISE (FailFast propagates, BestEffort records it as residual Drift) and
        # may optionally return what it changed. The dispatcher hands those changes back as its first
        # list, apart from the failures, so we accumulate them into `applied` here on the calling thread
        # across every pass and keep them OUT of the residual, preserving empty-list == verified-success.
        # Collecting on this thread (not in the dispatcher's workers) keeps applied race-free and in
        # resolved order under a fanning dispatcher. A report-only step returns None and contributes
        # nothing here, so the re-probe still surfaces it in the residual.
        applied: list[Drift] = []

        async def cycle() -> list[Drift]:
            self.__observer.began()
            applied_this_pass, failures = await self.__execute(self.__partition, lambda step: step.apply())
            applied.extend(applied_this_pass)
            self.__observer.acted(applied_this_pass)

            residual = failures + await self.drift()
            self.__observer.remained(residual)
            return residual

        return Residual(await self.__convergence(cycle), applied)

    async def watch(self, *, settle: Settle | None = None) -> AsyncIterator[Residual]:
        """The standing run - converge, hand back the residual, then wait for a step to say look again.

        It replaces a tick-driven Controller. The difference is who decides when to look. A tick source
        made the CALLER guess an interval, so a fast world was answered late and a quiet one was polled for
        nothing. Here the steps say when their own world moved, through Step.watch(), while the loop sleeps
        between wakes rather than counting.

        Level-triggered throughout. A wake carries no payload and means only look again, so this re-reads
        the WHOLE declaration every time rather than processing a delta. That is what makes a missed wake,
        a coalesced wake and a doubled wake all harmless.

        It ends when the injected Settle says so or when every step's source is exhausted - a declaration
        of steps that announce nothing converges once and then finishes, rather than hanging on a wake that
        can never come.
        """
        deciding = settle if settle is not None else Clean()
        sources: list[AsyncIterator[None]] = [step.watch().__aiter__()
                                              for group in self.__partition for step in group]
        async def woken_by(source: AsyncIterator[None]) -> None:
            # One wake from one source. A source that has run dry raises StopAsyncIteration through this
            # and the loop below reads that as "this step has nothing more to say", which is a different
            # fact from "nothing has happened yet" and has to stay tellable from it.
            await source.__anext__()

        pending: dict[asyncio.Task[None], AsyncIterator[None]] = {
            asyncio.create_task(woken_by(source)): source for source in sources
        }
        try:
            while True:
                residual = await self.converge()
                yield residual
                if deciding.settled(residual):
                    return
                while pending:
                    done, _ = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
                    woke = False
                    for task in done:
                        source = pending.pop(task)
                        try:
                            task.result()
                        except StopAsyncIteration:
                            continue          # that step has nothing more to say, the others may
                        pending[asyncio.create_task(woken_by(source))] = source
                        woke = True
                    if woke:
                        break
                if not pending:
                    return                    # every source is exhausted, so no wake can ever arrive
        finally:
            for task in pending:
                task.cancel()

    async def prune(self) -> list[Drift]:
        # The deletion half, the mirror of converge. Run every step's prune() in REVERSE resolved order
        # (tear a dependent down before the thing it depends on) through the same dispatcher, so the
        # OnError policy and the serial/parallel choice apply identically.
        #
        # CQS - like converge, a command returning its own outcome, the residue that survived teardown
        # ([] == everything gone). Even less splittable, since prune has no re-probe.
        #
        # Self-verifying. Each prune() removes its artifact and returns what SURVIVED, which the dispatcher
        # collects, so the returned residual is the proof teardown worked. drift() is deliberately NOT
        # re-probed here. It measures deviation from the should-EXIST state, so after teardown it would
        # report everything as "missing" (noise, not proof). Concatenate the survived residue with any
        # hard dispatcher failures under BestEffort. The residual is a (name, message) proof set, so the
        # order of the two groups within it does not matter.
        residue, failures = await self.__execute(self.__partition.inverse(), lambda step: step.prune())
        return residue + failures

    # noinspection PyMethodMayBeStatic
    async def __probe(self, groups: tuple[tuple[Step, ...], ...], channel: str) -> list[Drift]:
        # The single READ engine. One assess() per step, flattened over the whole run, with the caller
        # naming which channel of the reading it came for. drift, plan and audit walk the resolved
        # partition, footprint walks the teardown order, so the direction is still the caller's to hand
        # in - what changed is that the four verbs now share one PROBE and not merely one flattener.
        #
        # A step with an expensive read used to pay for it four times over, since nothing forced the four
        # answers to describe the same moment of the world. Now they cannot describe different ones.
        readings = await self.__dispatcher.probe(groups, lambda step: step.assess())
        return [item for reading in readings for item in getattr(reading, channel)]

    async def __execute(self, groups: tuple[tuple[Step, ...], ...], do: Callable[[Step], Outcome]) -> tuple[list[Drift], list[Drift]]:
        # The single WRITE engine. Sequence steps, funnelling both converge (forward partition,
        # do = apply) and prune (reversed partition, do = prune) through the injected Dispatcher. The
        # write callable goes in wrapped by the injected Retry, so a transient failure spends its
        # attempts inside the dispatcher's unit of work and only a failure that outlived them meets
        # the OnError policy. Retry is a transparent wrapper that may hand back an awaitable-returning
        # callable (an async step under Async), which is the same Outcome the dispatcher's do already
        # declares, so the wrapper needs no restating on the way in. The Dispatcher owns HOW (serial,
        # level-parallel or chain-pipelined) and the OnError policy. It returns two lists apart -
        # (do-returns, failures). The direction is the caller's.
        return await self.__dispatcher.execute(groups, Write(self.__retry, do), self.__cancellation)
