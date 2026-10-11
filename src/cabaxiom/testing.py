"""The doubles the kernel's own suite grew, published with a compatibility promise - a scripted Staged, a
settling Fixable, a RecordingBackoff that keeps the pauses it never takes and a Recording that keeps every
Observer hook as data.

A double only the kernel may use is a double every consumer writes again, slightly differently and gets
subtly wrong. These four are the shapes the suite converged on after writing them a dozen times over, so a
domain testing its own Steps, its own pacing or its own Observer starts from the fakes the kernel proves
itself with instead of from a private copy that drifts away from the contract.

They are doubles, so they are honest about BEING doubles. Nothing here answers outside the contract the
real citizen answers inside. A read hands back an Assessment paired with its artifacts, a write its changes
paired the same way, a Backoff a float and every hook takes exactly what Observer declares, so a step
written against these fakes meets the same kernel afterwards. A double that lies in a way the real contract
forbids teaches a test to pass against a kernel that would break, which is worse than having no double at
all. That is the same reason Staged refuses a read past its script and Recording refuses a hook name
Observer does not have. Answering anyway would be answering something nobody declared, where a green test
built on an invented answer proves nothing.

The doubles carry state and are single-use, like the worlds they model. Build a fresh one per test.
"""
from collections.abc import Sequence
from typing import ClassVar, final, override

from .cancellation import Fault
from .convergence import Backoff, Fixed
from .drift import Artifacts, Assessment, Changes, Drift, DriftItem, FlowAssessment, FlowOutcome
from .observer import Observer
from .step import Step

__all__ = ["Staged", "Fixable", "RecordingBackoff", "Firing", "Recording"]


class Staged(Step):
    """A step that answers a SCRIPTED sequence of drift readings, one per read, so a test can declare a
    world that CHANGES under the run rather than build a step that models the change.

    The steps a converge loop is hard to test against are the ones whose drift clears for reasons the run
    did not cause - a rollout finishing, a cache expiring, a queue draining. Modelling that with a counter
    and a condition puts the world's behaviour inside the double, where every test that needs a different
    world writes a slightly different double. Staged puts it in the ARGUMENT instead - hand it the exact
    readings the run should meet, in order, while the world is the literal a reader can see.

    apply() is left as Step's no-op on purpose. The script advances on the READ, never on the write, which
    is what makes this the double for external settling. The world moves whether or not this run touched
    it. For a world that only moves because the run applied to it, reach for Fixable.

    What it refuses - a read past the end of the script. Repeating the last reading would silently extend a
    world the author never wrote. Answering clean would hand the run a convergence nobody declared -
    either way a test passes on an invented reading. Instead the read raises AssertionError naming the
    script length and the read that ran past it, because an exhausted script is a fact about the TEST (the
    run took more passes than the author expected) and AssertionError is the failure a test framework
    already knows how to report. It surfaces. The kernel's read is single-try and sits under no OnError
    policy, so a refusal propagates out of converge() instead of settling into a residual.

    Each scripted reading fills the Assessment's DEVIATION channel, the one converge() re-probes for its
    proof. The other three channels stay empty, so a lifecycle test spends exactly the readings it means to.
    """

    def __init__(self, *readings: Sequence[Drift]) -> None:
        if not readings:
            raise ValueError("Staged needs at least one reading - an empty script is ill-defined")
        # Snapshotted to tuples at construction, both levels. The script is the DECLARED world, so a caller
        # that keeps a handle on the list it passed must not be able to rewrite the readings a later pass
        # will meet, which would make a failing run unreproducible from its own source.
        self.__script = tuple(tuple(reading) for reading in readings)
        # A mutable cell, not a plain int. A Step is frozen after __init__, so the double cannot reassign
        # an attribute to advance its cursor. Mutating a held list is the sanctioned way a double carries
        # the fake world it models, the same shape Vault's `open` flags use.
        self.__answered = [0]

    @property
    def script(self) -> tuple[tuple[Drift, ...], ...]:
        # The declared world, as handed in. Readable so a test can assert against the script it wrote
        # instead of repeating the literal.
        return self.__script

    @property
    def answered(self) -> int:
        # How many readings the run has taken so far. The cheapest way to assert how many times a
        # convergence policy actually re-probed, which is otherwise only visible through the residual.
        return self.__answered[0]

    @override
    def assess(self, inputs: Artifacts) -> FlowAssessment:
        if self.__answered[0] == len(self.__script):
            raise AssertionError(
                f"Staged was scripted with {len(self.__script)} readings and this run asked for reading "
                f"{self.__answered[0] + 1}. The script IS the declared world, so a read past its end has no "
                f"honest answer. Repeating the last reading or inventing a clean one would let the test "
                f"pass against a world nobody wrote. Script the readings this run really takes or drive "
                f"it with a convergence that stops sooner."
            )
        answer = self.__script[self.__answered[0]]
        self.__answered[0] += 1
        return Assessment(deviation=answer), {}


class Fixable(Step):
    """A step that stays out of desired state until apply() has run `applies` times, then settles and
    stays settled. The double every retry, convergence, idempotence and isolation test needs.

    This is the ordinary world. Something is wrong, the run fixes it and the re-probe proves it. One
    apply is the common case and the default, so Fixable() is the plain fixable step. More than one is the
    multi-pass world Fixpoint exists for, where a pass clears what it can and the next clears what the
    first unblocked. Once settled it is IDEMPOTENT in the way the kernel's proofs demand. drift() reads
    clean and apply() is a no-op returning None, so Idempotence.prove() sees no churn on the second run.

    Four knobs, because those are exactly the four axes the private copies across the suite differed on.
    `applies` is how many apply() calls it takes to settle. `name` is the drift item's subject, worth
    setting when two of these share a run, since DriftItem is a value and two unnamed ones are equal.
    `reports` makes each productive apply() hand back what it changed, so the run's applied channel is
    non-empty. `raising` makes each apply() that does NOT settle it raise that exception instead of quietly
    leaving the drift, which is the flaky write a Retry test is about.

    The raise count follows from `applies` rather than being its own number. `applies` always counts the
    calls it takes to settle, so Fixable(3, raising=...) raises on the first two and settles on the third,
    and Fixable(raising=...) settles at once and never raises at all. One counter, one meaning, whichever
    way the step fails.

    What it refuses - `applies` under 1. A step that is already in desired state is Step() itself and
    accepting 0 here would mean a double that never drifts, never applies and quietly proves nothing.
    """

    def __init__(self, applies: int = 1, *, name: str = "fixable", reports: bool = False,
                 raising: Exception | None = None) -> None:
        if applies < 1:
            raise ValueError(f"Fixable applies must be >= 1, got {applies}")
        self.__applies = applies
        self.__name = name
        self.__reports = reports
        self.__raising = raising
        # A mutable cell for the same reason Staged uses one. The freeze forbids reassigning an attribute,
        # so the try counter lives in a held list the double mutates in place.
        self.__tries = [0]

    @property
    def tries(self) -> int:
        # apply() calls made so far, the failed ones included. What a retry test asserts on - the budget
        # was spent, exactly this many times.
        return self.__tries[0]

    @property
    def remaining(self) -> int:
        # applies still owed before it settles. Floors at 0 rather than going negative, so a step applied
        # after it settled still reads as settled instead of drifting backwards.
        return max(self.__applies - self.__tries[0], 0)

    @property
    def settled(self) -> bool:
        return not self.remaining

    @override
    def assess(self, inputs: Artifacts) -> FlowAssessment:
        deviation: Changes = [] if self.settled else [DriftItem(self.__name, f"{self.remaining} left")]
        return Assessment(deviation=deviation or ()), {}

    @override
    def apply(self, inputs: Artifacts) -> FlowOutcome:
        # A settled step's apply is the no-op the whole kernel is built on and it must not spend a try.
        # counting one here would make every extra pass look like work and turn an idempotent double into
        # the churner the isolation hunt goes looking for.
        if self.settled:
            return None, {}
        self.__tries[0] += 1
        # The raise is asked AFTER the try is counted and only while the step is still unsettled, so the
        # attempt is spent (a Retry sees its budget go down) and the last one, the one that settles, always
        # gets through. A raise on the settling try would be a step that never settles, which is a
        # different double entirely.
        if self.__raising is not None and not self.settled:
            raise self.__raising
        produced: Changes = [DriftItem(self.__name, f"applied, {self.remaining} left")] if self.__reports else None
        return produced, {}


@final
class RecordingBackoff(Backoff):
    """A Backoff that captures the pauses it was ASKED for instead of taking them, so a pacing test asserts
    the whole schedule without sleeping through it.

    A pacing policy is the one axis whose correctness is a sequence of NUMBERS. The only ways to see
    those numbers were to patch time.sleep in whichever module happened to own the sleep or to sit through
    the real pauses. Patching pins a test to the kernel's internal call site. Sitting through them makes an
    exponential schedule take minutes. This wraps the policy under test, records what it said and answers
    0.0 to whoever is driving, so the schedule is a value to assert on and nothing waits for it.

    The wrapped policy is optional. Given one, `pauses` is the schedule that policy asked for and the test
    reads it back. Given none it wraps Fixed(0.0), which is the earlier and narrower use - `stalls` alone,
    for asserting that a stall streak was counted and reset correctly, where the pause length was never the
    point.

    Answering 0.0 rather than the wrapped delay is what makes the promise structural. Fixpoint does not
    call wait() - it YIELDS delay() to whichever reconciler drives it, where that reconciler sleeps on the
    number it gets back - so a recorder that returned the real delay would record the pause and then have
    the driver take it anyway. wait() is overridden for the same reason on the path that does call it (a
    sync Retry), recording through delay() and returning without a sleep of any length.
    """

    def __init__(self, backoff: Backoff | None = None) -> None:
        self.__backoff = backoff if backoff is not None else Fixed(0.0)
        self.__stalls: list[int] = []
        self.__pauses: list[float] = []

    @property
    def stalls(self) -> tuple[int, ...]:
        # The consecutive-stall counts this was paced with, in order. Fixpoint and Retry speak the same
        # stall vocabulary, so one recorder reads either.
        return tuple(self.__stalls)

    @property
    def pauses(self) -> tuple[float, ...]:
        # What the wrapped policy asked for at each of those stalls, in the same order. The schedule.
        return tuple(self.__pauses)

    @override
    def delay(self, stalled: int) -> float:
        self.__stalls.append(stalled)
        self.__pauses.append(self.__backoff.delay(stalled))
        return 0.0

    @override
    def wait(self, stalled: int) -> None:
        # Record and return. Deliberately NOT Backoff.wait's time.sleep(self.delay(stalled)). Sleeping zero
        # would be harmless today and a lie the day this class is asked to answer a real number.
        self.delay(stalled)


@final
class Firing:
    """One Observer hook call captured as data. Which hook fired and the arguments it carried.

    A RECORD, the way Pass is. The arguments are held as a tuple and read through properties, so a later
    firing cannot rewrite an earlier one and a reader cannot falsify the trace in place. The arguments stay
    positional and untyped because the six hooks carry six different payloads, so flattening them into
    named channels would leave four of five empty on every firing. What each position holds is Observer's
    own signature, unchanged.
    """
    __slots__ = ("__hook", "__arguments")

    def __init__(self, hook: str, *arguments: object) -> None:
        self.__hook = hook
        self.__arguments = arguments

    @property
    def hook(self) -> str:
        return self.__hook

    @property
    def arguments(self) -> tuple[object, ...]:
        return self.__arguments

    def __repr__(self) -> str:
        # The arguments are appended one by one rather than joined, so a no-argument hook reads as
        # Firing('began') instead of trailing the empty join's comma.
        carried = "".join(f", {argument!r}" for argument in self.arguments)
        return f"Firing({self.hook!r}{carried})"


@final
class Recording(Observer):
    """An Observer that keeps EVERY hook it was fired with as data, readable after the run.

    Journal records the run's PASSES, which is the shape an operator wants. This records the TRACE, which
    is the shape a test wants - one ordered log of every hook, with the arguments each carried, so a test
    asserts what fired, in what order and with what. That covers the unit hooks Journal does not touch at
    all (stepped, retried) and the teardown (pruned), which is why the suite kept growing a second private
    observer beside its Journal assertions.

    It is an Observer like any other, so it nests under Chorus and can watch a run that is also being
    journalled or logged. The sequence channels are snapshotted to tuples on the way in, exactly as Pass
    does, so a recorded firing keeps what it was handed even though the reconciler reuses its own lists
    between passes - a trace that mutates behind the reader is not a trace.

    What it refuses - fired() with a name Observer does not declare. That answer would otherwise be an empty
    tuple forever, so an assertion that nothing fired is exactly the assertion a typo makes true.
    """

    # Observer's six hooks, in the order the class declares them. Named once here because fired() is a
    # lookup by string and a string lookup with no vocabulary behind it cannot tell a miss from a typo.
    __hooks: ClassVar[tuple[str, ...]] = ("began", "acted", "remained", "stepped", "retried", "pruned")

    def __init__(self) -> None:
        self.__firings: list[Firing] = []

    @property
    def firings(self) -> tuple[Firing, ...]:
        # Every hook call, in the order it fired. A tuple, so the trace is read and never edited.
        return tuple(self.__firings)

    @property
    def hooks(self) -> tuple[str, ...]:
        # Just the names, in firing order. The one assertion nearly every observer test opens with, so it
        # does not have to be spelled out of firings each time.
        return tuple(firing.hook for firing in self.__firings)

    def fired(self, hook: str) -> tuple[Firing, ...]:
        # Every firing of ONE hook, in order. The per-hook view, so asserting on the third stepped() does
        # not mean counting past the pass hooks that fired between them.
        if hook not in self.__hooks:
            raise ValueError(
                f"Observer declares no {hook!r} hook, so a Recording asked for one would answer an empty "
                f"tuple forever - which is exactly what an assertion that nothing fired wants to hear. "
                f"The hooks are {', '.join(self.__hooks)}."
            )
        return tuple(firing for firing in self.__firings if firing.hook == hook)

    def __record(self, hook: str, *arguments: object) -> None:
        self.__firings.append(Firing(hook, *arguments))

    @override
    def began(self) -> None:
        self.__record("began")

    @override
    def acted(self, applied: Sequence[Drift]) -> None:
        self.__record("acted", tuple(applied))

    @override
    def remained(self, residual: Sequence[Drift]) -> None:
        self.__record("remained", tuple(residual))

    @override
    def stepped(self, step: Step, changes: Changes, error: Fault | None) -> None:
        # None is the no-op write and means something different from an empty report, so it is kept as
        # None rather than flattened into an empty tuple.
        self.__record("stepped", step, None if changes is None else tuple(changes), error)

    @override
    def retried(self, step: Step, attempt: int, error: Exception) -> None:
        self.__record("retried", step, attempt, error)

    @override
    def pruned(self, residual: Sequence[Drift]) -> None:
        self.__record("pruned", tuple(residual))

