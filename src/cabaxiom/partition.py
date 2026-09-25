"""Partition - the resolved run structure the dispatcher walks, as Levels (waves) or Chains (pipelines)."""
import operator
from abc import ABC
from collections import namedtuple
from enum import Enum
from itertools import combinations
from typing import TYPE_CHECKING, ClassVar, final

from .errors import Misconfigured, Unresolvable
from .step import Step

if TYPE_CHECKING:
    from .graph import Graph


@final
class Placement(namedtuple("Placement", "holds described noun")):
    # A shape's ordering rule as a value object. holds(dependency_group, dependent_group) is True when a
    # dependency is legally placed for its dependent, described is that rule in words for verify()'s error,
    # and noun is what ONE of that shape's groups is called.
    #
    # The noun is here rather than on the shape class because it is part of the same fact. A group of a
    # Levels partition is a wave BECAUSE a dependency must sit in an earlier one, while a group of a Chains
    # partition is a chain BECAUSE a dependency must sit in the same one. Anything that renders a resolved
    # run reads it, so nothing downstream has to keep a second table of shape names in step with this one.
    __slots__ = ()


class _Placements(Enum):
    # The two placement rules. The set is closed. A dependency sits in an earlier group for waves or the same
    # group for chains, so an enum rather than literals inline on each shape.
    EARLIER = Placement(operator.lt, "in an earlier group", "wave")
    SAME    = Placement(operator.eq, "in the same group", "chain")


class Partition(tuple[tuple["Step", ...], ...], ABC):
    """A resolved run structure the dispatcher walks - a tuple of groups, each group a tuple of steps. The two
    shapes are dual - Levels (waves - parallel within a group, sequential between) and Chains (pipelines -
    serial within a group, concurrent between). The Reconciler treats either shape uniformly. It walks the
    groups and inverts them for teardown.

    inverse() is the teardown rule - the same structure walked backwards, both the group order and the steps
    within each group reversed, so a dependent is always torn down before the thing it depends on. It returns
    a plain tuple, not a Partition, since dependents-first is the opposite orientation and just runs, never re-verified.

    verify() is the concurrency guard, one walk for both shapes. The shapes differ only in where a dependency
    may sit relative to its dependent, so each shape declares just that rule via _placement.

    That rule is a DECLARED ATTRIBUTE checked at class definition, not an abstract property. An abstractmethod
    is the wrong tool twice over here. A tuple subclass's C-level __new__ skips the instantiate-check, so it
    never blocked anything at runtime - a shape with no rule constructed happily and only failed at its first
    verify(), which is long after the mistake was made. And a plain attribute answering an abstract property
    is not a valid override, so the one line every shape actually writes was the one shape the contract could
    not express. __init_subclass__ runs when the class body finishes, which is that moment."""
    __slots__ = ()
    _placement: ClassVar[Placement]

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        if not isinstance(cls.__dict__.get("_placement"), Placement):
            raise Misconfigured(
                f"{cls.__name__} is a Partition shape and declares no _placement, so nothing says where a "
                f"dependency may sit relative to the step that needs it. Assign one of the placements."
            )

    def inverse(self) -> tuple[tuple["Step", ...], ...]:
        return tuple(tuple(reversed(group)) for group in reversed(self))

    def verify(self, graph: "Graph") -> None:
        # A fanning dispatcher runs a whole group at once, so a step's dependency must be placed where that
        # fan-out still honours it. The Ordering promises the shape and does not prove it, so a mis-split is
        # caught here.
        #
        # AGAINST THE WHOLE DERIVATION, not against one slot. It read `expects` by hand before, so a run
        # ordered by a capability or by an instance was checked against edges that were not the ones it had
        # been ordered by - the guard passed a seating it should have refused, so the hard `requires` edge
        # was invisible to it entirely.
        group_of = {step: index for index, group in enumerate(self) for step in group}
        self.__seats(graph, group_of)
        for index, group in enumerate(self):
            for step in group:
                for dependency in graph.dependencies(step):
                    if not self._placement.holds(group_of[dependency], index):
                        raise Unresolvable(
                            f"{Step.named(step)} depends on {Step.named(dependency)}, yet the Ordering "
                            f"placed {Step.named(dependency)} in group {group_of[dependency]} and "
                            f"{Step.named(step)} in group {index} - a concurrent dispatcher needs a "
                            f"dependency {self._placement.described}, so it would run them out of order."
                        )
        self.__rivals(graph, group_of)

    def __rivals(self, graph: "Graph", group_of: "dict[Step, int]") -> None:
        # The contention rule, which is a SEATING rule and so has no other home. It is not an edge and never
        # could be - an edge says which of two steps goes first, while contention says neither may run beside
        # the other while taking no view on the order.
        #
        # Whether two seats run at the same time is DERIVED from the shape's own placement rule rather than
        # declared a second time. A shape runs two seats concurrently exactly when neither is legally before
        # the other, which reads as "in the same wave" for Levels and "in different chains" for Chains
        # without either shape being asked. A third shape answers it the day it declares its placement.
        for label, contending in graph.contention().items():
            for first, second in combinations(contending, 2):
                here, there = group_of[first], group_of[second]
                if self._placement.holds(here, there) or self._placement.holds(there, here):
                    continue
                raise Unresolvable(
                    f"{Step.named(first)} and {Step.named(second)} both contend for {label!r}, yet the "
                    f"Ordering seated them where this shape runs them at the same time. A contended "
                    f"resource needs one of them {self._placement.described} of the other."
                )

    def __seats(self, graph: "Graph", group_of: "dict[Step, int]") -> None:
        # EVERY step, exactly once, before any placement is judged. The walk below asks where a dependency
        # was seated, so a dependency that was seated nowhere used to make it skip that edge instead of
        # answering - so an Ordering that dropped a step passed the guard and the run silently reconciled
        # a smaller world than it was handed. A step seated twice is the same failure from the other side.
        seated = sum(len(group) for group in self)
        missing = [step for step in graph.steps if step not in group_of]
        if missing:
            named = ", ".join(dict.fromkeys(Step.named(step) for step in missing))
            raise Unresolvable(
                f"The Ordering left {named} out of the seating entirely, so the run would skip work it "
                f"was handed. Every step of the run belongs to exactly one group."
            )
        if seated != len(group_of):
            raise Unresolvable(
                f"The Ordering seated {seated} steps into {len(group_of)} places, so at least one step "
                f"appears in more than one group and would run twice."
            )

@final
class Levels(Partition):
    """A partition as topological LEVELS. Each inner tuple is one wave of mutually-independent steps, the
    waves in dependency order. Its placement (a dependency must sit in an EARLIER wave) is the guard a
    level-fanning dispatcher needs, run by the shared verify()."""
    __slots__ = ()
    _placement = _Placements.EARLIER.value


@final
class Chains(Partition):
    """A partition as independent CHAINS. Each inner tuple is one chain of steps run in series, the chains
    mutually independent so a chain-fanning dispatcher runs them concurrently. The dual of Levels. Its placement
    (a dependency must sit in the SAME chain, run in series before it) is the guard against a Step.expects edge
    crossing between chains, run by the shared verify()."""
    __slots__ = ()
    _placement = _Placements.SAME.value
