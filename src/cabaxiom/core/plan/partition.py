"""Partition - the resolved run structure a dispatcher walks, as waves, chains or a plain serial walk."""
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable, Iterator
from enum import Enum
from typing import NamedTuple, final

from ..declaration.errors import Seating
from ..declaration.step import Step
from .graph import Graph


class Overlap(Enum):
    """WHERE a shape runs things at the same time, deduced directly from its placement rule.
    The value is the phrase the refusal speaks, so the fact and its wording travel
    together and no message has to reassemble it.

    IT IS A VERB'S OBJECT, so a new member must be written to fit that frame - `runs <value> at the same
    time`, `it overlaps <value>`. The frame is part of the contract because it is the half a reader cannot
    see from the value alone. The pairing refusal once put an article in front of one of these and
    shipped `an overlap the groups`. Every member reads under a verb and not one reads under an article."""

    WITHIN = "the steps inside one group"    # Waves: a wave runs at once
    ACROSS = "the groups"                    # Chains: the chains run at once, each in series
    NEITHER = "nothing"                      # Walk: one thread, one step at a time
    # A WORKER-ONLY answer, which no shape derives. Waves and Chains lean on the SEATING to keep the edges,
    # so the guard must ask whether a shape's rule and a worker's concurrency agree. A worker that reads the
    # GRAPH instead - awaiting each step's own prerequisites and holding its own contention - leans on no
    # seating at all, so every shape is safe for it and the pairing question does not arise. That is a third
    # safety story, not a third amount of overlap, so it gets its own word rather than borrowing NEITHER's.
    EDGES = "only what the declared edges allow"


@final
class Seat(NamedTuple):
    # Where a step actually sits. Which group and where inside it. A rule that saw only the GROUP could
    # not tell a chain apart from itself reversed - both ask about group 0 - so the seat carries the
    # position too, so the shapes that care about order within a group can finally say so.
    #
    # `position` and not `slot`, though a slot is what it is. `slot` already means the DECLARATION slot a
    # step writes in (`expects`, `requires`, `wants`, `demands`, `needs`) everywhere else in this kernel and
    # one word meaning two things is the defect this codebase spends its bug changelog on.
    group: int
    position: int


@final
class Placement(NamedTuple):
    # A shape's ordering rule as a value object. Its holds(dependency_seat, dependent_seat) is True when a
    # dependency is legally placed for its dependent, while described is that rule in words for verify()'s
    # error. A typed NamedTuple, so the one seam verify() trusts is checked, not Any-shaped.
    #
    # grouping is the shape's own noun for ONE group - a wave, a chain - and it rides here rather than
    # standing as a second seam because naming what a group IS and ruling on where a step may sit inside
    # one are the same fact told two ways. A reader of a drawn run needs it. "wave 0" promises its members
    # run at once, "chain 0" promises they run in series, so a picture that called both "group 0" would
    # hide the single most load-bearing thing about the shape.
    #
    # BOTH STRINGS ARE SPLICED INTO TEXT SOMEBODY READS and neither is ever compared, so the shape that
    # declares them is vetted at class-definition time by Partition.__init_subclass__ below.
    holds: Callable[[Seat, Seat], bool]
    described: str
    grouping: str


class Partition(ABC):
    """A resolved run structure the dispatcher walks. Groups in run order, each group a tuple of steps. The two
    fanning shapes are dual - WavesPartition (waves - parallel within a group, sequential between) and
    ChainsPartition (chains - serial within a group, concurrent between) - and WalkPartition is the serial
    walk. The Reconciler treats every shape uniformly. It walks the groups and inverts them for teardown.

    COMPOSED over its groups, not subclassed from tuple. The old tuple base defeated the ABC it stood under:
    a tuple subclass's C-level __new__ skips the abstractmethod instantiate-check, so an incomplete custom
    shape constructed happily and only failed at its first verify() - the placement contract was type-checked
    prose rather than a refusal. Holding the groups makes ABCMeta's refusal real. A shape that forgot its
    placement cannot be CONSTRUCTED. The groups stay reachable three ways, each for the reader it serves:
    iteration and len() for every walk, plus `groups` for the dispatcher hand-off, which stays a plain tuple so
    a custom dispatcher's contract does not change shape.

    inverse() is the teardown rule. The same structure walked backwards, both the group order and the steps
    within each group reversed, so a dependent is always torn down before the thing it depends on. It returns
    a plain tuple, not a Partition. Dependents-first is the opposite orientation and just runs, never re-verified.

    verify() is the ordering guard, one walk for every shape. The shapes differ only in where a dependency
    may sit relative to its dependent, so each shape declares just that rule via placement - including the
    serial walk, whose rule ("earlier in the walk") is a real rule rather than an exemption, which is why
    every shape is verified and none is trusted."""
    __slots__ = ("__groups",)

    def __init_subclass__(cls, **kwargs: object) -> None:
        # The shape's WORDING vetted where the shape is declared, which is the same clock ABCMeta already
        # uses to refuse a shape that forgot its rule. Both strings end up in text a person reads and
        # neither is ever compared, so nothing else would ever notice them being wrong. `described`
        # completes verify()'s refusal mid-sentence, so a capital, a full stop or a single word breaks the
        # one sentence a caller most needs whole. `grouping` lands in a drawing as "<grouping> 0", so a
        # phrase or a capital there reads as a bug in the picture. This axis is OPEN by design - a third
        # party may ship a shape - and a contract kept only in the docstrings of the three shipped ones is
        # a contract for nobody.
        super().__init_subclass__(**kwargs)
        declared = cls.__dict__.get("placement")
        if not isinstance(declared, Placement):
            return   # still abstract or a property, which ABCMeta and the type checker judge instead
        told = declared.described
        if not told or told[0].isupper() or len(told.split()) < 2 or told[-1] in ".,;:":
            raise Seating(
                f"{cls.__name__}.placement describes its rule as {told!r}, so `described` completes one "
                f"sentence mid-flow - \"this shape needs a dependency <described>, so the run would ignore "
                f"the edge\". So it reads as a lowercase phrase of at least two words carrying no closing "
                f"punctuation. The shipped shapes say \"in an earlier group\" and \"earlier in the same group\"."
            )
        if ":" in told or ";" in told:
            raise Seating(f"{cls.__name__}.placement describes its rule as {told!r}. That text is prose, so it carries no colon and no semicolon.")
        noun = declared.grouping
        if not noun or not noun.isalpha() or not noun.islower():
            raise Seating(
                f"{cls.__name__}.placement names one group {noun!r}. That noun lands in a drawing as "
                f"\"<grouping> 0\", so it reads as a single lowercase word. The shipped shapes say \"wave\", "
                f"\"chain\" and \"leg\"."
            )

    def __init__(self, groups: Iterable[tuple["Step", ...]]):
        self.__groups = tuple(groups)

    @property
    def groups(self) -> tuple[tuple["Step", ...], ...]:
        # The run structure as the plain tuple the dispatcher contract speaks - handed over by the
        # reconciler, so execute() keeps its shape and a custom dispatcher migrates nothing.
        return self.__groups

    def __iter__(self) -> Iterator[tuple["Step", ...]]:
        return iter(self.__groups)

    def __len__(self) -> int:
        return len(self.__groups)

    def inverse(self) -> tuple[tuple["Step", ...], ...]:
        return tuple(tuple(reversed(group)) for group in reversed(self.__groups))

    @final
    def verify(self, graph: Graph) -> None:
        # However this shape is walked, a step's dependency must SIT where that walk still honours the edge.
        # The Ordering promises the shape but does not prove it, so a mis-placement is caught here - against
        # the handed Graph, the SAME derivation the Ordering resolved over, which is what makes this guard
        # total by construction: EVERY edge kind the vocabulary declares (or ever grows) is checked, because
        # the guard no longer keeps its own list of kinds. Keyed by INSTANCE, since two steps of one class
        # may land in different seats once instance edges order them.
        seat_of = {step: Seat(group, position)
                   for group, steps in enumerate(self.groups)
                   for position, step in enumerate(steps)}
        for step, seat in seat_of.items():
            for dependency in graph.dependencies(step):
                if not self.placement.holds(seat_of[dependency], seat):
                    raise Seating(
                        f"{Step.named(step)} depends on {Step.named(dependency)}, yet the Ordering "
                        f"seated the dependency at {tuple(seat_of[dependency])} and {Step.named(step)} "
                        f"at {tuple(seat)} - this shape needs a dependency {self.placement.described}, so "
                        f"the run would ignore the edge."
                    )
        self.__exclusive(seat_of)

    def __exclusive(self, seat_of: dict["Step", Seat]) -> None:
        # The CONTENTION guard, the second thing a seating can get wrong. An edge is about order and this is
        # not. Two steps contending for one resource may run in either order or an hour apart, never at
        # the same time. So the question is not whether a dependency sits legally, it is whether two seats
        # OVERLAP - and the shape already answered that without being asked twice.
        #
        # together() is DERIVED from the placement rule this shape publishes, so no shape declares a second
        # thing about itself and a custom Partition is covered the day it is written. Two seats run at once
        # exactly when neither arrangement could legally carry a dependency. If the rule would refuse an edge
        # in both directions, it is refusing it because the two are in flight together. Measured against all
        # three shipped shapes - a wave overlaps and waves do not, a chain does not overlap and chains do,
        # and a serial walk overlaps nothing.
        held: dict[str, tuple[Step, Seat]] = {}
        for step, seat in sorted(seat_of.items(), key=lambda pair: pair[1]):
            for label in sorted(step.contends):
                standing = held.get(label)
                if standing is not None and self.together(standing[1], seat):
                    raise Seating(
                        f"{Step.named(step)} and {Step.named(standing[0])} both contend for "
                        f"{label!r}, yet this shape seats them at {tuple(standing[1])} and {tuple(seat)}, "
                        f"which run at the same time. Contention is not an edge and must not be written as "
                        f"one - the shape has to seat them apart."
                    )
                held[label] = (step, seat)

    @final
    def together(self, one: Seat, other: Seat) -> bool:
        """Whether two seats are IN FLIGHT at the same time under this shape.

        Derived, never declared. A shape publishes one rule - where a dependency may sit - and that rule
        already knows the answer. If it would refuse an edge in BOTH directions between two seats, the only
        reason left is that the two overlap in time, since a shape that ran them one after the other would
        have to permit the edge in whichever direction matches the running order. So a shape gets contention
        support for free the moment it states its placement, which is the property that let this land without
        a second declaration on every Partition ever written."""
        return not self.placement.holds(one, other) and not self.placement.holds(other, one)

    @property
    def overlap(self) -> Overlap:
        """WHERE this shape overlaps in flight, derived from its own placement rule - the ONE home
        for that fact, read by the dispatcher pairing guard and by the contention seating alike.

        A shape overlaps ACROSS groups when its rule permits a dependency in a later group while the
        dependent still runs (chains, each serial inside). It overlaps WITHIN a group when the rule
        permits them side by side in one (waves). A rule that permits neither is a serial walk and
        overlaps nothing. Derived rather than declared, so a shape that ships tomorrow answers the
        moment it states its rule - and cannot answer two consumers two different ways."""
        if self.together(Seat(0, 0), Seat(1, 0)):
            return Overlap.ACROSS
        if self.together(Seat(0, 0), Seat(0, 1)):
            return Overlap.WITHIN
        return Overlap.NEITHER

    @property
    @abstractmethod
    def placement(self) -> Placement:
        # The one per-shape rule, a Placement carrying the predicate plus its wording. The walk and the
        # message are shared. PUBLIC, like every extension seam in the kernel. A custom Partition implements
        # exactly this, so verify() (the guard) is what protects the invariant, not a hidden name.
        ...


@final
class WavesPartition(Partition):
    """A partition as topological WAVES. Each inner tuple is one wave of mutually-independent steps, the
    waves in dependency order. Its placement (a dependency must sit in an EARLIER wave) is the guard a
    level-fanning dispatcher needs, run by the shared verify(). Built by the Waves arranger."""
    __slots__ = ()
    # Only the wave matters. A dependency in an earlier wave is done before this one starts, so where it
    # sat INSIDE that wave is irrelevant, since the whole wave runs at once.
    # An abstract PROPERTY satisfied by a class CONSTANT. That is correct Python and it is the reason
    # ABCMeta refuses to construct a shape that forgot its rule, which is the guarantee this class
    # exists to make. A strict checker reads the base slot as `property` and the override as
    # `Placement` and calls that incompatible. Turning it into a plain annotated ClassVar would
    # satisfy it and DELETE the refusal, because placement is the only abstract member here and
    # without it Partition itself becomes constructible. The rule stays on everywhere else.
    placement = Placement(lambda dependency, dependent: dependency.group < dependent.group,  # pyright: ignore[reportAssignmentType, reportIncompatibleMethodOverride]
                          "in an earlier group", "wave")


@final
class ChainsPartition(Partition):
    """A partition as independent CHAINS. Each inner tuple is one chain of steps run in series, the chains
    mutually independent so a chain-fanning dispatcher runs them concurrently. The dual of WavesPartition. Its
    placement (a dependency must sit in the SAME chain, run in series before it) is the guard against a
    declared edge crossing between chains, run by the shared verify(). Built by the Chains arranger."""
    __slots__ = ()
    # BOTH clauses of this shape's own rule, which a group-only view could not say. The same chain (chains
    # run concurrently, so an edge may not cross one) AND earlier in it (a chain runs in series, so a
    # dependency seated after its dependent would run after it).
    placement = Placement(lambda dependency, dependent: dependency.group == dependent.group  # pyright: ignore[reportAssignmentType, reportIncompatibleMethodOverride]
                          and dependency.position < dependent.position,
                          "earlier in the same group", "chain")


@final
class WalkPartition(Partition):
    """A partition walked strictly in order on one thread, group by group and step by step within each. What
    the serial-safe Walk arranger builds. Nothing runs at once, so a dependency may share a
    group with its dependent - it only has to come BEFORE it in the walk, which is exactly seat order. That
    is a real rule, so a serial run is verified like any other rather than trusted, while an Ordering that
    hands back a reversed order is refused at construction instead of quietly applying it backwards."""
    __slots__ = ()
    # Seats compare lexicographically, so this IS walk order. An earlier group wins, then within a group an
    # earlier position does. Spelled out rather than handed to operator.lt, which typeshed declares as returning
    # Any - it would satisfy the bool this contract promises without anything ever checking it.
    placement = Placement(lambda dependency, dependent: dependency < dependent,  # pyright: ignore[reportAssignmentType, reportIncompatibleMethodOverride]
                          "earlier in the walk", "leg")
