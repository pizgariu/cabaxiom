"""Ordering strategies - choose a run order THROUGH a derivation, never deriving one of your own.

Each strategy is handed the run's Graph and picks an order the edges allow. It does not read a slot, does
not know which kinds exist and cannot disagree with the seating guard or the scope about what depends on
what - because all three now read the same object. Before this, four strategies each walked the
declaration their own way and the walks had already drifted apart.

Keyed by INSTANCE. Two steps of one kind are two nodes that may sit in different places, which is what an
instance-addressed edge means and what a class-keyed sort could not express."""
import heapq
from abc import ABC, abstractmethod
from collections import defaultdict
from collections.abc import Callable
from graphlib import CycleError, TopologicalSorter
from typing import final

from ._compat import override
from .errors import Cycle
from .graph import Graph
from .step import Step


class Ordering(ABC):
    """Strategy for turning a derivation into a run order.

    __call__ is the flat order every strategy answers. levels() and chains() are the SHAPED answers, and
    a strategy that cannot shape its output that way inherits a one-group fallback rather than pretending
    - the shape's guard then refuses the pairing, which is the honest place for that refusal.

    Every verb takes the Graph ALONE. The membership travels ON the derivation, so a strategy cannot be
    handed the edges of one world beside the steps of another."""

    @abstractmethod
    def __call__(self, graph: Graph) -> tuple[Step, ...]:
        ...

    def levels(self, graph: Graph) -> tuple[tuple[Step, ...], ...]:
        # Readiness waves, for a dispatcher that fans within a group. The fallback is one group holding
        # the flat order, which is correct for a serial walk and refused by a fanning shape.
        return (self(graph),)

    def chains(self, graph: Graph) -> tuple[tuple[Step, ...], ...]:
        # Independent strands, for a dispatcher that fans across groups. Same fallback, same reason.
        return (self(graph),)

    @staticmethod
    def _sorted(graph: Graph, over: tuple[Step, ...] | None = None) -> "TopologicalSorter[Step]":
        # One sorter, over instances, fed from the derivation. Every strategy that topologically sorts
        # builds it here, so none of them can scope the edges differently from the others.
        #
        # The return annotation stays QUOTED through this rewrite, for the reason 0.3.1 quoted the one it
        # replaced - graphlib.TopologicalSorter only became subscriptable in 3.11, while a signature is
        # evaluated when the def runs, so unquoted it stops the package importing on 3.10.
        held = graph.steps if over is None else over
        within = set(held)
        sorter: TopologicalSorter[Step] = TopologicalSorter()
        for step in held:
            sorter.add(step, *(need for need in graph.dependencies(step) if need in within))
        return sorter

    @staticmethod
    def _apart(graph: Graph, wave: tuple[Step, ...]) -> tuple[tuple[Step, ...], ...]:
        # Splits ONE wave into as few consecutive waves as it takes for no wave to hold two rivals. Steps in
        # a wave are mutually independent by construction, so any split of one is still a legal ordering -
        # the split costs a barrier and buys the contention declaration, while a wave with no rivals in it
        # comes back as itself.
        #
        # Greedy first-fit, which is graph colouring and so not optimal in general. Optimal is NP-hard and
        # the prize is a wave or two of extra width, which is not worth an exponential search to a caller
        # who declared contention precisely because the resource is the bottleneck.
        rivals: defaultdict[Step, set[str]] = defaultdict(set)
        for label, contending in graph.contention().items():
            held = set(contending) & set(wave)
            if len(held) > 1:
                for step in held:
                    rivals[step].add(label)
        if not rivals:
            return (wave,)
        split: list[list[Step]] = []
        taken: list[set[str]] = []
        for step in wave:
            wants = rivals[step]
            seat = next((index for index, held in enumerate(taken) if held.isdisjoint(wants)), len(taken))
            if seat == len(taken):
                split.append([])
                taken.append(set())
            split[seat].append(step)
            taken[seat] |= wants
        return tuple(tuple(group) for group in split)

    @staticmethod
    def _stuck(cycle: CycleError) -> Cycle:
        named = ", ".join(dict.fromkeys(Step.named(step) for step in cycle.args[1]))
        return Cycle(f"Step dependency cycle or unsatisfiable order among: {named}")


@final
class Kahn(Ordering):
    """The default - a topological sort that also knows which steps are ready at the same time."""

    @override
    def __call__(self, graph: Graph) -> tuple[Step, ...]:
        # Flattened waves rather than a second sort. TopologicalSorter.static_order breaks ties its own
        # way, so asking it here would let the flat order disagree with the waves it is supposed to be.
        return tuple(step for wave in self.levels(graph) for step in wave)

    @override
    def levels(self, graph: Graph) -> tuple[tuple[Step, ...], ...]:
        # Real readiness waves. Everything with no unsettled prerequisite goes in one group. This is the
        # only strategy that answers this honestly, which is why it is the default for a fanning shape.
        sorter = self._sorted(graph)
        supplied = {step: index for index, step in enumerate(graph.steps)}
        waves: list[tuple[Step, ...]] = []
        try:
            sorter.prepare()
            while sorter.is_active():
                ready = sorter.get_ready()
                waves.append(tuple(sorted(ready, key=lambda step: supplied[step])))
                sorter.done(*ready)
        except CycleError as cycle:
            raise self._stuck(cycle) from cycle
        return tuple(split for wave in waves for split in self._apart(graph, wave))


@final
class DFS(Ordering):
    """Depth-first post-order - a prerequisite lands immediately before the step that needed it.

    Flat only. It answers no waves and no chains, so a fanning shape refuses to pair with it."""

    @override
    def __call__(self, graph: Graph) -> tuple[Step, ...]:
        ordered: list[Step] = []
        done: set[Step] = set()

        def visit(step: Step, path: tuple[Step, ...]) -> None:
            if step in done:
                return
            if step in path:
                named = ", ".join(dict.fromkeys(Step.named(held) for held in path + (step,)))
                raise Cycle(f"Step dependency cycle or unsatisfiable order among: {named}")
            for need in graph.dependencies(step):
                visit(need, path + (step,))
            done.add(step)
            ordered.append(step)

        for step in graph.steps:
            visit(step, ())
        return tuple(ordered)


def _by_name(step: Step) -> object:
    # The default priority is the step's own name, so the output is canonical rather than input-dependent.
    return Step.named(step)


@final
class Priority(Ordering):
    """Best-first - at each point the READY step with the smallest key runs next.

    Flat only, like DFS. The key is injected, so a domain orders its own way within what the edges allow."""

    def __init__(self, key: Callable[[Step], object] = _by_name):
        self.__key = key

    @override
    def __call__(self, graph: Graph) -> tuple[Step, ...]:
        sorter = self._sorted(graph)
        ordered: list[Step] = []
        frontier: list[tuple[object, int, Step]] = []
        tiebreak = 0                     # so equal keys keep first-ready order and a Step is never compared
        try:
            sorter.prepare()
            for step in sorter.get_ready():
                heapq.heappush(frontier, (self.__key(step), tiebreak, step))
                tiebreak += 1
            while frontier:
                _key, _tie, step = heapq.heappop(frontier)
                ordered.append(step)
                sorter.done(step)
                for freed in sorter.get_ready():
                    heapq.heappush(frontier, (self.__key(freed), tiebreak, freed))
                    tiebreak += 1
        except CycleError as cycle:
            raise self._stuck(cycle) from cycle
        return tuple(ordered)


@final
class Components(Ordering):
    """Independent strands - the run split into parts that share no edge, each internally in order.

    The split comes off the derivation rather than off one slot, so two steps joined by a capability are
    one component as surely as two joined by a class edge."""

    @override
    def __call__(self, graph: Graph) -> tuple[Step, ...]:
        return tuple(step for chain in self.chains(graph) for step in chain)

    @override
    def chains(self, graph: Graph) -> tuple[tuple[Step, ...], ...]:
        chains: list[tuple[Step, ...]] = []
        for component in graph.components():
            try:
                chains.append(tuple(self._sorted(graph, component).static_order()))
            except CycleError as cycle:
                raise self._stuck(cycle) from cycle
        return tuple(chains)
