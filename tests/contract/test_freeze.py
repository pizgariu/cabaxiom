"""The 1.x promise, held by the suite rather than by whoever reviews the next minor.

MIGRATING.md promises that the forty-three names `cabaxiom` exports keep their place, their signatures and
their meaning for the whole 1.x line. Before this file the suite pinned only how MANY names the door holds,
so swapping one name for another, dropping a keyword or changing a default all passed green.

The table below is the door as 1.0.0 shipped it. HARDCODED on purpose, like the published doors in
test_layers. Deriving it from the tree would let the tree rewrite its own promise.

What a minor may still do is grow. A new name on the door, a new member on a frozen class, a new parameter
after the recorded ones as long as it has a default. Anything else that turns this file red is a 2.0.0
conversation. Annotations are left out because they render differently across the supported interpreters.
What a caller writes is the name, the kind and the default. That is what is held."""
import enum
import inspect
import unittest

import cabaxiom

_FROZEN = {
    "Artifacts": "alias",
    "Assessment": {
        "__init__": "(deviation=(), plan=(), advisory=(), footprint=())",
        "advisory": "attribute",
        "deviation": "attribute",
        "footprint": "attribute",
        "plan": "attribute",
    },
    "AsyncFlowAssessment": "alias",
    "AsyncFlowOutcome": "alias",
    "Cancellation": {
        "__init__": "()",
        "cancelled": "()",
    },
    "Cancelled": ("BaseException",),
    "Changes": "alias",
    "Coverage": ("Unresolvable", "ValueError", "Exception", "BaseException"),
    "Cycle": ("Unresolvable", "ValueError", "Exception", "BaseException"),
    "DataFlow": ("Unresolvable", "ValueError", "Exception", "BaseException"),
    "Deadline": {
        "__init__": "(seconds)",
        "cancelled": "()",
    },
    "Deferred": ("BaseException",),
    "Drift": {
        "__init__": "(*args, **kwargs)",
        "message": "property",
        "name": "property",
    },
    "DriftItem": {
        "__init__": "(name, message)",
        "message": "attribute",
        "name": "attribute",
    },
    "Exponential": {
        "__init__": "(base, cap)",
        "delay": "(stalled)",
        "wait": "(stalled)",
    },
    "Fault": "alias",
    "Fixed": {
        "__init__": "(seconds)",
        "delay": "(stalled)",
        "wait": "(stalled)",
    },
    "Fixpoint": {
        "__init__": "(max_passes=10, kw backoff=None)",
        "deciding": "()",
        "opening": "()",
        "passes": "()",
    },
    "Flag": {
        "__init__": "()",
        "cancel": "()",
        "cancelled": "()",
    },
    "FlowAssessment": "alias",
    "FlowOutcome": "alias",
    "Graph": {
        "__init__": "(steps, vocabulary=None)",
        "closure": "(seeds)",
        "components": "()",
        "demand": "()",
        "dependencies": "(step)",
        "dependents": "(step)",
        "fallout": "(seeds)",
        "matching": "(step)",
        "steps": "property",
        "vocabulary": "property",
    },
    "Identity": ("Unresolvable", "ValueError", "Exception", "BaseException"),
    "Kahn": {
        "__init__": "()",
        "chains": "(graph)",
        "flat": "(graph)",
        "waves": "(graph)",
    },
    "Ledger": {
        "__init__": "(groups, on_error, observer, graph)",
        "admit": "(level)",
        "assemble": "(step)",
        "blocked": "(step)",
        "groups": "property",
        "halt": "(culprit)",
        "mounted": "(step, prerequisites, produced)",
        "outcome": "()",
        "record": "(step, produced, artifacts, exception)",
    },
    "Malformed": ("TypeError", "Exception", "BaseException"),
    "Misconfigured": ("ValueError", "Exception", "BaseException"),
    "Observer": {
        "__init__": "()",
        "acted": "(applied)",
        "began": "()",
        "dispatching": "(step, inputs)",
        "produced": "(step, artifacts)",
        "pruned": "(residual)",
        "remained": "(residual)",
        "retried": "(step, attempt, error)",
        "stepped": "(step, changes, error)",
    },
    "OnError": {"FailFast": "FailFast", "BestEffort": "BestEffort", "Halt": "Halt"},
    "Pairing": ("Unresolvable", "ValueError", "Exception", "BaseException"),
    "Parallel": {
        "__init__": "(on_error=OnError.FailFast)",
        "dispatcher": "property",
        "resolve": "(ordering, graph)",
    },
    "Presence": ("Unresolvable", "ValueError", "Exception", "BaseException"),
    "Reading": {
        "__init__": "(deviations, produced=None, plan=(), advisory=(), footprint=())",
        "advisory": "property",
        "count": "(value)",
        "footprint": "property",
        "gathered": "(answered)",
        "index": "(value, start=0, stop=None)",
        "plan": "property",
        "produced": "property",
    },
    "Reconciler": {
        "__init__": "(steps, ordering=None, kw scope=None, kw mode=None, kw convergence=None, kw cancellation=None, kw observer=None, kw retry=None, kw vocabulary=None, kw authority=None, kw warrant=None)",
        "assess": "()",
        "converge": "()",
        "explain": "()",
        "foresee": "(step)",
        "prune": "()",
        "watch": "()",
    },
    "Residual": {
        "__init__": "(residual, kw failures=(), kw applied=(), kw produced=None, kw vetoed=())",
        "applied": "property",
        "converged": "(residual, kw failures, kw applied, kw produced)",
        "count": "(value)",
        "failures": "property",
        "index": "(value, start=0, stop=None)",
        "produced": "property",
        "pruned": "(statement)",
        "refused": "(reasons, kw beside, kw produced)",
        "vetoed": "property",
    },
    "Retry": {
        "__init__": "(attempts, kw backoff=None)",
        "around": "(do, kw observer=None)",
        "retryable": "(step, attempt, error)",
    },
    "Seating": ("Unresolvable", "ValueError", "Exception", "BaseException"),
    "Serial": {
        "__init__": "(on_error=OnError.FailFast)",
        "dispatcher": "property",
        "resolve": "(ordering, graph)",
    },
    "Skew": ("BaseException",),
    "Step": {
        "__init__": "(*args, **kwargs)",
        "advised": "(*told, kw produced=None)",
        "apply": "(inputs)",
        "assess": "(inputs)",
        "changed": "(*made, kw produced=None)",
        "consumes": "attribute",
        "contends": "attribute",
        "demands": "attribute",
        "drifted": "(*found, kw produced=None)",
        "expects": "attribute",
        "identifier": "property",
        "labelled": "(steps)",
        "leases": "attribute",
        "mandates": "attribute",
        "named": "(step)",
        "needs": "attribute",
        "owns": "(*held, kw produced=None)",
        "paired": "(previous, desired)",
        "prepares": "attribute",
        "produces": "attribute",
        "provides": "attribute",
        "prune": "(inputs)",
        "requires": "attribute",
        "tags": "attribute",
        "unchanged": "(kw produced=None)",
        "uses": "attribute",
        "verified": "(kw produced=None)",
        "wants": "attribute",
        "watch": "()",
    },
    "Supervised": {
        "__init__": "(on_error=OnError.FailFast, kw poll=0.05, kw grace=1.0)",
        "dispatcher": "property",
        "resolve": "(ordering, graph)",
    },
    "Unresolvable": ("ValueError", "Exception", "BaseException"),
    "Vocabulary": {
        "__init__": "(*kinds)",
        "grown": "(*kinds)",
        "shipped": "()",
        "slots_for": "(addressing)",
    },
}

_KIND = {
    inspect.Parameter.POSITIONAL_ONLY: "/",
    inspect.Parameter.POSITIONAL_OR_KEYWORD: "",
    inspect.Parameter.VAR_POSITIONAL: "*",
    inspect.Parameter.KEYWORD_ONLY: "kw ",
    inspect.Parameter.VAR_KEYWORD: "**",
}


class TheFrozenDoor(unittest.TestCase):

    def test_every_frozen_name_is_still_on_the_door(self):
        self.assertEqual(len(_FROZEN), 43)
        for name in sorted(_FROZEN):
            with self.subTest(name=name):
                self.assertIn(name, cabaxiom.__all__, f"{name} is frozen for 1.x and left the door")

    def test_a_frozen_class_keeps_every_member_with_its_parameters(self):
        for name, members in self._shaped(dict, keyed=True):
            shipped = getattr(cabaxiom, name)
            for member, shape in members.items():
                with self.subTest(name=name, member=member):
                    self.assertTrue(member == "__init__" or hasattr(shipped, member), f"{name}.{member} is frozen and gone")
                    now = self._shape(shipped, member)
                    if not shape.startswith("("):
                        self.assertEqual(now, shape, f"{name}.{member} was a {shape}")
                        continue
                    self._grows_only(f"{name}.{member}", shape[1:-1], now[1:-1])

    def test_a_frozen_enum_keeps_its_members_and_their_values(self):
        for name, members in self._shaped(dict, keyed=False):
            shipped = getattr(cabaxiom, name)
            for member, value in members.items():
                with self.subTest(name=name, member=member):
                    self.assertEqual(shipped[member].value, value)

    def test_a_frozen_refusal_is_still_caught_by_everything_it_was_caught_by(self):
        for name, bases in self._shaped(tuple, keyed=False):
            caught = {base.__name__ for base in getattr(cabaxiom, name).__mro__}
            with self.subTest(name=name):
                self.assertLessEqual(set(bases), caught, f"an except clause written for {name} stops catching it")

    def _shaped(self, kind, *, keyed):
        for name, shape in sorted(_FROZEN.items()):
            if not isinstance(shape, kind):
                continue
            if kind is dict and keyed != ("__init__" in shape):
                continue
            yield name, shape

    def _shape(self, shipped, member):
        if member == "__init__":
            return f"({self._parameters(shipped)})"
        raw = inspect.getattr_static(shipped, member)
        if isinstance(raw, property):
            return "property"
        if isinstance(raw, (staticmethod, classmethod)) or inspect.isfunction(raw):
            return f"({self._parameters(getattr(shipped, member))})"
        return "attribute"

    def _parameters(self, callable_):
        parameters = list(inspect.signature(callable_).parameters.values())
        if parameters and parameters[0].name in ("self", "cls"):
            parameters = parameters[1:]
        return ", ".join(f"{_KIND[p.kind]}{p.name}{self._default(p)}" for p in parameters)

    def _default(self, parameter):
        if parameter.default is parameter.empty:
            return ""
        if isinstance(parameter.default, enum.Enum):
            return f"={type(parameter.default).__name__}.{parameter.default.name}"
        return f"={parameter.default!r}"

    def _grows_only(self, where, shipped, now):
        before = shipped.split(", ") if shipped else []
        after = now.split(", ") if now else []
        self.assertEqual(after[:len(before)], before, f"{where} changed a parameter it shipped with")
        for added in after[len(before):]:
            with self.subTest(added=added):
                self.assertTrue("=" in added or added.startswith("*"), f"{where} grew {added} without a default")
