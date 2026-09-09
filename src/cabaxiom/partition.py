"""Partition - the resolved run structure the dispatcher walks, as Levels (waves) or Chains (pipelines)."""
import operator
from abc import ABC
from collections import namedtuple
from enum import Enum
from typing import ClassVar, final

from .step import Step


@final
class Placement(namedtuple("Placement", "holds described")):
    # A shape's ordering rule as a value object. holds(dependency_group, dependent_group) is True when a
    # dependency is legally placed for its dependent, while described is that rule in words for verify()'s error.
    __slots__ = ()


class _Placements(Enum):
    # The two placement rules. The set is closed. A dependency sits in an earlier group for waves or the same
    # group for chains, so an enum rather than literals inline on each shape.
    EARLIER = Placement(operator.lt, "in an earlier group")   # waves
    SAME    = Placement(operator.eq, "in the same group")     # chains


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

    That rule is a DECLARED ATTRIBUTE, not an abstract property. An abstractmethod is the wrong tool twice
    over here. A tuple subclass's C-level __new__ skips the instantiate-check, so it never blocked anything
    at runtime - a shape with no rule constructed happily and only failed at its first verify(), which is
    long after the mistake was made. And a plain attribute answering an abstract property is not a valid
    override, so the one line every shape actually writes was the one shape the contract could not express."""
    __slots__ = ()
    _placement: ClassVar[Placement]

    def inverse(self) -> tuple[tuple["Step", ...], ...]:
        return tuple(tuple(reversed(group)) for group in reversed(self))

    def verify(self) -> None:
        # A fanning dispatcher runs a whole group at once, so a step's dependency must be placed where that
        # fan-out still honours Step.after. The Ordering promises the shape but does not prove it, so a
        # mis-split is caught here.
        group_of = {type(step): index for index, group in enumerate(self) for step in group}
        for index, group in enumerate(self):
            for step in group:
                for dependency in step.after:
                    if dependency in group_of and not self._placement.holds(group_of[dependency], index):
                        raise ValueError(
                            f"{Step.named(step)} depends on {dependency.__name__}, yet the Ordering "
                            f"placed {dependency.__name__} in group {group_of[dependency]} and "
                            f"{Step.named(step)} in group {index} - a concurrent dispatcher needs a "
                            f"dependency {self._placement.described}, so it would ignore Step.after."
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
    (a dependency must sit in the SAME chain, run in series before it) is the guard against a Step.after edge
    crossing between chains, run by the shared verify()."""
    __slots__ = ()
    _placement = _Placements.SAME.value
