"""Scope - which of the handed steps take part in a run. Everything by default or Only / Skip by step type."""
from typing import TYPE_CHECKING, final

from ._compat import override
from .errors import Misconfigured
from .step import Step

if TYPE_CHECKING:
    from .graph import Graph


class Scope:
    """Which of the handed steps take part in a run. The Reconciler resolves the scope once at
    construction, so every verb (the reads, converge, prune) sees the same set. The base keeps
    everything, so a reconciler with no scope behaves as if the seam were not there. Only and
    Skip narrow the set by step type, which is the currency the caller writes at the call site.

    Every scope is handed the run's whole Graph rather than a bare tuple of steps, so it narrows along
    the same derivation everything else reads. What a scope may not do is narrow a run into one the
    derivation refuses and the hard-presence rule says so with the scope named.
    """

    def select(self, graph: "Graph") -> tuple[Step, ...]:
        # The base keeps every step, which is the run-everything default.
        return graph.steps


class _Named(Scope):
    # Shared plumbing for the scopes that name step types. The selection cannot be empty and every
    # named type must match a step actually handed in, so a typo fails loudly at construction
    # instead of silently converging a smaller world than asked for.
    def __init__(self, *step_types: type[Step]):
        if not step_types:
            raise Misconfigured(f"{type(self).__name__} needs at least one step type - an empty scope is ill-defined")
        self._types = step_types

    def _verify_present(self, steps: tuple[Step, ...]) -> None:
        present = {type(step) for step in steps}
        missing = [named.__name__ for named in self._types if named not in present]
        if missing:
            raise ValueError(
                f"{type(self).__name__} names step types with no step in the run: {', '.join(missing)}. "
                f"A scope chooses among the steps the Reconciler was handed, nothing else."
            )


@final
class Only(_Named):
    """Keep the named step types plus the transitive dependencies of each, in the handed order.

    A targeted run must stay a correct run - a target converging before its prerequisites would trust
    state nobody put there. So Only grows its selection along the DERIVATION until it closes, the way a
    targeted apply pulls in what its target depends on.

    Along the derivation and not along one slot, which is the defect this closes. It walked `expects` by
    hand, so a target that named a capability, an instance or a hard prerequisite had those edges narrowed
    away - the run was assembled without something it had explicitly declared, yet nothing said so because
    a soft edge to an absent step is legal."""

    @override
    def select(self, graph: "Graph") -> tuple[Step, ...]:
        steps = graph.steps
        self._verify_present(steps)
        seeds = tuple(step for step in steps if type(step) in self._types)
        kept = graph.closure(seeds)      # the seeds plus every transitive prerequisite, in any kind
        return tuple(step for step in steps if step in kept)


@final
class Skip(_Named):
    """Drop exactly the named step types and keep everything else, with no cascade.

    A dependent of a skipped step still runs, as long as it wanted that step SOFTLY. A soft edge orders
    the steps present and does not demand their presence, so skipping a soft prerequisite means trusting
    the world already satisfies it, which is precisely what the caller asked for.

    A HARD edge is the other half of that sentence and the reason this scope cannot be a blind filter.
    `requires`, `mandates`, `demands` and `needs` each say the world must contain the thing, so dropping
    what answers one of them produces a run the caller declared to be wrong. That is refused, so the
    refusal names the scope rather than the declaration, because the declaration was right."""

    @override
    def select(self, graph: "Graph") -> tuple[Step, ...]:
        steps = graph.steps
        self._verify_present(steps)
        return tuple(step for step in steps if type(step) not in self._types)
