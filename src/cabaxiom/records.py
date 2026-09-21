"""Records - what a run hands BACK. Residual is the verdict of converge(), Explanation the verdict of explain().

These are not the engine and they were sitting in the engine's module. A record answers a question about a
run that has already been resolved or already finished, holds nothing but what it was handed and does no
work - which is why it can be read, kept, compared and printed long after the Reconciler that made it has
gone. The Reconciler imports them while nothing here imports the Reconciler."""
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
class Explanation:
    """What the Reconciler resolved, surfaced read-only. The groups the dispatcher walks in run order, and
    the derived dependency edges behind that order.

    `groups` is the resolved run structure, each inner tuple one group of step names - a wave (independent
    within, sequential between) under a level dispatcher or a chain (sequential within, concurrent between)
    under Pipeline. `edges` pairs each step with the steps it depends on, in the same run order. This is
    exactly the partition every verb walks, so it explains the real run and re-resolves nothing.
    """
    def __init__(self, groups: tuple[tuple[str, ...], ...], edges: tuple[tuple[str, tuple[str, ...]], ...]):
        self.groups = groups
        self.edges = edges

    def __repr__(self) -> str:
        # One line. Each group a parenthesised set of step names, the groups joined in run order.
        flow = " -> ".join("(" + ", ".join(group) + ")" for group in self.groups) or "()"
        return f"Explanation({flow})"
