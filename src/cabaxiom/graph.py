"""The Graph - one home for every edge a declaration draws and every question asked about them.

Before this, seven places walked the declaration by hand and four of them read the slot off the type
while three read it off the instance. Seven copies of one fact is how a guard ends up honouring an edge
kind in one place and missing it in another, which the class-versus-instance split was already
happening. One derivation, read by every consumer, so a kind added to the vocabulary tomorrow is honoured
everywhere without any of them learning it exists.

IMMUTABLE IN CONTRACT AND LAZY IN COMPUTATION. The edges are derived once at construction, since every
consumer needs them. The inversion is built on the first ask and kept, since a run that never asks for
dependents never pays for them."""
from collections import defaultdict
from collections.abc import Callable, Iterable, Sequence
from typing import final

from .errors import Identity, Malformed, Presence
from .step import Step
from .vocabulary import MODES, EdgeKind, Roster, Vocabulary

# What a slot may hold. A plain alias rather than a `type` statement, since the floor is still 3.10.
Declared = type[Step] | str | Step


@final
class Match:
    """One NAME in one slot plus every step in the run it pointed at - including none.

    The per-name view of an edge, where dependencies() is the per-step one. It carries the ROW rather
    than the slot's name, so a consumer that needs the hardness or the addressing reads the vocabulary
    instead of re-learning it from a list of slot names somebody has to keep in step."""

    __slots__ = ("__step", "__kind", "__name", "__matched")

    def __init__(self, step: Step, kind: EdgeKind, name: Declared, matched: Sequence[Step]):
        self.__step = step
        self.__kind = kind
        self.__name = name
        self.__matched = tuple(matched)

    @property
    def step(self) -> Step:
        return self.__step

    @property
    def kind(self) -> EdgeKind:
        return self.__kind

    @property
    def slot(self) -> str:
        return self.__kind.slot

    @property
    def name(self) -> Declared:
        return self.__name

    @property
    def matched(self) -> tuple[Step, ...]:
        return self.__matched

    @property
    def soft(self) -> bool:
        # Read off the ROW, never off a hardcoded list of slot names. A kind grown tomorrow answers this
        # correctly on the day it is added.
        return not self.__kind.hard

    @property
    def label(self) -> str:
        return self.__kind.addressing.spoken(self.__name)

    def __repr__(self) -> str:
        found = ", ".join(Step.named(step) for step in self.__matched) or "nothing"
        return f"Match({Step.named(self.__step)}.{self.slot} {self.label} -> {found})"


@final
class Graph:
    """Every edge one declaration draws, derived once, over one membership."""

    def __init__(self, steps: Iterable[Step], vocabulary: Vocabulary | None = None):
        self.__vocabulary = vocabulary if vocabulary is not None else Vocabulary.shipped()
        self.__steps = tuple(steps)
        for step in self.__steps:
            self.__vet(step, self.__vocabulary)
        self.__addressable()

        instances: defaultdict[type[Step], list[Step]] = defaultdict(list)
        providers: defaultdict[str, list[Step]] = defaultdict(list)
        for step in self.__steps:
            instances[type(step)].append(step)
            for capability in step.provides:            # off the INSTANCE, so one may provide and its twin not
                providers[capability].append(step)
        self.__instances: dict[type[Step], Sequence[Step]] = {kind: Roster(held) for kind, held in instances.items()}
        self.__providers: dict[str, Sequence[Step]] = dict(providers)

        # ONE loop over the vocabulary. That is the whole point of the table. There is no branch here
        # naming a slot, so a row added tomorrow is derived by this same loop on the day it is added.
        drawn: defaultdict[Step, list[Step]] = defaultdict(list)
        for step in self.__steps:
            for kind in self.__vocabulary:
                for name in getattr(step, kind.slot, ()):
                    for found in self.__found(kind, name):
                        if kind.precedes:
                            drawn[found].append(step)   # this step runs BEFORE the match
                        else:
                            drawn[step].append(found)
        self.__edges = {step: tuple(dict.fromkeys(drawn.get(step, ()))) for step in self.__steps}
        self.__inverted: dict[Step, tuple[Step, ...]] | None = None

    def __found(self, kind: EdgeKind, name: Declared) -> tuple[Step, ...]:
        # Shared by the derivation and by matching(), so the two views of one edge cannot disagree.
        return kind.addressing.found(name, self.__instances, self.__providers)

    def __addressable(self) -> None:
        # IDENTITY IS THE DEPENDENCY CURRENCY. Two steps a dict cannot tell apart become one node, so the
        # run would reconcile a smaller world than it was handed and say nothing. The two cases get two
        # sentences, because handing the same instance in twice is a different mistake from handing in two
        # that compare equal, where the fix differs.
        if len(set(self.__steps)) == len(self.__steps):
            return
        seen: set[int] = set()
        for step in self.__steps:
            if id(step) in seen:
                raise Identity(
                    f"{Step.named(step)} was handed to this run twice. One instance is one node of the "
                    f"derivation, so the second is not a second step - build two."
                )
            seen.add(id(step))
        raise Identity(
            "Two steps in this run compare equal, so the derivation cannot tell them apart and one of "
            "them would silently never run. A step is addressed by identity."
        )

    @staticmethod
    def __vet(step: Step, vocabulary: Vocabulary) -> None:
        # The shape of every slot, checked per INSTANCE because that is where a slot is read from. The
        # classic catch is the forgotten comma - `expects = (Reactor)` is the class and not a one-tuple -
        # and the second is a bare string in a set-of-labels slot, which iterates into single characters.
        for kind in vocabulary:
            declared = getattr(step, kind.slot, ())
            if isinstance(declared, str) or not isinstance(declared, tuple):
                raise Malformed(
                    f"{Step.named(step)}.{kind.slot} must be a tuple of {kind.addressing.takes}, got "
                    f"{type(declared).__name__}. A single entry needs its trailing comma."
                )
            for name in declared:
                if kind.addressing.admits(name):
                    continue
                elsewhere = next((mode for mode in MODES if mode.admits(name)), None)
                hint = f" {elsewhere.stray} belongs in a slot addressed that way." if elsewhere else ""
                raise Malformed(
                    f"{Step.named(step)}.{kind.slot} takes {kind.addressing.takes}, yet it holds "
                    f"{name!r}.{hint}"
                )
        for labels in ("provides", "contends"):
            held: object = getattr(step, labels, frozenset())
            if isinstance(held, str) or not isinstance(held, (frozenset, set)):
                raise Malformed(
                    f"{Step.named(step)}.{labels} must be a set of labels, got {type(held).__name__}. A "
                    f"bare string iterates into single characters, which is the silent kind of wrong."
                )

    @property
    def vocabulary(self) -> Vocabulary:
        return self.__vocabulary

    @property
    def steps(self) -> tuple[Step, ...]:
        # PUBLISHED, so a consumer cannot be handed a derivation of one world beside the steps of another.
        # Every verb along the spine takes the Graph alone for exactly this reason.
        return self.__steps

    def dependencies(self, step: Step) -> tuple[Step, ...]:
        # What must settle before this step, deduplicated, first-seen order kept.
        return self.__edges.get(step, ())

    def matching(self, step: Step) -> tuple[Match, ...]:
        # The per-NAME twin of dependencies(), MISSES INCLUDED and deliberately not deduplicated. A hard
        # edge that matched nothing is invisible in dependencies() and is precisely what demand() is
        # looking for, so the two cannot be the same view.
        return tuple(Match(step, kind, name, self.__found(kind, name))
                     for kind in self.__vocabulary
                     for name in getattr(step, kind.slot, ()))

    def dependents(self, step: Step) -> tuple[Step, ...]:
        # The inversion, built on the first ask and kept. A run that never asks never pays.
        if self.__inverted is None:
            building: defaultdict[Step, list[Step]] = defaultdict(list)
            for dependent, prerequisites in self.__edges.items():
                for prerequisite in prerequisites:
                    building[prerequisite].append(dependent)
            self.__inverted = {held: tuple(building.get(held, ())) for held in self.__steps}
        return self.__inverted.get(step, ())

    def closure(self, seeds: Iterable[Step]) -> frozenset[Step]:
        # The seeds plus everything they transitively need. What a targeted run must keep.
        return self.__reached(seeds, self.dependencies)

    def fallout(self, seeds: Iterable[Step]) -> frozenset[Step]:
        # The seeds plus everything that transitively needs them. What one failure costs.
        return self.__reached(seeds, self.dependents)

    @staticmethod
    def __reached(seeds: Iterable[Step], along: Callable[[Step], tuple[Step, ...]]) -> frozenset[Step]:
        # ONE frontier walk and the direction is a parameter, so closure and fallout cannot drift apart in
        # their handling of a cycle, a repeat or an isolated seed.
        reached: set[Step] = set()
        frontier = list(seeds)
        while frontier:
            step = frontier.pop()
            if step in reached:
                continue
            reached.add(step)
            frontier.extend(along(step))
        return frozenset(reached)

    def components(self) -> tuple[tuple[Step, ...], ...]:
        # The weakly-connected split, over the DERIVED edges rather than over one slot. Groups and members
        # both come out in supplied order, so a component split is reproducible.
        parent: dict[Step, Step] = {step: step for step in self.__steps}

        def root(step: Step) -> Step:
            while parent[step] is not step:
                parent[step] = parent[parent[step]]      # path halving
                step = parent[step]
            return step

        for step in self.__steps:
            for prerequisite in self.dependencies(step):
                parent[root(step)] = root(prerequisite)
        grouped: defaultdict[Step, list[Step]] = defaultdict(list)
        for step in self.__steps:
            grouped[root(step)].append(step)
        return tuple(tuple(grouped[held]) for held in dict.fromkeys(root(step) for step in self.__steps))

    def demand(self) -> None:
        # THE HARD-PRESENCE RULE, nothing else. A hard edge that matched nothing is a refusal, a soft
        # one that matched nothing is a shrug. Which it is comes off the ROW rather than off a list of
        # slot names this method would otherwise have to keep in step with the vocabulary.
        for step in self.__steps:
            for match in self.matching(step):
                if match.soft or match.matched:
                    continue
                raise Presence(
                    f"{Step.named(step)}.{match.slot} names {match.label} and this run has no such "
                    f"{match.kind.addressing.noun}. A hard edge says the world must contain it. The "
                    f"soft companion {match.kind.counterpart!r} is the slot that trusts the world instead."
                )
