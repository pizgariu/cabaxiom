from cabaxiom import Artifacts, Assessment, Backoff, DriftItem, Step
from cabaxiom.core.declaration.drift import FlowAssessment, FlowOutcome


class _RecStep(Step):
    """A step that records its apply() call into a shared log, for ordering assertions. Distinct
    subclasses (A, B, …) are needed because `expects` refers to step CLASSES, while the topo-sort keys on
    type(step) - two instances of one class would collapse to a single node."""

    def __init__(self, log: list):
        self._log = log

    def apply(self, inputs: Artifacts) -> FlowOutcome:
        # Appending to the shared log MUTATES a held list rather than reassigning an attribute, so it
        # is allowed under the frozen Step contract.
        self._log.append(self.__class__.__name__)
        return None, {}


class A(_RecStep):
    pass


class B(_RecStep):
    expects = (A,)


class C(_RecStep):
    expects = (B,)


class X(_RecStep):
    pass


class Y(_RecStep):
    pass


class Z(_RecStep):
    pass


class ReportOnly(Step):
    """A step the reconciler cannot satisfy on its own. Deviation never clears, apply stays the no-op."""

    def assess(self, inputs: Artifacts) -> FlowAssessment:
        return Assessment(deviation=[DriftItem("svc", "still wrong")]), {}


class Fixable(Step):
    """A step that drifts until applied once."""

    def __init__(self):
        # A mutable cell, not a bool. A Step is frozen after __init__, so the flag advances by mutating a
        # held list in place rather than reassigning an attribute.
        self.applied = [False]

    def assess(self, inputs: Artifacts) -> FlowAssessment:
        deviation = [] if self.applied[0] else [DriftItem("f", "needs fix")]
        return Assessment(deviation=deviation), {}

    def apply(self, inputs: Artifacts) -> FlowOutcome:
        self.applied[0] = True
        return None, {}


class Boom(Step):
    def apply(self, inputs: Artifacts) -> FlowOutcome:
        raise RuntimeError("hard I/O failure")


class Staged(Step):
    """Clears one unit of drift per apply(), so it needs `passes` applies to reach desired state. The
    shared multi-pass fixture for convergence and the async reconciler. apply() reports nothing (a plain
    no-op return), so it exercises the loop without touching the applied channel."""

    def __init__(self, passes: int) -> None:
        # A mutable cell for the same reason Fixable uses one. The countdown advances in place. It stays
        # private behind an int property, so a caller reads `step.remaining` as the count it is.
        self.__remaining = [passes]

    @property
    def remaining(self) -> int:
        return self.__remaining[0]

    def assess(self, inputs: Artifacts) -> FlowAssessment:
        deviation = [] if self.__remaining[0] == 0 else [DriftItem("staged", f"{self.__remaining[0]} left")]
        return Assessment(deviation=deviation), {}

    def apply(self, inputs: Artifacts) -> FlowOutcome:
        if self.__remaining[0]:
            self.__remaining[0] -= 1
        return None, {}


class RecordingBackoff(Backoff):
    """A Backoff that records the stall count handed to each pause and pauses for nothing, so a test stays
    instant. `stalls` is the sequence of stall counts Fixpoint or Retry paced, in order."""

    def __init__(self) -> None:
        self.stalls: list[int] = []

    def delay(self, stalled: int) -> float:
        self.stalls.append(stalled)
        return 0.0
