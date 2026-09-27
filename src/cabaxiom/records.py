"""Records - what a run hands BACK. Residual from converge(), Explanation from explain(), Casualty from foresee().

These are not the engine and they were sitting in the engine's module. A record answers a question about a
run that has already been resolved or already finished, holds nothing but what it was handed and does no
work - which is why it can be read, kept, compared and printed long after the Reconciler that made it has
gone. The Reconciler imports them while nothing here imports the Reconciler."""
from dataclasses import dataclass
from typing import final

from .drift import Drift
from .errors import Unresolvable


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
@dataclass(frozen=True)
class Reason:
    """ONE declaration and what it resolved to. The unit `edges` flattens away.

    A flat "Api depends on Db" is the answer to a question nobody asked. With eight slots in the language,
    the useful question is which declaration drew that edge - whether Api named a class, a capability or an
    instance and whether it named it hardly or softly. Those differ in what a caller does about it, so an
    explanation that cannot tell them apart cannot be acted on.

    `matched` is empty for a declaration nothing answered. That is legal for a soft slot and refused for a
    hard one before a run ever gets here, so an empty one in an explanation is always a soft miss - which is
    worth seeing, because a soft miss is the shape of a step that quietly did not order against anything."""

    step: str
    slot: str
    name: str
    matched: tuple[str, ...]
    hard: bool

    def __str__(self) -> str:
        return f"{self.step}.{self.slot} {self.name} -> {', '.join(self.matched) or 'nothing'}"


@final
class Explanation:
    """What the Reconciler resolved, surfaced read-only. The groups the dispatcher walks in run order, the
    derived dependency edges behind that order plus the declarations that drew each one.

    `groups` is the resolved run structure, each inner tuple one group of step names - a wave (independent
    within, sequential between) under a level dispatcher or a chain (sequential within, concurrent between)
    under Pipeline. `edges` pairs each step with the steps it depends on, in the same run order. `reasons`
    is the same information unflattened, one Reason per declaration the steps actually wrote. `shape` is
    what ONE of those groups is called under the dispatcher that resolved it, a wave or a chain, which is
    the difference between running a group together and running it in series. This is exactly the partition
    every verb walks, so it explains the real run and re-resolves nothing.
    """
    def __init__(self, groups: tuple[tuple[str, ...], ...], edges: tuple[tuple[str, tuple[str, ...]], ...],
                 reasons: tuple[Reason, ...] = (), shape: str = "group"):
        self.groups = groups
        self.edges = edges
        self.reasons = reasons
        self.shape = shape

    def __repr__(self) -> str:
        # One line. Each group a parenthesised set of step names, the groups joined in run order.
        flow = " -> ".join("(" + ", ".join(group) + ")" for group in self.groups) or "()"
        return f"Explanation({flow})"

    def because(self, step: str) -> tuple[Reason, ...]:
        # Every declaration one step wrote, in the order the vocabulary lists the slots. The lookup callers
        # would otherwise write themselves over `reasons`, the one they would write differently each time.
        #
        # A name this run never resolved is REFUSED rather than answered with an empty tuple, because an
        # empty tuple is the honest answer for a step that declared nothing. The two are not the same
        # finding and they were spelled the same way, so a typo read as a step with no declarations.
        # foresee() already refuses it. Two structural reads of one run should not disagree.
        if step not in {named for group in self.groups for named in group}:
            raise Unresolvable(
                f"{step} is not in this run, so there is nothing it could have declared. An explanation is "
                f"about the run that was resolved, not about a step that might have been in it."
            )
        return tuple(reason for reason in self.reasons if reason.step == step)


@final
@dataclass(frozen=True)
class Casualty:
    """What ONE step's failure would cost this run, read before anything runs - explain()'s counterfactual.

    `blocked` is the derivation's answer - every step that transitively depends on the failure, which is
    every step that must not be allowed to converge after it. It is not a simulation. It is the Graph's
    own fallout() walk, the same one a targeted run inverts to build its closure, so the forecast cannot
    drift from the derivation it forecasts about.

    READ THAT FIELD CAREFULLY AT THIS VERSION. It says what a failure WOULD cost, not what the kernel
    currently withholds. `OnError.BestEffort` records the failure and keeps going, so every step named in
    `blocked` still runs, against state nobody put there. Naming them is the whole point of this
    read - it is the measurement that says how much a run stands to lose before anything is done about it.

    `skipped` and `settling` are the FailFast answer, split in two because FailFast stops the
    run by RUN POSITION rather than by edges - so what survives depends on the shape the dispatcher walks.
    `skipped` is every step in a strictly later group, which no dispatcher can start once the run has
    stopped. `settling` is the failure's own group-mates, which are indeterminate, because a fanning
    dispatcher admitted the whole group at once and they are already in flight.

    `starves` is a severity note rather than a further casualty. It names the capabilities this step is
    the only present provider of. Every step wanting one of them already stands in `blocked`, because a
    capability edge fans to every provider, yet a FUTURE declaration written against a starved capability
    fails differently - a `demands` refuses at resolution and a `wants` goes quiet.

    A Casualty is truthy when it is NOT contained, so it reads as the finding it is."""

    failed: str
    blocked: tuple[str, ...]
    skipped: tuple[str, ...]
    settling: tuple[str, ...]
    starves: tuple[str, ...]

    @property
    def contained(self) -> bool:
        # Nothing else depends on it. The run would lose this step and no more, which under BestEffort is
        # the difference between a failure and an incident.
        return not self.blocked

    def __bool__(self) -> bool:
        return not self.contained

    def __str__(self) -> str:
        if self.contained:
            return f"{self.failed} would fail alone"
        return f"{self.failed} would fail, blocking {', '.join(self.blocked)}"
