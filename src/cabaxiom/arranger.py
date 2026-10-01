"""Arranger - HOW an Ordering becomes the Partition a dispatcher walks - the shape it fans into (waves or chains) or the serial-safe walk that fans nothing."""
from abc import ABC, abstractmethod
from typing import final, override

from .errors import Coverage, Pairing, Seating
from .graph import Graph
from .ordering import Ordering
from .partition import ChainsPartition, Overlap, Partition, WalkPartition, WavesPartition
from .step import Step


class Arranger(ABC):
    """The open extension point for HOW an Ordering becomes the Partition a dispatcher walks, handed to
    BaseDispatcher's constructor. Subclass it to build your own run-shape - say, custom waves for a
    pipeline - and pass it up from your dispatcher's __init__. The built-in shapes: Waves (a
    WavesPartition, the shape the wave dispatchers Parallel and Supervised compose) and Chains (a
    ChainsPartition, its chain dual - no shipped dispatcher composes it today, a custom chain-runner
    does) are the fanning pair, while Walk is the serial-safe shape that fans nothing, the one a trivial
    custom dispatcher reaches for. A RunMode PAIRS an Arranger with the worker that will walk what it
    builds and calls arrange() inside its own resolve() before guarding the pairing - so the shape stays a
    plugged-in object rather than a branch, so the reconciler asks the RunMode rather than being handed the
    component to drive.

    arrange() is CONCRETE and owns resolution's guards, so a custom shape inherits them instead of being
    trusted to remember them. It opens with graph.demand() - the hard-presence rule (`requires`, `demands`),
    fired the moment membership is final and OUTSIDE the Ordering, so no Ordering can forget it - then asks
    the subclass for its shape and guards what comes back through __covers. The seam is shape(), which
    builds and nothing else. A subclass that implements it cannot skip a guard by forgetting one, because it
    never had the chance to write the sequence. That is the whole reason the abstract method moved down a
    level, since an abstract entry point made every guard opt-IN, where one four-line Arranger was enough to
    converge a run whose `requires` named a step nobody had supplied.

    The order is load-bearing. __covers runs before the placement check or an Ordering that DROPPED a
    prerequisite would turn that check's seat lookup into a KeyError instead of the coverage error naming
    the real fault. Keeping the sequence here rather than in an override is what makes the order a property
    of the kernel instead of a rule each shape has to remember.

    Every shape is verified, none is trusted. The rule comes from the Partition the seam RETURNS, so what a
    shape claims about itself and what it hands back cannot disagree - a serial walk says so by building a
    WalkPartition, whose rule is "earlier in the walk" rather than an exemption from checking.

    The Graph is the WHOLE input, for the same reason. It carries the run's membership as graph.steps
    alongside the edges derived over exactly that membership. The two used to arrive as separate arguments,
    and nothing checked that they described the same world - a mismatched pair surfaced as a raw KeyError
    from the placement check or as a coverage error blaming an Ordering that had done nothing wrong. One
    argument cannot disagree with itself."""

    @final
    def arrange(self, ordering: Ordering, graph: Graph) -> Partition:
        graph.demand()   # the hard-presence rule, fired the moment membership is final
        partition = self.shape(ordering, graph)
        self.__covers(partition, graph.steps)
        partition.verify(graph)   # every shape, since every shape has a real placement rule
        return partition

    @final
    def _apart(self, into: type[Partition], groups: tuple[tuple[Step, ...], ...], graph: Graph) -> tuple[tuple[Step, ...], ...]:
        """Re-seat so that no two steps contending for one resource are ever in flight together.

        WHICH WAY TO MOVE THEM IS DERIVED, not declared. The shape already publishes its placement rule,
        and Partition.overlap derives WHERE it overlaps straight off that rule. A wave overlaps WITHIN one
        group so rivals are pushed into different groups, a chain is serial inside and overlaps ACROSS
        groups so rivals are pulled into the same one, while a serial walk overlaps NEITHER so there is
        nothing to move. A shape that ships tomorrow answers the same question the day it states its rule.

        Contention is not an edge and this is where that stops being a slogan. The seating moves, the Graph
        does not. No arrow is invented, so foresee() still forecasts the real prerequisites, Enclosure still
        sees the real boundaries, so the drawing still shows the declaration rather than the schedule."""
        rivals: dict[str, list[Step]] = {}   # label -> the steps that named it, in seated order
        for group in groups:
            for step in group:
                for label in sorted(step.contends):
                    rivals.setdefault(label, []).append(step)
        if not any(len(named) > 1 for named in rivals.values()):
            return groups
        # Read the overlap OFF the shape, never re-derived here: Partition.overlap is the one home that
        # turns a placement rule into where the shape overlaps in flight. This used to duplicate its
        # two probes by hand - the same fact spoken twice, one edit away from disagreeing.
        overlap = into(()).overlap
        if overlap is Overlap.ACROSS:
            return self.__pulled(groups, rivals)
        if overlap is Overlap.WITHIN:
            return self.__pushed(groups, graph)
        return groups

    @staticmethod
    def __pulled(groups: tuple[tuple[Step, ...], ...], rivals: dict[str, list["Step"]]) -> tuple[tuple[Step, ...], ...]:
        # Chains overlap ACROSS groups, so rivals must share one. Merging two chains is sound because chains
        # are independent by construction. No edge crosses them, so concatenating preserves every within-chain
        # order and creates no new obligation. Union by the group each rival sits in, then concatenate in
        # seated order so the merged chain still reads as the walk it was built from.
        home = {step: index for index, group in enumerate(groups) for step in group}
        merged = list(range(len(groups)))

        def root(index: int) -> int:
            while merged[index] != index:
                merged[index] = merged[merged[index]]
                index = merged[index]
            return index

        for named in rivals.values():
            for other in named[1:]:
                first, second = root(home[named[0]]), root(home[other])
                if first != second:
                    merged[second] = first
        gathered: dict[int, list[Step]] = {}
        for index, group in enumerate(groups):
            gathered.setdefault(root(index), []).extend(group)
        return tuple(tuple(group) for group in gathered.values())

    @staticmethod
    def __pushed(groups: tuple[tuple[Step, ...], ...], graph: Graph) -> tuple[tuple[Step, ...], ...]:
        # A wave overlaps INSIDE one group, so rivals must sit in different waves. Every step takes the
        # EARLIEST wave that is both past all its dependencies and free of anything it contends with, walking
        # the groups in the order the Ordering already resolved. Sound by construction rather than by
        # argument. A step is never seated below its dependency's wave plus one, which is exactly the rule
        # WavesPartition verifies, so the search terminates because a fresh wave is always free.
        seated: dict[Step, int] = {}
        taken: dict[int, set[str]] = {}
        for original_wave_index, group in enumerate(groups):
            for step in group:
                for edge in graph.dependencies(step):
                    if edge not in seated:
                        raise Seating(
                            f"{Step.named(step)} depends on {Step.named(edge)}, yet the Ordering "
                            f"yielded it first. An Ordering must return steps in a valid topological order."
                        )
                wave = max(original_wave_index, max((seated[edge] + 1 for edge in graph.dependencies(step)), default=0))
                while step.contends & taken.get(wave, set()):
                    wave += 1
                seated[step] = wave
                taken.setdefault(wave, set()).update(step.contends)
        waves: dict[int, list[Step]] = {}
        for step, wave in seated.items():
            waves.setdefault(wave, []).append(step)
        return tuple(tuple(waves[wave]) for wave in sorted(waves))

    @abstractmethod
    def shape(self, ordering: Ordering, graph: Graph) -> Partition:
        # Turn the Ordering into the Partition this shape stands for, nothing else. The guards around it
        # are arrange()'s, so an implementation here is exactly the shape and never the ceremony.
        ...

    @staticmethod
    def __covers(partition: Partition, steps: tuple[Step, ...]) -> None:
        # Guard against an Ordering that drops or duplicates a step. verify() checks only WHERE a dependency
        # sits. This checks the partition still holds EXACTLY the supplied steps, each once (by identity), so a
        # waves()/chains() that silently loses or repeats one cannot converge a smaller or doubled world. A
        # Scope typo already fails loudly and a broken Ordering now does too.
        placed = [step for group in partition for step in group]
        if sorted(map(id, placed)) != sorted(map(id, steps)):
            raise Coverage(
                f"Ordering placed {len(placed)} steps but was given {len(steps)}: it must return every "
                f"supplied step exactly once, dropping and duplicating none."
            )


class BaseFan(Arranger):
    """Shared machinery for the two built-in fanning shapes, Waves and Chains. Reject a flat Ordering as a
    class before running (the unbound override check against the ABC names no concrete strategy), build the
    shape from the groups the Ordering produces, then verify the placement upfront. Each concrete shape
    supplies only the atoms that genuinely differ - the Partition it builds, the Ordering verb that feeds
    it, what that verb's flat fallback looks like, why fanning that fallback is wrong and the built-in
    Ordering to reach for - while the rejection sentence is assembled here ONCE, so the two shapes cannot
    drift apart in form. It names ITSELF in the rejection (its class name doubles as the shape noun), so
    the message is self-contained with no dispatcher identity threaded in.

    The fence. This base fans over the verbs the Ordering contract ships - waves() and chains() - since its
    flat-fallback probe reads them off the shipped ABC. A shape that builds a DIFFERENT Partition from one of
    those verbs subclasses this base and passes `into=`, which is the supported route for a custom Partition.
    A genuinely NEW shape (one no Ordering verb feeds) implements Arranger directly and gets the same guards,
    since they live in arrange() rather than in anything a subclass writes."""

    def __init__(self, into: type[Partition], via: str, fallback: str, consequence: str, use: str):
        self.__into = into                 # the Partition subclass this shape builds: WavesPartition or ChainsPartition
        self.__via = via                   # the Ordering verb that feeds it, "waves" or "chains"
        self.__fallback = fallback         # what that verb's flat fallback looks like, named in the rejection
        self.__consequence = consequence   # why fanning that fallback is wrong, the rejection's reasoning
        self.__use = use                   # the built-in Ordering that genuinely fans this shape

    @override
    def shape(self, ordering: Ordering, graph: Graph) -> Partition:
        if getattr(type(ordering), self.__via) is getattr(Ordering, self.__via):
            fanned = self.__class__.__name__.lower()   # Waves fans waves, Chains fans chains: the name IS the noun
            raise Pairing(
                f"{self.__class__.__name__} needs an Ordering that splits steps into independent {fanned}, yet "
                f"{ordering.__class__.__name__} only yields {self.__fallback} from {self.__via}(), which "
                f"{self.__consequence}. Use {self.__use}."
            )
        return self.__into(self._apart(self.__into, getattr(ordering, self.__via)(graph), graph))


@final
class Waves(BaseFan):
    """Fans an Ordering into independent topological waves - Kahn's waves, each a wave of mutually independent
    steps in dependency order - and verifies the placement upfront. The shape the wave dispatchers
    Parallel and Supervised compose. The barrier between waves holds every declared edge. Rejects a flat Ordering (one that only
    yields the waves() fallback), which fanned out would ignore the declared edges. Use Kahn."""

    @override
    def __init__(self) -> None:
        super().__init__(
            into=WavesPartition, via="waves",
            fallback="a flat order",
            consequence="fanned out would ignore the declared edges",
            use="Kahn",
        )


@final
class Chains(BaseFan):
    """Fans an Ordering into independent dependency chains - Components' chains, each run in series, the chains
    mutually independent - and verifies the placement upfront. The chain dual of Waves. A dispatcher
    composing it fans the chains and runs each in series, where Waves fans within a wave. No shipped
    dispatcher composes it today - the seam stays open for a custom chain-runner. Rejects a flat Ordering
    (one that only yields the single-chain fallback), which fanned would run nothing concurrently.
    Use Components."""

    @override
    def __init__(self) -> None:
        super().__init__(
            into=ChainsPartition, via="chains",
            fallback="one chain of everything",
            consequence="fanned would run nothing concurrently",
            use="Components",
        )


@final
class Walk(Arranger):
    """The serial-safe shape. No fan. It walks a partition - real waves from Kahn,
    the one-wave fallback from DFS/Components - in order, one step at a time, honouring every declared edge. The
    shape a serial custom dispatcher composes to inherit the covers-guarded walk without reimplementing
    it."""

    @override
    def shape(self, ordering: Ordering, graph: Graph) -> Partition:
        # A WalkPartition, not a WavesPartition. The groups are the same tuples, yet the RULE differs -
        # nothing here runs at once, so a dependency may share a group with its dependent as long as it
        # comes first in the walk, which is what a serial walk actually does.
        # Through _apart like every other shape, though a serial walk overlaps nothing and it always hands
        # the groups straight back. Uniform on purpose. The day a custom Partition is walked serially, the
        # contention question is already asked of it rather than skipped because Walk was special.
        return WalkPartition(self._apart(WalkPartition, ordering.waves(graph), graph))

