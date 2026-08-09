"""Property-based tests: invariants of the algorithmic core hold across generated graphs, not just picked cases."""
import unittest

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from cabaxiom import DriftItem, Fixpoint, Kahn, Parallel, Reconciler, Step


@st.composite
def dependency_graphs(draw, max_nodes=6):
    # A random DAG of Step types. Node i may depend on any subset of {0..i-1}, which keeps the graph acyclic
    # by construction. Returns edges, where edges[i] is the sorted list of dependency indices of node i.
    n = draw(st.integers(min_value=0, max_value=max_nodes))
    edges = []
    for i in range(n):
        edges.append(sorted(draw(st.sets(st.integers(min_value=0, max_value=i - 1))) if i else set()))
    return edges


def _build(edges, log):
    # One fresh Step subclass per node, its `after` wired to the classes of its dependencies (built first,
    # since a dependency has a lower index). apply() records the step name so a test can read the run order.
    classes = []
    for index, deps in enumerate(edges):
        after = tuple(classes[d] for d in deps)
        classes.append(type(f"S{index}", (Step,), {
            "after": after,
            "apply": lambda self, _log=log: _log.append(type(self).__name__),
        }))
    return [cls() for cls in classes]


class OrderingProperties(unittest.TestCase):
    @settings(deadline=None, suppress_health_check=[HealthCheck.differing_executors])
    @given(dependency_graphs())
    def test_kahn_applies_every_dependency_before_its_dependent(self, edges):
        # The core ordering invariant. Whatever the DAG, no step runs before something it declares in `after`.
        log: list[str] = []
        Reconciler(_build(edges, log)).converge()   # Serial executor, Kahn ordering, both defaults
        position = {name: i for i, name in enumerate(log)}
        for index, deps in enumerate(edges):
            for dep in deps:
                self.assertLess(position[f"S{dep}"], position[f"S{index}"])

    @settings(deadline=None, suppress_health_check=[HealthCheck.differing_executors])
    @given(dependency_graphs())
    def test_parallel_accepts_every_dag_kahn_resolves(self, edges):
        # Kahn's waves are always safe to fan out. For any DAG, arrange plus verify under Parallel never rejects.
        with Parallel() as executor:
            Reconciler(_build(edges, []), Kahn(), executor=executor)


class ConvergenceProperties(unittest.TestCase):
    @settings(deadline=None, suppress_health_check=[HealthCheck.differing_executors])
    @given(st.integers(min_value=1, max_value=25))
    def test_fixpoint_never_exceeds_max_passes(self, max_passes):
        # Termination guarantee. A step that never settles is applied exactly max_passes times, never more.
        applies: list[int] = []

        class NeverSettles(Step):
            def apply(self) -> None:
                applies.append(1)

            def drift(self) -> list:
                return [DriftItem("n", f"pass {len(applies)}")]   # a fresh message each pass, so it never settles

        Reconciler((NeverSettles(),), convergence=Fixpoint(max_passes=max_passes)).converge()
        self.assertEqual(len(applies), max_passes)
