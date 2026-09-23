"""Records - what a run hands BACK. Residual is the verdict of converge(), Explanation the verdict of explain().

These are not the engine and they were sitting in the engine's module. A record answers a question about a
run that has already been resolved or already finished, holds nothing but what it was handed and does no
work - which is why it can be read, kept, compared and printed long after the Reconciler that made it has
gone. The Reconciler imports them while nothing here imports the Reconciler."""
from dataclasses import dataclass
from typing import final

from .drift import Drift


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
        return tuple(reason for reason in self.reasons if reason.step == step)
