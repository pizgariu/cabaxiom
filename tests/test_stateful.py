"""Stateful tests: across any interleaving of perturbation and reconcile, converge reaches a drift-free fixpoint and is idempotent."""
from hypothesis import HealthCheck, settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, precondition, rule

from cabaxiom import DriftItem, Fixpoint, Reconciler, Step

_DESIRED = "desired"


class _Managed(Step):
    # Owns one key of a shared world dict and drives it to _DESIRED. Drift is the gap between the two.
    def __init__(self, world, key):
        self._world = world
        self._key = key

    def drift(self) -> list:
        return [] if self._world.get(self._key) == _DESIRED else [DriftItem(str(self._key), "stale")]

    def apply(self) -> None:
        self._world[self._key] = _DESIRED


class ReconcilerMachine(RuleBasedStateMachine):
    # The reconciler as a state machine over a mutable world. Any interleaving of register, perturb and
    # reconcile must keep the self-verifying contract intact. Converge drives every managed key to desired,
    # and a second converge on a settled world changes nothing.
    def __init__(self):
        super().__init__()
        self._world: dict = {}
        self._steps: dict = {}

    @rule(key=st.integers(min_value=0, max_value=4))
    def register(self, key):
        # A step's existence declares that its key must be desired. A freshly registered key starts settled.
        if key not in self._steps:
            self._steps[key] = _Managed(self._world, key)
        self._world[key] = _DESIRED

    @rule(key=st.integers(min_value=0, max_value=4), value=st.text(max_size=4))
    def perturb(self, key, value):
        # Drag a key off desired, managed or not. `value` is at most 4 chars, so it never equals _DESIRED.
        self._world[key] = value

    @precondition(lambda self: self._steps)
    @rule()
    def reconcile(self):
        steps = tuple(self._steps.values())
        Reconciler(steps, convergence=Fixpoint()).converge()
        for step in steps:
            assert step.drift() == [], "converge left a managed key off desired"
        settled = dict(self._world)
        Reconciler(steps, convergence=Fixpoint()).converge()
        assert self._world == settled, "a second converge changed a settled world"


TestReconcilerMachine = ReconcilerMachine.TestCase
TestReconcilerMachine.settings = settings(
    max_examples=50, stateful_step_count=15, deadline=None,
    suppress_health_check=[HealthCheck.differing_executors],
)
