"""Observer - optional trace hooks fired around each converge pass, composed via Chorus, recorded as data by
Journal and Timing, emitted to the host's logs by Logging."""
import logging
import time
from collections.abc import Mapping, Sequence
from threading import Lock
from typing import final, override

from .cancellation import Fault
from .drift import Changes, Drift
from .step import Step


class Observer:
    """Trace hooks fired around a run. Subclass and override only the hooks you need, the rest stay
    no-ops, so a reconciler with the default observer behaves byte-for-byte as one with none. It is
    deliberately not abstract for that reason. Trace what was acted on and what the world still shows,
    without instrumenting a single Step by hand.

    Two granularities. The PASS hooks (began / acted / remained / pruned) fire from the reconciler on the
    calling thread or coroutine, after the dispatcher has collected its results. The UNIT hooks (stepped /
    retried) fire live, as each unit of work settles, which is what makes a 40-step converge watchable
    while it runs - and they fire where the run RECORDS. On the caller's event loop under every shipped
    dispatcher (even ThreadDispatcher only runs the hook itself on a worker thread - the Ledger still
    records on the loop) and inside the retrying coroutine for retried. A custom dispatcher that records
    from its own worker threads is the one that needs a thread-safe observer.
    """

    def began(self) -> None:
        # A converge pass is about to apply its steps.
        ...

    def acted(self, applied: Sequence[Drift]) -> None:
        # What this pass's apply() changed, in resolved order. A Sequence on purpose. The reconciler hands
        # a tuple, because a trace must not be able to rewrite what it traces - the residual is the run's
        # PROOF. The annotation used to say list, which invited exactly the mutation the kernel discards.
        ...

    def remained(self, residual: Sequence[Drift]) -> None:
        # The drift the re-probe still finds after the pass, what remained between the world and desired.
        # Handed as a tuple, like acted - a reader, never an editor.
        ...

    def dispatching(self, step: Step, inputs: Mapping[str, object]) -> None:
        # ONE unit of work is about to run. The step plus the payload the run mounted for it - fired as
        # the wave fans, per admitted step, before the write starts. BOTH PHASES fire it. The read side
        # announces each assess the same way, so a trace of a plain assess() is not a blank page. The START moment stepped never was,
        # which is what lets an observer pair the two into a real per-step duration under ANY dispatcher.
        # WAVE-GRANULAR by nature. It fires when the wave admits the step, so under a fanning dispatcher
        # the write may still queue behind its wave-mates for a moment. The payload arrives as a read-only
        # view of the very mapping the step will be handed - a trace must not be able to rewrite what the
        # run is about to read.
        ...

    def stepped(self, step: Step, changes: Changes, error: Fault | None) -> None:
        # ONE unit of work settled - the step that ran, what its write handed back (None for a no-op) and
        # the exception it raised (None when it ran clean) - fired even for a failure FailFast is about to
        # re-raise, so the last thing a run traced is the thing that killed it. The channel admits the
        # ferried Cancelled for the same reason. The hook fires BEFORE the rule re-raises an abort, so the
        # abort is the last thing the run traced too. A blocked step never fires this. It did not run and
        # its `step blocked` drift already records why.
        ...

    def produced(self, step: Step, artifacts: Mapping[str, object]) -> None:
        # ONE clean unit's artifacts, as the run records them - the lineage seam. Which producer produced
        # what, the attribution assemble() deliberately merges away for its consumers. Fired beside
        # stepped for every CLEAN step, the empty mapping included (producing nothing is information),
        # never for a failure (a failed write has no artifacts to attribute). The READ side deliberately does NOT
        # fire it, though a probe also produces artifacts. A re-probe runs after every converge, so its
        # (usually empty) reading would land last and overwrite the WRITE's attribution in any collector
        # keyed by step. Lineage is about what a run CHANGED, so this hook stays the write's alone. A read-only view, for the
        # same reason every hook gets one. The Ledger stores this very dict for the step's dependents to
        # read, so a trace that could write through it would corrupt the run's own data-flow.
        ...

    def retried(self, step: Step, attempt: int, error: Exception) -> None:
        # A write attempt failed and the retry is about to spend another. The step, how many attempts have
        # failed so far plus the failure. Fired before the backoff pause, so a stalled run traces WHY it
        # is waiting. Never fired for a Cancelled (an abort cuts through without spending attempts) or a
        # failure the retry's retryable declined (it propagates at once).
        ...

    def pruned(self, residual: Sequence[Drift]) -> None:
        # A teardown finished - what survived it (empty == everything gone), failures included. The teardown
        # twin of remained, so a Journal-style observer can record prune runs too. A tuple, like the rest.
        ...


@final
class Chorus(Observer):
    """An Observer that relays each hook to several observers in order. This is the composition seam,
    the way Quorum composes cancellations, so one run can trace to a log and a metrics sink at once. A
    Chorus is itself an Observer, so it nests."""

    def __init__(self, *observers: Observer):
        self.__observers = observers

    @override
    def began(self) -> None:
        for observer in self.__observers:
            observer.began()

    @override
    def acted(self, applied: Sequence[Drift]) -> None:
        for observer in self.__observers:
            observer.acted(applied)

    @override
    def remained(self, residual: Sequence[Drift]) -> None:
        for observer in self.__observers:
            observer.remained(residual)

    @override
    def dispatching(self, step: Step, inputs: Mapping[str, object]) -> None:
        for observer in self.__observers:
            observer.dispatching(step, inputs)

    @override
    def stepped(self, step: Step, changes: Changes, error: Fault | None) -> None:
        for observer in self.__observers:
            observer.stepped(step, changes, error)

    @override
    def produced(self, step: Step, artifacts: Mapping[str, object]) -> None:
        for observer in self.__observers:
            observer.produced(step, artifacts)

    @override
    def retried(self, step: Step, attempt: int, error: Exception) -> None:
        for observer in self.__observers:
            observer.retried(step, attempt, error)

    @override
    def pruned(self, residual: Sequence[Drift]) -> None:
        for observer in self.__observers:
            observer.pruned(residual)


@final
class Pass:
    """One converge pass captured as data. What its apply() changed and the residual the re-probe then
    found. A RECORD. Both channels are captured as tuples behind read-only properties, so a later pass
    cannot mutate a recorded one and a reader cannot falsify the record in place."""
    __slots__ = ("__applied", "__residual")

    def __init__(self, applied: Sequence[Drift], residual: Sequence[Drift]):
        self.__applied = tuple(applied)
        self.__residual = tuple(residual)

    @property
    def applied(self) -> tuple[Drift, ...]:
        return self.__applied

    @property
    def residual(self) -> tuple[Drift, ...]:
        return self.__residual

    def __repr__(self) -> str:
        return f"Pass(applied={self.applied!r}, residual={self.residual!r})"


@final
class Journal(Observer):
    """An Observer that records every converge pass as data, so a whole run can be inspected or asserted
    after the fact instead of through side-effecting log lines - the run becomes a value. Each pass's
    apply() changes and the residual that followed are paired into a Pass, appended to `passes` in order.
    It is an Observer like any other, so it composes under Chorus. A run can journal and log at once."""

    def __init__(self) -> None:
        self.__passes: list[Pass] = []
        self.__applied: list[Drift] = []

    @property
    def passes(self) -> tuple[Pass, ...]:
        # The recorded run, in pass order. A tuple, so a caller reads the record without mutating it.
        return tuple(self.__passes)

    @override
    def acted(self, applied: Sequence[Drift]) -> None:
        # acted always precedes remained within a pass, so this buffers what changed until remained closes it.
        self.__applied = list(applied)

    @override
    def remained(self, residual: Sequence[Drift]) -> None:
        # remained closes the pass. Pair what was applied with what still remained, then record it. Pass
        # snapshots its channels itself, so no defensive copy is owed here.
        self.__passes.append(Pass(self.__applied, residual))


@final
class Logging(Observer):
    """An Observer that emits every hook to the standard library logging module under its own logger name, so
    a long converge shows up wherever the host application's logs already go. It adds no dependency, because
    logging IS the standard library, so the kernel keeps its promise of depending on nothing.

    It CONFIGURES nothing - no basicConfig, no handler, no level. Those belong to the application, where a
    library that installs a handler into its host's logging tree has decided formatting, destination and
    verbosity for a program it does not own - the reason people rip such a library out. The standard library
    already answers the silence question, since a logger nobody configured emits nothing, so this stays quiet
    until the host wires a handler for `cabaxiom` or one of its parents. Then it speaks in exactly the
    shape the host chose. Pass a name to sit somewhere else in the host's tree or a ready Logger to hand it
    the one the host already built.

    COUNTS, not contents. The pass hooks report how much moved rather than the drift items themselves,
    because a log line is for NOTICING and a residual can be long. Journal beside it under a Chorus keeps
    what moved, as data an assertion can read. Levels are picked for the person reading the log. The pass
    hooks at INFO, the per-unit trace at DEBUG (one line per step, which a 40-step converge makes 40 of) and
    the two failure channels at WARNING, because a failure logged at DEBUG is a failure nobody sees."""

    def __init__(self, logger: logging.Logger | str = "cabaxiom"):
        # A NAME is resolved through getLogger, so two Logging observers under one name are one logger and
        # the host configures it by that name. A ready Logger is taken as handed, for an application that
        # already has its own tree and wants the kernel inside it rather than beside it.
        self.__logger = logging.getLogger(logger) if isinstance(logger, str) else logger

    @override
    def began(self) -> None:
        # Every emit below hands logging its arguments UNFORMATTED, the module's own %-style deferral. The
        # string gets built only if a handler is going to take it, so an unconfigured Logging costs a level
        # check per hook instead of a formatted line per step. An f-string would pay that formatting on every
        # hook of every pass and then throw it away, which is the cost that makes people turn tracing off.
        self.__logger.info("converge pass began")

    @override
    def acted(self, applied: Sequence[Drift]) -> None:
        self.__logger.info("pass applied %d change(s)", len(applied))

    @override
    def remained(self, residual: Sequence[Drift]) -> None:
        self.__logger.info("pass left %d residual item(s)", len(residual))

    @override
    def stepped(self, step: Step, changes: Changes, error: Fault | None) -> None:
        # A step is named by its TYPE here, the same form the Ledger writes into failure drift. The numbered
        # per-instance label needs the whole run to tally duplicates, which a hook firing live does not have.
        # The failure branch is WARNING for the same reason the hook fires at all. The last thing a dying run
        # traced must be readable at the level an operator actually watches.
        if error is not None:
            self.__logger.warning("%s failed: %s: %s", Step.named(step), error.__class__.__name__, error)
        else:
            self.__logger.debug("%s settled with %d change(s)", Step.named(step), len(changes or ()))

    @override
    def retried(self, step: Step, attempt: int, error: Exception) -> None:
        # Fired before the backoff pause, so this line is what explains a run that appears to be doing nothing.
        self.__logger.warning("%s attempt %d failed, retrying: %s: %s", Step.named(step), attempt, error.__class__.__name__, error)

    @override
    def pruned(self, residual: Sequence[Drift]) -> None:
        self.__logger.info("teardown left %d survivor(s)", len(residual))


@final
class Stamp:
    """One unit of work settling, timed. The step and HOW LONG AFTER its pass began it settled. A record like
    Pass, read-only, so a reader cannot re-date a measurement after the run.

    A MOMENT, not a duration. That distinction is the honest one for THIS record. The hooks do expose
    a start now - dispatching fires as the wave fans - so a duration IS a number an observer can measure by
    pairing dispatching with stepped, wave-granularity understood. Timing deliberately keeps the settle
    moment alone. Under a serial walk the successive differences between stamps ARE the step durations,
    under a fanning dispatcher they are not, so this record refuses to blur the two. An observer that
    wants real durations pairs the two hooks itself and owns the wave-granularity caveat."""
    __slots__ = ("__step", "__at")

    def __init__(self, step: Step, at: float):
        self.__step = step
        self.__at = at

    @property
    def step(self) -> Step:
        return self.__step

    @property
    def at(self) -> float:
        return self.__at

    def __repr__(self) -> str:
        return f"Stamp({Step.named(self.step)}, at={self.at!r})"


@final
class Span:
    """One converge pass timed. How long the pass took and when each of its units settled. The timing twin of
    Pass and a RECORD the same way - the stamps are captured as a tuple behind read-only properties, so a
    later pass cannot rewrite a measured one and a reader cannot falsify a number in place.

    `elapsed` is measured from began to remained, so it covers the WHOLE cycle. The apply and the re-probe
    that verifies it, which together are the honest cost of one converge pass. The wait a Convergence takes
    between passes falls outside it, because no hook opens that wait."""
    __slots__ = ("__elapsed", "__stamps")

    def __init__(self, elapsed: float, stamps: Sequence[Stamp]):
        self.__elapsed = elapsed
        self.__stamps = tuple(stamps)

    @property
    def elapsed(self) -> float:
        return self.__elapsed

    @property
    def stamps(self) -> tuple[Stamp, ...]:
        return self.__stamps

    def __repr__(self) -> str:
        return f"Span(elapsed={self.elapsed!r}, stamps={self.stamps!r})"


@final
class Timing(Observer):
    """An Observer that TIMES a run and hands the numbers back as a value, the way Journal hands back passes.
    A measurement that only prints is a measurement nobody can assert on, so this one keeps it. Each converge
    pass closes into a Span in `passes`, with every unit that settled inside that pass becoming a Stamp within it.
    Compose it under a Chorus with Journal to have what a pass did and what it cost side by side or with
    Logging to watch a run live and measure it after.

    The clock is perf_counter. It is monotonic, so a system clock stepped backwards mid-run (an NTP
    correction is the ordinary case) cannot make a pass come out negative. It is the finest resolution
    the platform offers, which matters because the steps worth measuring are the ones that settle in
    microseconds. time.time() answers a different question - what o'clock it is - with a number somebody
    else is allowed to move.

    A teardown is NOT timed. prune() fires pruned but never began, so a teardown has no start the hooks
    expose, so a unit settling with no pass open is left unrecorded rather than measured from an invented
    origin. The same rule covers any hook arriving outside a pass.

    Locked, because the unit hook fires wherever a dispatcher records. Every shipped dispatcher records on
    the event loop, yet a custom one recording from its own worker threads would stamp into one list while
    the calling thread closes the pass around them."""

    def __init__(self) -> None:
        self.__passes: list[Span] = []
        self.__stamps: list[Stamp] = []
        self.__began: float | None = None   # the open pass's origin, None between passes and outside them
        self.__lock = Lock()

    @property
    def passes(self) -> tuple[Span, ...]:
        # The timed run, in pass order, named as Journal names its own so one reading habit serves both.
        with self.__lock:
            return tuple(self.__passes)

    @property
    def elapsed(self) -> float:
        # Time spent INSIDE passes, which is not wall clock for the run. The wait a Convergence takes between
        # passes belongs to the pacing policy and no hook opens it, so this record does not claim it. Summed
        # from a float zero, so an untimed run answers 0.0 rather than an int the duration channel never uses.
        return sum((span.elapsed for span in self.passes), 0.0)

    @override
    def began(self) -> None:
        with self.__lock:
            self.__began = time.perf_counter()
            self.__stamps = []

    @override
    def stepped(self, step: Step, changes: Changes, error: Fault | None) -> None:
        # Read the clock BEFORE taking the lock, so a worker queued behind another thread's stamp does not
        # charge its own waiting to the step it is about to record. Failures are stamped like successes. A
        # step that took 30 seconds to fail is exactly the measurement somebody is looking for.
        at = time.perf_counter()
        with self.__lock:
            if self.__began is not None:
                self.__stamps.append(Stamp(step, at - self.__began))

    @override
    def remained(self, residual: Sequence[Drift]) -> None:
        # remained closes the pass, the same boundary that closes a Journal's. It closes the whole cycle
        # rather than the apply alone - acted would stop the clock before the re-probe that proves the pass.
        at = time.perf_counter()
        with self.__lock:
            if self.__began is not None:
                self.__passes.append(Span(at - self.__began, self.__stamps))
                self.__began = None

