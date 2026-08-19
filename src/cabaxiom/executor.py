"""Executor strategies - HOW a Partition is run: Serial, the pooled Parallel (waves) and Pipeline (chains), and the event-loop Async (waves)."""
import asyncio
import inspect
from abc import ABC, abstractmethod
from collections.abc import Callable
from enum import Enum
from multiprocessing.dummy import Pool
from multiprocessing.pool import ThreadPool
from typing import final

from ._compat import override
from .cancellation import Cancellation, Cancelled
from .drift import Drift, DriftItem
from .ordering import Ordering
from .partition import Chains, Levels, Partition
from .step import Step


@final
class _Fan:
    """The shape a fanning executor fans into, composed onto it as `_shape`: how to turn an Ordering into a
    verified Partition, and why a flat Ordering is rejected. Two exist, dual to each other, built by the
    `waves()` factory for the level-fanners (Parallel, Async) and `chains()` for the chain-fanner (Pipeline).
    Serial fans nothing, composes no shape, and keeps the serial-safe default. The per-shape wording lives here
    because only the shape knows why its own fallback is wrong: a fanned flat wave ignores Step.after, a
    pipelined single chain runs nothing concurrently."""

    def __init__(self, into: type[Partition], via: str, needs: str, otherwise: str, use: str):
        self.__into = into      # the Partition subclass this shape builds: Levels or Chains
        self.__via = via        # the Ordering method that feeds it: "levels" or "chains"
        self.__needs = needs
        self.__otherwise = otherwise
        self.__use = use

    @classmethod
    def waves(cls) -> "_Fan":
        # The shape the level-fanners compose: independent topological waves, drawn from Kahn's levels.
        return cls(
            into=Levels, via="levels",
            needs="level-aware Ordering that splits steps into independent waves",
            otherwise="only yields a flat order from levels(), which fanned out would ignore Step.after",
            use="Kahn",
        )

    @classmethod
    def chains(cls) -> "_Fan":
        # The shape the chain-fanner composes: independent dependency chains, drawn from Components.
        return cls(
            into=Chains, via="chains",
            needs="chain-aware Ordering that splits steps into independent chains",
            otherwise="only yields one chain of everything from chains(), which pipelined would run nothing concurrently",
            use="Components",
        )

    def __call__(self, executor: str, ordering: Ordering, steps: tuple[Step, ...]) -> Partition:
        # An Ordering that does not override `via` only yields the flat fallback, so reject it as a class (the
        # unbound override check against the ABC names no concrete strategy) before running. Then build the
        # shape from the groups it produces and verify the placement upfront.
        if getattr(type(ordering), self.__via) is getattr(Ordering, self.__via):
            raise ValueError(
                f"{executor} needs a {self.__needs}, but {type(ordering).__name__} {self.__otherwise}. Use {self.__use}."
            )
        partition = self.__into(getattr(ordering, self.__via)(steps))
        partition.verify()
        return partition


class OnError(Enum):
    # What the Executor does when a step's apply() (or prune()) raises.
    FailFast = "FailFast"      # let it propagate and abort the run
    BestEffort = "BestEffort"  # catch it, record it as Drift, keep going with the rest of the run


class Executor(ABC):
    # Strategy for HOW a resolved set of steps is run. Serial walks them on one thread, Parallel fans each
    # level to a pool, Pipeline fans each independent chain. The Executor is the ONLY thing that invokes a
    # step, so it is the ONLY thing that can catch, which is why the OnError policy lives here. It checks the
    # injected cancellation before each unit of work and raises Cancelled if it fires.
    #
    # execute() returns TWO lists, kept apart on purpose: (returns, failures). `returns` is everything do()
    # itself handed back (converge's applied items, prune's surviving residue), `failures` is the exception
    # drift (empty under FailFast, which re-raises instead of collecting). Returning them apart lets converge
    # route its applied items to their own channel, and lets prune concatenate them since for a teardown both
    # are residual.

    _shape: _Fan | None = None   # the shape a subclass fans into (waves() or chains()); None means it fans nothing

    def arrange(self, ordering: Ordering, steps: tuple[Step, ...]) -> Partition:
        # The executor turns the injected Ordering into the Partition SHAPE it runs. A non-fanning executor
        # (Serial, no _shape) walks a serial-safe level partition (real waves from Kahn, the one-wave fallback
        # from DFS/Components) in order on one thread, honouring Step.after with no verification. A fanning one
        # delegates to its composed shape, which demands the Ordering it needs, builds the partition, and
        # verifies it upfront.
        if self._shape is None:
            return Levels(ordering.levels(steps))
        return self._shape(type(self).__name__, ordering, steps)

    @abstractmethod
    def execute(self, groups: tuple[tuple[Step, ...], ...], do: Callable[[Step], list[Drift] | None], cancellation: Cancellation) -> tuple[list[Drift], list[Drift]]:
        ...


@final
class Serial(Executor):
    """Default executor: every level in order, every step within a level in order, on one thread.
    FailFast (default) lets an apply() exception propagate."""

    def __init__(self, on_error: OnError = OnError.FailFast):
        self.__on_error = on_error

    @override
    def execute(self, levels: tuple[tuple[Step, ...], ...], do: Callable[[Step], list[Drift] | None], cancellation: Cancellation) -> tuple[list[Drift], list[Drift]]:
        returns: list[Drift] = []
        failures: list[Drift] = []
        for level in levels:
            for step in level:
                if cancellation.cancelled():
                    raise Cancelled.by(cancellation)
                try:
                    produced = do(step)
                except Cancelled:
                    raise   # an abort is a DECISION, so it cuts through the error policy entirely
                except Exception as exception:
                    if self.__on_error is OnError.FailFast:
                        raise
                    failures.append(DriftItem(Step.named(step), f"step failed: {type(exception).__name__}: {exception}"))
                else:
                    if produced:  # prune's residue (what survived), or converge's applied items - apply's no-op returns None
                        returns.extend(produced)
        return returns, failures


class _PooledExecutor(Executor, ABC):
    """Shared thread-pool plumbing for the two fanning executors: Parallel fans the steps within a level,
    Pipeline fans the independent chains. One Pool per instance (multiprocessing.dummy.Pool, the threaded
    twin of multiprocessing.Pool), created lazily on first run and reused across runs, released by close()
    or the context manager.

    Threads, not processes: a Step's apply() is almost always I/O (files, subprocesses, network) where the
    GIL is released and threads genuinely overlap, and Steps are ordinary live objects that need not pickle.
    The fence: this makes the fan I/O-parallel, not CPU-parallel. A domain whose steps grind pure-Python
    computation serializes on the GIL (until a free-threaded build changes that), and should inject its own
    Executor (a process pool needs picklable steps and a module-level do)."""

    def __init__(self, on_error: OnError = OnError.FailFast, *, width: int | None = None):
        # width is the pool size (None defaults to os.cpu_count()). on_error matches Serial.
        self._on_error = on_error  # protected: each subclass's execute() reads it
        self.__width = width
        self.__pool: ThreadPool | None = None

    def _ensure_pool(self) -> ThreadPool:
        # One pool per instance, created on first use and reused across execute() calls: a Fixpoint converge
        # calls execute() once per pass, so a fresh pool each pass would spin worker threads up and down
        # repeatedly. Closed by close() or the context manager, else finalised on garbage collection.
        if self.__pool is None:
            self.__pool = Pool(self.__width)
        return self.__pool

    def close(self) -> None:
        # Release the worker threads deterministically (close then join). A short-lived caller can skip this
        # and let the pool finalise on garbage collection, but a long-lived owner (a Controller looping for
        # hours) should close it, which is what the context-manager protocol below wraps.
        if self.__pool is not None:
            self.__pool.close()
            self.__pool.join()
            self.__pool = None

    def __enter__(self) -> "_PooledExecutor":
        return self

    def __exit__(self, *exception: object) -> None:
        self.close()


@final
class Parallel(_PooledExecutor):
    """Runs each topo LEVEL concurrently on the pool, with the levels themselves still walked in dependency
    order. The steps WITHIN one level are mutually independent by construction, so fanning them out is safe,
    and the barrier between levels preserves every Step.after edge. Composes the WAVES shape."""

    _shape = _Fan.waves()

    @override
    def execute(self, levels: tuple[tuple[Step, ...], ...], do: Callable[[Step], list[Drift] | None], cancellation: Cancellation) -> tuple[list[Drift], list[Drift]]:
        # attempt() ALWAYS catches, even under FailFast, so an apply() blowing up in a worker thread surfaces
        # back on THIS thread as a clean value rather than a stray cross-thread exception, and carries back the
        # step's own return. The level is a barrier: every step in it runs to completion before we inspect
        # outcomes, so under FailFast we re-raise the first failure only after the level finishes.
        def attempt(_step: Step) -> tuple[Step, list[Drift] | None, Exception | Cancelled | None]:
            # BOTH clauses catch, and the first one is not redundant. A Cancelled is an Exception today, so
            # `except Exception` would take it - but it is about to stop being one, and a BaseException loose
            # in a pool worker does not propagate, it hangs the map. Catching the abort BY NAME here is what
            # lets the re-parent land without this boundary noticing.
            try:
                return _step, do(_step), None
            except Cancelled as _abort:
                return _step, None, _abort
            except Exception as _exception:
                return _step, None, _exception

        returns: list[Drift] = []
        failures: list[Drift] = []
        pool = self._ensure_pool()
        for level in levels:
            if cancellation.cancelled():
                raise Cancelled.by(cancellation)
            # pool.map preserves input order, so `returns` builds in resolved step order on THIS thread.
            for step, produced, exception in pool.map(attempt, level):
                if exception is not None:
                    if isinstance(exception, Cancelled):
                        raise exception   # a decision, never a failure - it cuts through BestEffort
                    if self._on_error is OnError.FailFast:
                        raise exception
                    failures.append(DriftItem(Step.named(step), f"step failed: {type(exception).__name__}: {exception}"))
                elif produced:  # prune's residue (what survived), or converge's applied items - apply's no-op returns None
                    returns.extend(produced)
        return returns, failures


@final
class Pipeline(_PooledExecutor):
    """The dual of Parallel: runs each independent CHAIN concurrently on the pool, the steps WITHIN a chain
    in series. Parallel fans the steps inside a level and bars between levels, Pipeline fans the chains and
    serialises inside each. Correct only when the chains share no Step.after edge, which the Reconciler proves
    upfront via the partition's verify(), so a chain never waits on another and needs no barrier. Composes the
    CHAINS shape."""

    _shape = _Fan.chains()

    @override
    def execute(self, chains: tuple[tuple[Step, ...], ...], do: Callable[[Step], list[Drift] | None], cancellation: Cancellation) -> tuple[list[Drift], list[Drift]]:
        # run_chain walks ONE chain in series on a worker thread, checking cancellation between its steps (a
        # chain can be long, unlike a level's single fan). It ALWAYS catches, like Parallel's attempt(): a step
        # blowing up, or a cancellation firing, comes back as a clean value on THIS thread. pool.map is a
        # barrier over the chains and preserves their order, so returns build in resolved order and the FIRST
        # chain (in order) that failed or cancelled is the one re-raised.
        def run_chain(chain: tuple[Step, ...]) -> tuple[list[Drift], list[Drift], Exception | None]:
            produced_all: list[Drift] = []
            failures_all: list[Drift] = []
            for step in chain:
                if cancellation.cancelled():
                    return produced_all, failures_all, Cancelled.by(cancellation)
                try:
                    produced = do(step)
                except Cancelled as abort:
                    # The chain stops and hands the abort back the same way the between-steps check does,
                    # under EITHER policy. A decision is not a failure, so BestEffort has no say in it.
                    return produced_all, failures_all, abort
                except Exception as exception:
                    if self._on_error is OnError.FailFast:
                        return produced_all, failures_all, exception
                    failures_all.append(DriftItem(Step.named(step), f"step failed: {type(exception).__name__}: {exception}"))
                else:
                    if produced:  # prune's residue, or converge's applied items - apply's no-op returns None
                        produced_all.extend(produced)
            return produced_all, failures_all, None

        returns: list[Drift] = []
        failures: list[Drift] = []
        pool = self._ensure_pool()
        for chain_returns, chain_failures, error in pool.map(run_chain, chains):
            if error is not None:
                raise error   # a Cancelled (under any on_error), or under FailFast the chain's first failure
            returns.extend(chain_returns)
            failures.extend(chain_failures)
        return returns, failures


@final
class Async(Executor):
    """Runs each dependency wave on an asyncio event loop instead of a thread pool, the cooperative dual of
    Parallel, for steps whose apply() is a coroutine that closes its gap over I/O (a network call, a socket, a
    subprocess awaited without blocking). It awaits a wave's coroutines concurrently and bars between waves, so
    every Step.after edge holds, composing the same WAVES shape as Parallel.

    A step method may be a coroutine (awaited) or a plain sync call (run inline, so a sync apply() still works,
    it just does not overlap). converge() stays synchronous: Async drives a fresh event loop per pass with
    asyncio.run, so call it from sync code, not from inside an already-running loop. Like every executor it
    fans only the write phase (apply, prune), the drift re-probe stays a serial read."""

    _shape = _Fan.waves()

    def __init__(self, on_error: OnError = OnError.FailFast):
        self.__on_error = on_error

    @override
    def execute(self, levels: tuple[tuple[Step, ...], ...], do: Callable[[Step], list[Drift] | None], cancellation: Cancellation) -> tuple[list[Drift], list[Drift]]:
        # converge() is sync, so drive the whole wave walk on a fresh loop and hand back plain lists.
        return asyncio.run(self.__walk(levels, do, cancellation))

    async def __walk(self, levels: tuple[tuple[Step, ...], ...], do: Callable[[Step], list[Drift] | None], cancellation: Cancellation) -> tuple[list[Drift], list[Drift]]:
        # attempt() ALWAYS catches, even under FailFast, so a coroutine blowing up comes back as a clean value
        # rather than cancelling its wave-mates mid-flight, and carries the step's own return. A sync do() is
        # used as-is, an awaitable one is awaited. gather preserves input order, so returns build in resolved
        # step order, and the wave is a barrier: every coroutine settles before we inspect, so under FailFast
        # the first failure (in order) is re-raised only after the whole wave has finished.
        async def attempt(step: Step) -> tuple[Step, list[Drift] | None, Exception | Cancelled | None]:
            # Caught by name for the reason the thread pool catches it by name, one boundary over.
            try:
                outcome = do(step)
                if inspect.isawaitable(outcome):
                    outcome = await outcome
                return step, outcome, None
            except Cancelled as abort:
                return step, None, abort
            except Exception as exception:
                return step, None, exception

        returns: list[Drift] = []
        failures: list[Drift] = []
        for level in levels:
            if cancellation.cancelled():
                raise Cancelled.by(cancellation)
            for step, produced, exception in await asyncio.gather(*(attempt(step) for step in level)):
                if exception is not None:
                    if isinstance(exception, Cancelled):
                        raise exception   # a decision, never a failure - it cuts through BestEffort
                    if self.__on_error is OnError.FailFast:
                        raise exception
                    failures.append(DriftItem(Step.named(step), f"step failed: {type(exception).__name__}: {exception}"))
                elif produced:  # prune's residue, or converge's applied items - apply's no-op returns None
                    returns.extend(produced)
        return returns, failures
