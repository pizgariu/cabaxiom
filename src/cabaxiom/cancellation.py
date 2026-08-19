"""Cancellation strategies for a cooperative run stop: Deadline, Flag, and a Quorum composite over Rules."""
import time
from abc import ABC, abstractmethod
from collections.abc import Iterable
from typing import final

from ._compat import override


class Cancelled(BaseException):
    """Raised when a Cancellation fires mid-run, aborting a converge or prune. Partial applies are
    idempotent, so re-running resumes from where it stopped. There is no rollback or snapshot machinery.
    For a domain whose apply() regenerates what prune() removes, an interrupted teardown has two clean
    exits - re-run prune to finish it, or converge to restore.

    A BaseException, on the KeyboardInterrupt and SystemExit precedent, and for the same reason those
    two are. An abort is a DECISION somebody made about this run, not an accident inside it, and a
    domain hook that writes `except Exception` to guard its own I/O has said nothing whatsoever about
    whether it wants to keep converging a world that has been stopped. It used to be able to eat one
    without noticing. Now it structurally cannot, and the executors' own attempt loops cannot either,
    which turned the abort cut-through from a branch every fan had to remember into a property of the
    type. The cost is that a caller who really wants to catch one has to name it, which is the correct
    price for a decision."""

    @classmethod
    def by(cls, cancellation: object) -> "Cancelled":
        # ONE wording for an aborted run, so the four raise sites cannot drift apart. They did not drift
        # yet - all four spelled the same f-string - which is exactly when a shared form is cheap to
        # introduce and free to keep.
        return cls(f"Run cancelled by {type(cancellation).__name__}")


class Cancellation:
    # A cooperative stop for a long run. The Executor checks it before each step (Serial) or each level
    # (Parallel) and raises Cancelled if it fires. The base never cancels.
    def cancelled(self) -> bool:
        return False


@final
class Deadline(Cancellation):
    # Cancels once a wall-clock budget (seconds) elapses. The clock starts on the first check, so
    # construction-to-run latency is not counted against the budget.
    #
    # ONE-SHOT, and worth knowing before you reuse one. The clock starts once and never restarts, so a
    # Deadline handed to a loop that runs many passes cancels every pass after the first expiry rather
    # than budgeting each one. That is the honest reading of a deadline (a moment, not an allowance),
    # and a per-pass budget is a fresh Deadline per pass.
    def __init__(self, seconds: float):
        if seconds < 0:
            raise ValueError(f"Deadline seconds must be >= 0, got {seconds}")
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
    @override
    def __call__(self, fired: Iterable[bool]) -> bool:
        return any(fired)


@final
class Every(Rule):
    # Cancel only when EVERY member fired. Quorum forbids an empty member set, so the all([]) is True
    # trap cannot fire here.
    @override
    def __call__(self, fired: Iterable[bool]) -> bool:
        return all(fired)


@final
class Most(Rule):
    # Cancel when MORE members fired than not: a strict majority, a tie does not cancel.
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
            raise ValueError("Quorum needs at least one cancellation - an empty quorum is ill-defined "
                             "(Every would fire on the vacuous all([]) is True)")
        self.__cancellations = cancellations
        self.__rule = rule or Some()   # None sentinel, never a mutable default instance

    @override
    def cancelled(self) -> bool:
        return self.__rule(cancellation.cancelled() for cancellation in self.__cancellations)


@final
class AnyOf(Quorum):
    # Cancel as soon as ANY member fires, the common case. A named Quorum with the Some rule.
    def __init__(self, *cancellations: Cancellation):
        super().__init__(*cancellations, rule=Some())


@final
class AllOf(Quorum):
    # Cancel only once EVERY member has fired.
    def __init__(self, *cancellations: Cancellation):
        super().__init__(*cancellations, rule=Every())


@final
class Majority(Quorum):
    # Cancel when a strict majority of members have fired, a tie does not cancel.
    def __init__(self, *cancellations: Cancellation):
        super().__init__(*cancellations, rule=Most())
