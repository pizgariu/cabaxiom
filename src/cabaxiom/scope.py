"""Scope - which handed steps take part. Everything by default, Only / Skip by type, WithTag / WithoutTag by tag."""
from abc import ABC, abstractmethod
from typing import final, override

from .errors import Misconfigured, Presence
from .graph import Graph
from .step import Step


class Scope:
    """Which of the handed steps take part in a run. The Reconciler resolves the scope once at
    construction, so every verb (the reads, converge, prune) sees the same set. The base keeps
    everything, so a reconciler with no scope behaves as if the seam were not there. Only and
    Skip narrow the set by step type, which is how `expects` addresses its dependencies too.
    """

    def select(self, graph: Graph) -> Graph:
        # The run's language rides with the graph. A scope is an endofunctor (Graph -> Graph)
        # that transforms a base derivation into a narrowed one, inherently preserving the
        # single source of truth for the vocabulary.
        return graph


class BaseNamed(Scope, ABC):
    # Shared plumbing for the scopes that name step types. The selection cannot be empty and every named type
    # must match a step actually handed in. select() verifies that once, up front - a typo fails loudly at
    # construction instead of silently converging a smaller world - then hands off to the subclass's narrow(),
    # so no scope can forget the check or run it against an unverified set.
    def __init__(self, *step_types: type[Step]):
        if not step_types:
            raise Misconfigured(f"{self.__class__.__name__} needs at least one step type - an empty scope is ill-defined")
        self._types = step_types

    @final
    @override
    def select(self, graph: Graph) -> Graph:
        present = {type(step) for step in graph.steps}
        missing = [named.__name__ for named in self._types if named not in present]
        if missing:
            raise Presence(
                f"{self.__class__.__name__} names step types with no step in the run: {', '.join(missing)}. "
                f"A scope chooses among the steps the Reconciler was handed, nothing else."
            )
        return self.narrow(graph)

    @abstractmethod
    def narrow(self, graph: Graph) -> Graph:
        # Reduce the handed graph to this scope's subset. Presence of every named type is already verified.
        ...


@final
class Only(BaseNamed):
    """Keep the named step types plus the transitive dependencies of each, in the handed order.

    A targeted run must stay a correct run. A target converging before its prerequisites would
    trust state nobody put there. So Only grows its selection along every edge kind the Graph
    derives - `expects`, `requires`, `prepares` and `mandates` on kinds, `wants` and `demands` on
    capabilities, `uses` and `needs` on instances - until it closes, the way a targeted apply pulls in what its target depends on."""

    @override
    def narrow(self, graph: Graph) -> Graph:
        # Grow the selection until it closes, keeping the handed steps that made it in.
        # The Graph is already built, so we just ask it for its closure.
        targets = (step for step in graph.steps if type(step) in self._types)
        wanted = graph.closure(targets)

        # Maintain the original supplied order
        kept = tuple(step for step in graph.steps if step in wanted)
        return Graph(kept, graph.vocabulary)


@final
class Skip(BaseNamed):
    """Drop exactly the named step types and keep everything else, with no cascade.

    A dependent of a skipped step still runs. `expects` orders the steps present, it does not demand
    their presence (the kernel already ignores an expects-edge to an absent type), so skipping a
    prerequisite means trusting the world already satisfies it, which is precisely what the caller
    asked for."""

    @override
    def narrow(self, graph: Graph) -> Graph:
        kept = tuple(step for step in graph.steps if type(step) not in self._types)
        return Graph(kept, graph.vocabulary)


class BaseTagged(Scope, ABC):
    # Shared plumbing for the scopes that select on Step.tags, mirroring BaseNamed over tags instead of type:
    # the selection cannot be empty, every named tag must be carried by some handed step (a mistyped tag fails
    # loudly at construction instead of silently selecting nothing), while the tag-match filter runs once here.
    # The two directions differ ONLY in polarity - keep the matched steps or drop them - so each subclass sets
    # `keep` and nothing else.
    def __init__(self, *tags: str):
        if not tags:
            raise Misconfigured(f"{self.__class__.__name__} needs at least one tag - an empty scope is ill-defined")
        self._tags = frozenset(tags)

    @final
    @override
    def select(self, graph: Graph) -> Graph:
        # The axis hands EVERY scope the run's language via the graph itself.
        present: set[str] = set().union(*(step.tags for step in graph.steps))
        missing = sorted(tag for tag in self._tags if tag not in present)
        if missing:
            raise Presence(
                f"{self.__class__.__name__} names tags no step carries: {', '.join(missing)}. "
                f"A scope chooses among the steps the Reconciler was handed, nothing else."
            )
        # One walk, with the subclass saying what to keep - the tag-axis twin of narrow() owning the subset.
        kept = tuple(step for step in graph.steps if self.keeps(step.tags))
        return Graph(kept, graph.vocabulary)

    @abstractmethod
    def keeps(self, carried: frozenset[str]) -> bool:
        # Does a step carrying THESE tags belong in the run? The named tags are `self._tags`, already
        # verified present. PUBLIC, like every seam in the kernel, a METHOD rather than a declared
        # polarity flag. A flag admits exactly two answers and both already ship, so it could carry no new
        # scope at all, while a predicate carries any of them - `self._tags <= carried` is the conjunctive
        # scope the flag could never express. Being abstract also means ABCMeta refuses a subclass that
        # forgets it AND the bare base, which is a refusal a flag has no way to make.
        ...


@final
class WithTag(BaseTagged):
    """Keep only the steps carrying at least one of the named tags, dropping the rest.

    A pure filter along the tag axis, like Skip along the type axis. It does NOT pull in the dependencies
    of a kept step the way Only does. A kept step whose prerequisite was not tagged runs without it, trusting
    the world already satisfies it (`expects` orders the steps present, it does not demand their presence). Reach
    for Only when a run must stay dependency-closed."""

    @override
    def keeps(self, carried: frozenset[str]) -> bool:
        return bool(carried & self._tags)


@final
class WithEveryTag(BaseTagged):
    """Keep only the steps carrying EVERY named tag, the conjunction WithTag cannot express.

    Where `WithTag("prod", "network")` keeps a step wearing either label, this keeps only the ones wearing
    both - the intersection of two cross-cutting axes, say the network steps that are also production. It
    is the narrowest of the three tag scopes and, like the other two, a pure filter that pulls in no
    dependency of a kept step. Naming one tag makes it identical to WithTag, which is why the interesting
    case is two or more.

    Every named tag must still be carried by SOME handed step, exactly as the family's guard requires, so a
    typo fails loudly rather than selecting nothing. That check is about the DECLARATION being meaningful,
    not about any one step carrying them all."""

    @override
    def keeps(self, carried: frozenset[str]) -> bool:
        return self._tags <= carried


@final
class WithoutTag(BaseTagged):
    """Drop every step carrying any of the named tags, keep the rest, with no cascade.

    The tag-axis mirror of Skip. It excludes a cross-cutting group (say every "destructive" step) in one scope,
    however many types wear the tag. A dependent of a dropped step still runs, trusting the world satisfies
    what was excluded, exactly as Skip does."""

    @override
    def keeps(self, carried: frozenset[str]) -> bool:
        return not (carried & self._tags)

