"""Dispatcher strategies - HOW a Partition is run. Serial, the pooled Parallel (waves) and Pipeline (chains) plus the event-loop Async (waves)."""
import asyncio
import inspect
from abc import ABC, abstractmethod
from collections.abc import Callable
from enum import Enum
from typing import final

from ._compat import override
from .cancellation import Cancellation, Cancelled
from .drift import Assessed, Assessment, Changes, Drift, DriftItem, Outcome
from .ordering import Ordering
from .partition import Chains, Levels, Partition
from .step import Step


@final
class _Fan:
    """The shape a fanning executor fans into, composed onto it as `_shape` - how to turn an Ordering into a
    verified Partition and why a flat Ordering is rejected. Two exist, dual to each other, built by the
    `waves()` factory for the level-fanners (Parallel, Async) and `chains()` for the chain-fanner (Pipeline).
    Serial fans nothing, composes no shape and keeps the serial-safe default. The per-shape wording lives here
    because only the shape knows why its own fallback is wrong. A fanned flat wave ignores Step.after, a
    pipelined single chain runs nothing concurrently."""

    def __init__(self, into: type[Partition], via: str, needs: str, otherwise: str, use: str):
        self.__into = into      # the Partition subclass this shape builds: Levels or Chains
        self.__via = via        # the Ordering method that feeds it: "levels" or "chains"
        self.__needs = needs
        self.__otherwise = otherwise
        self.__use = use

    @classmethod
    def waves(cls) -> "_Fan":
        # The shape the level-fanners compose - independent topological waves, drawn from Kahn's levels.
        return cls(
            into=Levels, via="levels",
            needs="level-aware Ordering that splits steps into independent waves",
            otherwise="only yields a flat order from levels(), which fanned out would ignore Step.after",
            use="Kahn",
        )

    @classmethod
    def chains(cls) -> "_Fan":
        # The shape the chain-fanner composes - independent dependency chains, drawn from Components.
        return cls(
            into=Chains, via="chains",
            needs="chain-aware Ordering that splits steps into independent chains",
            otherwise="only yields one chain of everything from chains(), which pipelined would run nothing concurrently",
            use="Components",
        )

    def __call__(self, dispatcher: str, ordering: Ordering, steps: tuple[Step, ...]) -> Partition:
        # An Ordering that does not override `via` only yields the flat fallback, so reject it as a class (the
        # unbound override check against the ABC names no concrete strategy) before running. Then build the
        # shape from the groups it produces and verify the placement upfront.
        if getattr(type(ordering), self.__via) is getattr(Ordering, self.__via):
            raise ValueError(
                f"{dispatcher} needs a {self.__needs}, yet {type(ordering).__name__} {self.__otherwise}. Use {self.__use}."
            )
        partition = self.__into(getattr(ordering, self.__via)(steps))
        partition.verify()
        return partition


class OnError(Enum):
    # What the Executor does when a step's apply() (or prune()) raises.
    FailFast = "FailFast"      # let it propagate and abort the run
    BestEffort = "BestEffort"  # catch it, record it as Drift, keep going with the rest of the run


class BaseDispatcher(ABC):
    """The half a dispatcher INHERITS - the shape it fans into and the failure policy it obeys.

    Split off because the policy had three homes. Serial kept it privately, the pooled pair kept it
    protected under a different name, while the async one kept its own private copy again, so a fourth
    dispatcher had to remember to declare a fourth. One home, one name, so a subclass that forgets to
    call super().__init__() now fails loudly instead of quietly defaulting to nothing."""

    _shape: "_Fan | None" = None   # the shape a subclass fans into (waves() or chains()); None means it fans nothing

    def __init__(self, on_error: OnError = OnError.FailFast):
        self._on_error = on_error

    def arrange(self, ordering: Ordering, steps: tuple[Step, ...]) -> Partition:
        # The dispatcher turns the injected Ordering into the Partition SHAPE it runs. A non-fanning one
        # (Serial, no _shape) walks a serial-safe level partition (real waves from Kahn, the one-wave
        # fallback from DFS/Components) in order on one thread, honouring Step.after with no verification.
        # A fanning one delegates to its composed shape, which demands the Ordering it needs, builds the
        # partition and verifies it upfront.
        if self._shape is None:
            return Levels(ordering.levels(steps))
        return self._shape(type(self).__name__, ordering, steps)


class Dispatcher(BaseDispatcher, ABC):
    # Strategy for HOW a resolved set of steps is run. Serial walks them in order on the caller's loop,
    # Parallel gathers each dependency wave, Pipeline gathers each independent chain. The dispatcher is the
    # ONLY thing that invokes a step, so it is the ONLY thing that can catch, which is why the OnError
    # policy lives here. It checks the injected cancellation before each unit of work.
    #
    # ASYNC NATIVE, AND THERE IS EXACTLY ONE OF IT. The kernel used to ship a synchronous family beside an
    # Async executor that spun a private event loop per pass, so a caller who already had a loop ended up
    # with two, so an apply() that wanted to share the caller's connection pool could not. A mirror is two
    # implementations of one idea and the second one is always slightly wrong. A step whose apply() is a
    # plain function still runs inline and pays nothing for the colour of the engine around it.
    #
    # execute() returns TWO lists, kept apart on purpose - (returns, failures). `returns` is everything do()
    # itself handed back (converge's applied items, prune's surviving residue), `failures` is the exception
    # drift (empty under FailFast, which re-raises instead of collecting). Returning them apart lets converge
    # route its applied items to their own channel and lets prune concatenate them since for a teardown both
    # are residual.

    @abstractmethod
    async def execute(self, groups: tuple[tuple[Step, ...], ...], do: Callable[[Step], Outcome], cancellation: Cancellation) -> tuple[list[Drift], list[Drift]]:
        ...

    @abstractmethod
    async def probe(self, groups: tuple[tuple[Step, ...], ...], read: Callable[[Step], Assessed]) -> list[Assessment]:
        # The READ phase, fanned by the same dispatcher that fans the writes. It used to be a list
        # comprehension inside the reconciler, so a concurrent run applied its steps concurrently and then
        # read them back one at a time - the proof of the run was the slowest part of it.
        #
        # No cancellation argument, deliberately. A read touches nothing, so there is nothing to abort
        # part-way through and nothing an abort would save.
        ...

    @staticmethod
    def _reading(settled: list[Assessment | BaseException]) -> list[Assessment]:
        # THE RULE A BROKEN READ OBEYS. Every entry has already settled by the time this runs, so no
        # sibling read is left running detached on the loop to warn at teardown - and if any entry is an
        # exception, the FIRST in resolved order is raised. Reads stay single-try and fail loud, they just
        # no longer leave the loop dirty behind them.
        for outcome in settled:
            if isinstance(outcome, BaseException):
                raise outcome
        return [outcome for outcome in settled if isinstance(outcome, Assessment)]

    @staticmethod
    async def _settle_read(reading: Assessed) -> Assessment:
        # A read's outcome, awaited when the step handed back a coroutine and taken as-is otherwise, so a
        # plain `def assess()` stays a legal override beside an `async def assess()`.
        return await reading if inspect.isawaitable(reading) else reading

    @staticmethod
    async def _settle(outcome: Outcome) -> Changes:
        # One write's outcome, awaited when the step handed back a coroutine and taken as-is otherwise.
        # The ONE place the two shapes of a write meet, so no dispatcher has to know a step's colour.
        return await outcome if inspect.isawaitable(outcome) else outcome

    def _record(self, step: Step, produced: Changes, broke: BaseException | None,
                returns: list[Drift], failures: list[Drift]) -> None:
        # The ONE raise-or-collect rule, shared by all three. An abort cuts through first, since it is a
        # decision and not a failure. Then FailFast re-raises and BestEffort records exactly one entry.
        if isinstance(broke, Cancelled):
            raise broke
        if broke is not None:
            if self._on_error is OnError.FailFast:
                raise broke
            failures.append(DriftItem(Step.named(step), f"step failed: {type(broke).__name__}: {broke}"))
        elif produced:  # prune's residue or converge's applied items - apply's no-op returns None
            returns.extend(produced)


@final
class Serial(Dispatcher):
    """One step at a time, in resolved order, on the caller's own event loop.

    No concurrency and no threads, which makes it the shape to reach for when a domain's writes cannot
    overlap at all. A coroutine apply() is still awaited here - serial means one at a time, not synchronous.
    """

    @override
    async def execute(self, levels: tuple[tuple[Step, ...], ...], do: Callable[[Step], Outcome], cancellation: Cancellation) -> tuple[list[Drift], list[Drift]]:
        returns: list[Drift] = []
        failures: list[Drift] = []
        for level in levels:
            for step in level:
                if cancellation.cancelled():
                    raise Cancelled.by(cancellation)
                broke: BaseException | None = None
                produced: Changes = None
                try:
                    produced = await self._settle(do(step))
                except Cancelled:
                    raise   # nothing is in flight beside it, so it propagates rather than being ferried
                except Exception as exception:
                    broke = exception
                self._record(step, produced, broke, returns, failures)
        return returns, failures

    @override
    async def probe(self, groups: tuple[tuple[Step, ...], ...], read: Callable[[Step], Assessed]) -> list[Assessment]:
        # One at a time, where a break propagates as itself - nothing else is in flight to settle first.
        return [await self._settle_read(read(step)) for group in groups for step in group]


@final
class Parallel(Dispatcher):
    """Each dependency wave gathered on the event loop, with a barrier between waves.

    The wave IS the barrier - every step in it settles before the next wave starts, which is what makes
    Step.after hold under concurrency. It absorbs what used to be a separate Async executor, because once
    the engine has one colour there is nothing left for a second fanning dispatcher to be.
    """

    _shape = _Fan.waves()

    @override
    async def execute(self, levels: tuple[tuple[Step, ...], ...], do: Callable[[Step], Outcome], cancellation: Cancellation) -> tuple[list[Drift], list[Drift]]:
        # attempt() ALWAYS catches, including the abort, then hands the step back beside its outcome, because
        # a gathered wave settles out of order and the caller has to know which result belongs to which step.
        async def attempt(step: Step) -> tuple[Step, Changes, BaseException | None]:
            try:
                return step, await self._settle(do(step)), None
            except Cancelled as abort:
                return step, None, abort
            except Exception as exception:
                return step, None, exception

        returns: list[Drift] = []
        failures: list[Drift] = []
        for level in levels:
            if cancellation.cancelled():
                raise Cancelled.by(cancellation)
            # gather preserves input order, so `returns` builds in resolved step order, while every coroutine
            # in the wave has settled before a single outcome is inspected.
            for step, produced, broke in await asyncio.gather(*(attempt(step) for step in level)):
                self._record(step, produced, broke, returns, failures)
        return returns, failures

    @override
    async def probe(self, groups: tuple[tuple[Step, ...], ...], read: Callable[[Step], Assessed]) -> list[Assessment]:
        readings: list[Assessment] = []
        for group in groups:
            settled = await asyncio.gather(*(self._settle_read(read(step)) for step in group),
                                           return_exceptions=True)
            readings.extend(self._reading(list(settled)))
        return readings


@final
class Pipeline(Dispatcher):
    """Each independent chain its own coroutine, the steps within a chain in series.

    The dual of Parallel. Where Parallel overlaps the steps that share a wave, this overlaps whole chains
    that share no edge, which suits a graph of long independent strands better than a wide shallow one.
    """

    _shape = _Fan.chains()

    @override
    async def execute(self, chains: tuple[tuple[Step, ...], ...], do: Callable[[Step], Outcome], cancellation: Cancellation) -> tuple[list[Drift], list[Drift]]:
        # A chain is walked in series and checks the cancellation between its own steps, since a chain can
        # be long where a wave is one fan. It hands back settled outcomes rather than recording them, so the
        # raise-or-collect rule still runs once, on the caller, in chain order.
        async def run_chain(chain: tuple[Step, ...]) -> list[tuple[Step, Changes, BaseException | None]]:
            settled: list[tuple[Step, Changes, BaseException | None]] = []
            for step in chain:
                if cancellation.cancelled():
                    settled.append((step, None, Cancelled.by(cancellation)))
                    return settled
                try:
                    settled.append((step, await self._settle(do(step)), None))
                except Cancelled as abort:
                    settled.append((step, None, abort))
                    return settled
                except Exception as exception:
                    settled.append((step, None, exception))
                    if self._on_error is OnError.FailFast:
                        return settled
            return settled

        returns: list[Drift] = []
        failures: list[Drift] = []
        if cancellation.cancelled():
            raise Cancelled.by(cancellation)
        for chain in await asyncio.gather(*(run_chain(chain) for chain in chains)):
            for step, produced, broke in chain:
                self._record(step, produced, broke, returns, failures)
        return returns, failures

    @override
    async def probe(self, groups: tuple[tuple[Step, ...], ...], read: Callable[[Step], Assessed]) -> list[Assessment]:
        async def read_chain(chain: tuple[Step, ...]) -> list[Assessment]:
            return [await self._settle_read(read(step)) for step in chain]

        settled = await asyncio.gather(*(read_chain(chain) for chain in groups), return_exceptions=True)
        readings: list[Assessment] = []
        for chain in settled:
            if isinstance(chain, BaseException):
                raise chain
            readings.extend(chain)
        return readings
