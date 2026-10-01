"""The run's two CUT-THROUGH exceptions plus the cancellation strategies that raise one of them.
Deadline, Flag and a Quorum composite over Rules.

Cancelled and Skew live together because they are one idea twice. A BaseException exists here exactly when
an ordinary `except Exception` must not be able to swallow it. They are the two members the settled
channels speak beside a plain Exception, which is what `Fault` names. They sit in this module rather
than beside the machinery that raises them because the Ledger and the Observer both have to speak the type
while neither may import the dispatcher that mints the second one."""
import time
from abc import ABC, abstractmethod
from collections.abc import Iterable
from typing import final, override

from .errors import Misconfigured


class Cancelled(BaseException):
    """Raised when a Cancellation fires mid-run, aborting a converge or prune. Partial applies are
    idempotent, so re-running resumes from where it stopped. There is no rollback or snapshot machinery.
    For a domain whose apply() regenerates what prune() removes, an interrupted teardown has two clean
    exits. Re-run prune to finish it or converge to restore.

    A BaseException, the KeyboardInterrupt and SystemExit precedent. An abort is a DECISION, not a
    failure, so a domain's ordinary `except Exception` inside a hook cannot swallow it and quietly keep
    converging a run somebody stopped. Catch it by name where an abort is genuinely yours to handle. The
    kernel's own worker boundaries ferry it as a value (a BaseException escaping a pool worker would hang
    the pool), which is why the settled channels speak `Exception | Cancelled` rather than Exception."""

    @classmethod
    def by(cls, cancellation: "Cancellation") -> "Cancelled":
        # The one wording for an aborted run, naming the source that fired. Raised by the wave dispatchers
        # when the check between waves - or Supervised's mid-wave poll - finds it fired.
        return cls(f"Run cancelled by {cancellation.__class__.__name__}")


class Skew(BaseException):
    """Raised when the two sides of a wire disagree about the protocol - a reply naming a fate the
    coordinator does not know, a reply SAYING the hook raised while ferrying no exception, an envelope
    naming a verb no step contract has or a hook that LANDED whose reply then refused to cross.

    A BaseException for exactly the reason Cancelled is one. It was a BUG first. The attempt loop
    catches Exception, so a skew raised as an ordinary one was RETRIED - and the worker half declines to
    say "step failed" for a hook that already ran precisely so that retry is never handed a landed write.
    Measured before the fix. One unpicklable reply under Retry(3) applied three times and the run
    reported a verified clean converge. A BaseException is the only thing that loop's `except Exception`
    structurally cannot catch, so the worker's refusal to lie now survives the frame after the one that
    made it.

    It is still a value the run RECORDS, not an abort that vaporises the record. The write fan catches it
    by name and hands it to the one Ledger rule, so a skew raises under FailFast and blocks just that
    step's dependents under BestEffort. One skewed unit does not take the record of a wave's other
    thousands with it. What it must never do is spend a second attempt. That is what the type buys.

    A skew is NOT an abort, so unlike Cancelled it does not cut through a policy that chose to collect."""


# What a settled write carries instead of an outcome. An ordinary failure or one of the two cut-throughs
# above. Named once because three homes speak it - the dispatcher's Settled tuple, Ledger.record and
# Observer.stepped - and a fourth member would otherwise be a fourth edit in eight places.
class Deferred(BaseException):
    """A write that never ran because its permit was unavailable, cut through like Skew and for the same
    two reasons.

    It must not be RETRIED, which is why it is not an Exception. A permit denial is a fact about the world
    right now. A retry loop spinning on a full pool would spend the step's whole attempt budget on a
    queue it cannot shorten, then report a failure that never happened.

    It must still be RECORDED, which is why the write path catches it. A step that did not run because
    capacity was exhausted is not settled, so the residual is where a run says what is not settled. So a
    denial is DRIFT ABOUT THE WORLD rather than a failure of the step, so the record keeps the two apart -
    nothing broke, the pool was full and the next pass asks again.

    That is the whole reason blocking was refused. A step waiting on a token holds a dispatcher slot while
    the Cancellation cannot fire, so a Deadline would bound the work and not the wait. Reporting starvation
    makes distributed concurrency visible as data instead of hiding it in a suspended coroutine."""


type Fault = Exception | Cancelled | Skew | Deferred


class Cancellation:
    # A cooperative stop for a long run. The Dispatcher checks it between waves (Parallel) or polls it
    # while a wave is still in flight (Supervised), then raises Cancelled when it fires. The base never
    # cancels.
    def cancelled(self) -> bool:
        return False


@final
class Deadline(Cancellation):
    # Cancels once a wall-clock budget (seconds) elapses. The clock starts on the first check, so
    # construction-to-run latency is not counted against the budget. ONE-SHOT by design. The clock never
    # resets, so once the budget is spent every later check cancels too - a Deadline reused across a
    # watch() loop's passes cancels every pass after the first expiry. Budget each run with a fresh Deadline.
    def __init__(self, seconds: float):
        if seconds < 0:
            raise Misconfigured(f"Deadline seconds must be >= 0, got {seconds}")
        self.__seconds = seconds
        self.__started: float | None = None

    @override
    def cancelled(self) -> bool:
        now = time.monotonic()
        if self.__started is None:
            self.__started = now
        return now - self.__started >= self.__seconds


@final
class Flag(Cancellation):
    # Cancels when cancel() is called, e.g. from a SIGINT handler or another thread watching the run.
    def __init__(self) -> None:
        self.__cancelled = False

    def cancel(self) -> None:
        self.__cancelled = True

    @override
    def cancelled(self) -> bool:
        return self.__cancelled


class Rule(ABC):
    # How a Quorum combines its members' fired-or-not states into one cancel-or-continue answer. Given a
    # generator of member states, Some and Every short-circuit it, Most must tally all.
    @abstractmethod
    def __call__(self, fired: Iterable[bool]) -> bool:
        ...


@final
class Some(Rule):
    # Cancel as soon as ANY member fired. Quorum's default.
    def __init__(self) -> None:
        # Declared and empty on purpose. This axis IS a callable, so a class that leaves its
        # constructor implicit reads as an invocation of `__call__` to a tool resolving
        # `Some()` and the strategy that takes nothing is exactly the one that cannot say so
        # any other way. Stating it is the whole point.
        super().__init__()

    @override
    def __call__(self, fired: Iterable[bool]) -> bool:
        return any(fired)


@final
class Every(Rule):
    # Cancel only when EVERY member fired. Quorum forbids an empty member set, so the all([]) is True
    # trap cannot fire here.
    def __init__(self) -> None:
        # Declared and empty on purpose. This axis IS a callable, so a class that leaves its
        # constructor implicit reads as an invocation of `__call__` to a tool resolving
        # `Every()` and the strategy that takes nothing is exactly the one that cannot say so
        # any other way. Stating it is the whole point.
        super().__init__()

    @override
    def __call__(self, fired: Iterable[bool]) -> bool:
        return all(fired)


@final
class Most(Rule):
    # Cancel when MORE members fired than not - a strict majority, a tie does not cancel.
    def __init__(self) -> None:
        # Declared and empty on purpose. This axis IS a callable, so a class that leaves its
        # constructor implicit reads as an invocation of `__call__` to a tool resolving
        # `Most()` and the strategy that takes nothing is exactly the one that cannot say so
        # any other way. Stating it is the whole point.
        super().__init__()

    @override
    def __call__(self, fired: Iterable[bool]) -> bool:
        tally = list(fired)
        return sum(tally) * 2 > len(tally)


class Quorum(Cancellation):
    # A composite Cancellation that fires when an injected Rule is met across its members: Some (the
    # default), Every, Most. A Quorum is itself a Cancellation, so it nests. Members are polled lazily,
    # so Some stops at the first that fired. An empty Quorum is rejected because its answer would hinge
    # on the Rule's vacuous case (Every would fire on all([]) is True).
    def __init__(self, *cancellations: Cancellation, rule: Rule | None = None):
        if not cancellations:
            raise Misconfigured("Quorum needs at least one cancellation - an empty quorum is ill-defined "
                             "(Every would fire on the vacuous all([]) is True)")
        self.__cancellations = cancellations
        self.__rule = rule or Some()   # None sentinel, never a mutable default instance

    @override
    def cancelled(self) -> bool:
        return self.__rule(cancellation.cancelled() for cancellation in self.__cancellations)


@final
class AnyOf(Quorum):
    # Cancel as soon as ANY member fires, the common case. A named Quorum with the Some rule.
    @override
    def __init__(self, *cancellations: Cancellation):
        super().__init__(*cancellations, rule=Some())


@final
class AllOf(Quorum):
    # Cancel only once EVERY member has fired.
    @override
    def __init__(self, *cancellations: Cancellation):
        super().__init__(*cancellations, rule=Every())


@final
class Majority(Quorum):
    # Cancel when a strict majority of members have fired, a tie does not cancel.
    @override
    def __init__(self, *cancellations: Cancellation):
        super().__init__(*cancellations, rule=Most())

