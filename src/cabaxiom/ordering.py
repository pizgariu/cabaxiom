"""Ordering strategies - sequence Steps along the Graph's derived edges: Kahn (readiness waves), DFS (depth-first flat), Priority (best-first flat), Components (independent chains)."""
import heapq
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable
from graphlib import CycleError, TopologicalSorter
from typing import final, override

from .errors import Cycle
from .graph import Graph
from .step import Step


class Ordering(ABC):
    # Strategy interface for sequencing steps. A Reconciler is handed ONE Ordering and the arranger feeds
    # every verb the run's Graph - the kernel's one derivation over every edge kind (`expects`, `requires`, `prepares` and `mandates`
    # on kinds, `wants` and `demands` on capabilities, `uses` and `needs` on instances) - so the algorithm can be
    # swapped without touching converge logic.
    #
    # The Graph is the WHOLE input, deliberately. It carries the post-scope membership as graph.steps
    # alongside the edges derived over exactly that membership, so no strategy can be handed a set and a
    # derivation that disagree. The two used to travel as separate arguments, which made their agreement a
    # convention every custom Ordering had to keep rather than a fact of the type.
    #
    # Contract for every implementation. Order graph.steps by graph.dependencies(), which is keyed by
    # INSTANCE (so two steps of one class can be ordered relative to each other, while a step with no edge
    # stays in supplied order) and raise ValueError on a cycle. The hard-presence rule is NOT the
    # strategy's job. The sealed arrange() fires graph.demand() before any verb runs, so no implementation can forget it.
    @abstractmethod
    def __call__(self, graph: Graph) -> tuple[Step, ...]:
        ...

    def waves(self, graph: Graph) -> tuple[tuple[Step, ...], ...]:
        # Topological WAVES. Each inner tuple is a wave of mutually-independent steps, waves in dependency
        # order. Default is ONE wave equal to the flat __call__ order. A level-capable ordering overrides.
        return (self(graph),)

    def chains(self, graph: Graph) -> tuple[tuple[Step, ...], ...]:
        # Topological CHAINS. Dual of waves(). Each inner tuple is one chain run in series, the chains
        # mutually independent so a chain-fanning dispatcher runs them concurrently. Default is ONE chain of the
        # whole flat order, the sentinel the Chains arranger rejects since it runs nothing concurrently.
        # A chain-capable ordering overrides.
        return (self(graph),)

    @staticmethod
    def _cycle(nodes: Iterable[Step]) -> Cycle:
        # The one wording for a dependency cycle or unsatisfiable order, naming each stuck step's class once in
        # cycle order. Nodes are step instances (from graphlib's CycleError or DFS's recursion path). Two
        # instances of one class collapse to one name.
        path = " -> ".join(Step.named(node) for node in nodes)
        return Cycle(f"Step dependency cycle or unsatisfiable order: {path}")

    @staticmethod
    def _prepared(graph: Graph) -> TopologicalSorter[Step]:
        # Build the handed Graph into a PREPARED TopologicalSorter, the shared foundation the graph-walking
        # strategies stand on: Kahn drains it into waves, Priority pops it by key. Raises ValueError via
        # _cycle on a cycle, so each caller just walks a ready sorter.
        sorter: TopologicalSorter[Step] = TopologicalSorter()
        for step in graph.steps:
            sorter.add(step, *graph.dependencies(step))
        try:
            sorter.prepare()
        except CycleError as cycle:
            raise Ordering._cycle(cycle.args[1]) from cycle
        return sorter


@final
class Kahn(Ordering):
    """Default Ordering. Topological sort over the instance graph via stdlib graphlib.TopologicalSorter (Kahn)."""

    def __init__(self) -> None:
        # Declared and empty on purpose. This axis IS a callable, so a class that leaves its
        # constructor implicit reads as an invocation of `__call__` to a tool resolving
        # `Kahn()` and the strategy that takes nothing is exactly the one that cannot say so any
        # other way. Stating it is the whole point.
        super().__init__()

    @override
    def __call__(self, graph: Graph) -> tuple[Step, ...]:
        # Flat linear order. The waves flattened. Kahn's waves come out in the order static_order() would, so
        # the flat order is just waves() drained, while the cycle check lives once, in _prepared.
        return tuple(step for wave in self.waves(graph) for step in wave)

    @override
    def waves(self, graph: Graph) -> tuple[tuple[Step, ...], ...]:
        # Real waves. Drain the prepared sorter round by round via get_ready/done. Ready steps come out in
        # supplied order and flattening the waves equals the flat __call__ order above.
        sorter = Ordering._prepared(graph)
        waves = []
        while sorter.is_active():
            ready = sorter.get_ready()
            waves.append(tuple(ready))
            sorter.done(*ready)
        return tuple(waves)


@final
class DFS(Ordering):
    """Swap-in alternative to Kahn. Same result contract, a different (still valid) order on branching
    graphs. Recurses into a node's deps and emits post-order, one chain to the bottom before siblings, so it
    agrees with Kahn on a linear chain but differs on a diamond. Fully iterative to survive deep
    dependency chains (e.g., 200,000 steps) without hitting Python's recursion limit."""

    def __init__(self) -> None:
        # Declared and empty on purpose. This axis IS a callable, so a class that leaves its
        # constructor implicit reads as an invocation of `__call__` to a tool resolving
        # `DFS()` and the strategy that takes nothing is exactly the one that cannot say so any
        # other way. Stating it is the whole point.
        super().__init__()

    @override
    def __call__(self, graph: Graph) -> tuple[Step, ...]:
        # Three-state vertex colouring. A node is unvisited (in neither set), visiting (on `onstack`, its
        # subtree still open) or done. `onstack` is an O(1) mirror of the recursion path, so a cycle is a
        # constant-time membership test, not an O(depth) scan. `stack` carries the path itself, walked once
        # only when a cycle is found, to name it in order.
        done: set[Step] = set()
        onstack: set[Step] = set()
        order: list[Step] = []

        for root in graph.steps:
            if root in done:
                continue
            stack = [(root, iter(graph.dependencies(root)))]
            onstack.add(root)

            while stack:
                node, deps = stack[-1]
                try:
                    dep = next(deps)
                    if dep in done:
                        continue
                    if dep in onstack:
                        path = [item[0] for item in stack]
                        cycle_start = path.index(dep)
                        raise self._cycle(path[cycle_start:] + [dep])
                    onstack.add(dep)
                    stack.append((dep, iter(graph.dependencies(dep))))
                except StopIteration:
                    stack.pop()
                    onstack.remove(node)
                    done.add(node)
                    order.append(node)

        return tuple(order)


@final
class Priority(Ordering):
    """Best-first Ordering. The ready set is a PRIORITY QUEUE, so at each step the ready step with the
    smallest key is emitted next. The key maps a Step CLASS to a sort key and is injected. The default is
    the class name (reproducible output independent of input) or pass a domain priority to run more
    important ready steps first. Flat-only like DFS. It yields no waves() to fan, so no wave dispatcher
    can drive it - it orders a custom serial walk."""

    @staticmethod
    def __by_class_name(step_class: type) -> str:
        # Default key - lexicographic by class name, a canonical order independent of input. A staticmethod,
        # not a module-level function. It belongs to Priority, nothing else reads it.
        return step_class.__name__

    def __init__(self, key: Callable[[type], object] | None = None):
        # Resolved via None so no shared default leaks across instances. The key sees the Step CLASS, never
        # an instance.
        self.__key = key or Priority.__by_class_name

    @override
    def __call__(self, graph: Graph) -> tuple[Step, ...]:
        # Kahn with a PRIORITY-QUEUE frontier (heapq). Pop the ready step with the smallest key, emit it,
        # unlock its dependents, repeat. The heap tuple carries an integer tiebreak so equal keys keep
        # first-ready order and the step is never compared. RAISE ValueError on a cycle, naming the stuck steps.
        sorter = Ordering._prepared(graph)
        frontier: list[tuple[object, int, Step]] = []   # min-heap of (key, tiebreak, step): the ready set as a priority queue
        tiebreak = 0                                    # stable order for equal keys, keeps a non-comparable key from comparing steps
        order = []
        ready = sorter.get_ready()
        while ready or frontier:
            for step in ready:
                heapq.heappush(frontier, (self.__key(type(step)), tiebreak, step))
                tiebreak += 1
            _, _, step = heapq.heappop(frontier)
            order.append(step)
            sorter.done(step)
            ready = sorter.get_ready()
        return tuple(order)


@final
class Components(Ordering):
    """Chain-capable Ordering for a chain-fanning dispatcher. Partitions the steps into weakly-connected
    components (maximal groups with no dependency edge crossing between them), each component internally in
    Kahn topological order. The components share no edge so they are mutually independent, letting a
    dispatcher composing Chains run each as its own serial chain with all chains concurrent - no shipped
    dispatcher does today, the seam stays open for a custom chain-runner. The flat __call__ concatenates
    the components into a valid topological order.

    Weakly-connected components, not a minimum path cover. Path-cover chains still share edges (a diamond's
    two sides both depend on the fork and feed the join), so running them concurrently would ignore those
    edges. A component is the largest group genuinely independent of every other."""

    @override
    def __call__(self, graph: Graph) -> tuple[Step, ...]:
        return tuple(step for chain in self.chains(graph) for step in chain)

    def __init__(self) -> None:
        # Declared and empty on purpose. This axis IS a callable, so a class that leaves its
        # constructor implicit reads as an invocation of `__call__` to a tool resolving
        # `Components()` and the strategy that takes nothing is exactly the one that cannot say so
        # any other way. Stating it is the whole point.
        super().__init__()

    @override
    def chains(self, graph: Graph) -> tuple[tuple[Step, ...], ...]:
        # The Graph owns the SPLIT (union-find over the derived edges), this strategy owns the ORDER within
        # each split. Every component is edge-closed by the Graph's construction, so its members sort over
        # exactly their own dependencies with nothing crossing in or out. Component order and
        # within-component order both follow supplied order, so the outcome is deterministic.
        chains = []
        for component in graph.components():
            sorter: TopologicalSorter[Step] = TopologicalSorter()
            for step in component:
                sorter.add(step, *graph.dependencies(step))
            try:
                chains.append(tuple(sorter.static_order()))
            except CycleError as cycle:
                raise self._cycle(cycle.args[1]) from cycle
        return tuple(chains)

