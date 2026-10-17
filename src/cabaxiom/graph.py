"""The Graph - the kernel-owned home of the dependency structure. Every edge kind derived once. Every
question the kernel asks of that structure (invert it, close over it, split it) answered in one place."""
from collections import defaultdict
from collections.abc import Callable, Iterable, Sequence
from typing import final

from .errors import DataFlow, Identity, Malformed, Presence
from .step import Step
from .vocabulary import MODES, EdgeKind, Roster, Vocabulary

# The three shapes a declared name takes. A step CLASS (`expects`, `requires`, `prepares`, `mandates`), a
# capability LABEL (`wants`, `demands`) or a step INSTANCE (`uses`, `needs`). One alias, because every per-name read carries it.
type Declared = type[Step] | str | Step

@final
class Match:
    """One declared name and the present steps it resolved to - the derivation's per-NAME view, misses
    included.

    dependencies() answers what a step comes AFTER. The resolved edges, deduplicated across every name that
    reached them. A name that matched NOTHING contributes no edge, so it is invisible there - and a miss is
    real structure, not the absence of it. It is a soft name trusting the world to have done the work
    already, a prerequisite a narrowing scope just dropped or an edge a transition is about to take
    away. This record is the shape that can say so. The slot the name was declared in, the name itself and
    the match set the same lookups the derivation runs found for it, empty or not.

    `soft` reads the slot. `expects`, `prepares`, `wants` and `uses` trust an absent name, while `requires`,
    `mandates`, `demands` and `needs` do not (demand() raises on their misses once membership is final), so only a soft miss is silent.

    A RECORD, like every value the kernel mints. The match set is captured as a tuple behind read-only
    properties, so a caller cannot rewrite what a derivation found."""

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
        # The kind RECORD itself, so a consumer that needs more than the slot name (the addressing, the
        # hardness, the counterpart) reads the vocabulary's own row instead of re-learning it.
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
        # Read off the kind's own record, never a hardcoded name list. This used to spell the three soft
        # slots as a literal tuple, so a NEW soft kind would have answered False here - the flag a Rift's
        # quieted channel votes on, wrong without a sound. The vocabulary is the one place that knows.
        return not self.__kind.hard

    @property
    def label(self) -> str:
        # The declared name in words - the addressing's dispatch, not an if-chain here. A capability quoted
        # so it cannot be read as a class, a step class by its own name, a step instance by its class name.
        return self.__kind.addressing.spoken(self.__name)

    def __repr__(self) -> str:
        matched = ", ".join(Step.named(step) for step in self.__matched) or "nothing"
        return f"Match({Step.named(self.__step)}.{self.__kind.slot} {self.label} -> {matched})"


@final
class Graph:
    """The dependency structure of ONE step set, derived once and asked many ways - the Ledger's twin on
    the dependency axis. Where the Ledger owns what a run RECORDED, the Graph owns what a run is MADE OF:
    which step comes after which, resolved from every edge kind the vocabulary declares - `expects` and
    `requires` on kinds, fanned to every present instance of the named class (`prepares` and `mandates`
    writing the same edge the other way around), `wants` and `demands` on capabilities, fanned to every
    present provider. And `uses` and `needs` on instances - keyed by instance, scoped to the supplied
    set, duplicates collapsed in first-seen order.

    Derivation is TOTAL. An edge naming something absent is a dead end, never an error, so every consumer
    reads the same structure - a targeted scope growing its closure mid-narrowing, a partition checking
    placements, a ledger blocking a failure's dependents. The one presence rule lives apart as demand(),
    the guard the arranger fires on the post-scope set before any Ordering verb runs - `requires` or
    `mandates` naming an absent class, `demands` naming an unprovided capability or `needs` naming a
    missing instance, raises THERE - absence is only an
    error once the run's final membership is known.

    Construction VETS the declarations first. A value in the wrong slot (a label in `expects`, a class in
    `uses`) is a programming error rather than an absence. It raises a TypeError naming the slot the stray
    belongs in - so an untyped domain hears at build time what a typed one hears from mypy, instead of a
    wrong-shaped key silently matching nothing.

    Immutable in contract, lazy in computation. The forward edges are derived at construction. The
    inversion is built on the first dependents() ask and cached - a run that never asks pays nothing. The
    per-name read matching() is lazier still and keeps nothing at all, since the tables it consults outlive
    the derivation for demand() anyway."""

    def __init__(self, steps: Iterable[Step], vocabulary: Vocabulary | None = None):
        # The language this derivation speaks, injected like every axis and defaulting to the shipped
        # table - resolved via None so no shared default leaks, the kernel's rule for injected defaults.
        # Against None and not for truthiness, though a Vocabulary is never empty. `or` would work only
        # because the Vocabulary constructor refuses an empty language. A default that quietly leans
        # on a guard three modules away is a default that changes meaning when that guard moves.
        self.__vocabulary = Vocabulary.shipped() if vocabulary is None else vocabulary
        self.__steps = tuple(steps)
        for step in self.__steps:
            self.__vet(step, self.__vocabulary)
        # HASHABILITY FIRST, because the guard below cannot run without it and the commonest way to break
        # identity breaks this too. A bare @dataclass takes eq=True, which writes __eq__ AND sets
        # __hash__ to None, so building the set two lines down raised a bare `unhashable type` from inside
        # the derivation - naming no step, no cause and no fix, for the exact decorator the guard beneath
        # was written to catch. The sentence has to be said before the set is built or it is never said.
        for step in self.__steps:
            if step.__class__.__hash__ is None:
                raise Identity(
                    f"{step.__class__.__name__} is not hashable, so this run cannot address it at all. A "
                    f"Step's identity IS the kernel's dependency addressing. A bare @dataclass drops __hash__ "
                    f"when it writes __eq__, so take eq=False and keep value semantics on a field object instead."
                )
        present = set(self.__steps)
        # The identity guard's second half, for what the class-definition hook cannot see. A decorator
        # like dataclass(eq=True) rewrites __eq__ AFTER Step.__init_subclass__ ran. Two value-equal steps
        # collapse into one hash key here and every table below would quietly derive a smaller world -
        # the failure used to surface as a coverage error blaming the Ordering. The same instance handed
        # twice is the OTHER way the counts diverge, so the two get their own sentences.
        if len(present) != len(self.__steps):
            identities = {id(step) for step in self.__steps}
            if len(identities) < len(self.__steps):
                twice = next(step for index, step in enumerate(self.__steps) if step in self.__steps[:index])
                raise Identity(
                    f"{Step.named(twice)} was handed to this run twice. A step is one concern with one "
                    f"identity, so declare a second instance instead of repeating the first."
                )
            collapsed = next(step for index, step in enumerate(self.__steps) if step in set(self.__steps[:index]))
            raise Identity(
                f"Two distinct {collapsed.__class__.__name__} instances compare EQUAL, so they would collapse "
                f"into one graph node and the run would derive a smaller world. A Step's identity is the "
                f"kernel's dependency addressing. Drop the __eq__ (a dataclass takes eq=False) and keep "
                f"value semantics on a field object instead."
            )
        gathered_by_class: defaultdict[type[Step], list[Step]] = defaultdict(list)
        providers: defaultdict[str, list[Step]] = defaultdict(list)
        for step in self.__steps:
            gathered_by_class[type(step)].append(step)
            for capability in step.provides:   # instance-read, like tags: a step may provide per instance
                providers[capability].append(step)
        self.__instances = {kind: Roster(held) for kind, held in gathered_by_class.items()}
        self.__providers = providers
        # ONE loop over the vocabulary, not one hand-written loop per slot. A kind edge fans to every
        # present instance, a capability edge to every present provider, an instance edge to its own
        # presence - and WHICH of those a slot means is the record's addressing, so the next edge kind is
        # a row in the vocabulary and not an edit here. Row order is derivation order, then the dedup
        # keeps first-seen. A PRECEDES kind writes the edge the other way around - the match comes after
        # the declaring step - and those contributions land after a step's own declarations, in supplied
        # order of whoever declared them, so the outcome stays deterministic.
        gathered: dict[Step, list[Step]] = {step: [] for step in self.__steps}
        for step in self.__steps:
            for kind in self.__vocabulary:
                for name in getattr(step, kind.slot, ()):
                    for found in self.__found(kind, name):
                        if kind.precedes:
                            gathered[found].append(step)
                        else:
                            gathered[step].append(found)
        self.__edges = {step: tuple(dict.fromkeys(mine)) for step, mine in gathered.items()}
        self.__inverted: dict[Step, tuple[Step, ...]] | None = None   # built on the first dependents() ask

    def __found(self, kind: EdgeKind, name: Declared) -> tuple[Step, ...]:
        # THE lookup, answered by the kind's own addressing - a strategy, not a string compared three
        # times. Total by construction (an absent name is an empty match, never an error) and shared by
        # the derivation and by matching(), so the two views cannot disagree about what a name found.
        return kind.addressing.found(name, self.__instances, self.__providers)

    @staticmethod
    def __vet(step: Step, vocabulary: Vocabulary) -> None:
        # The declaration guard. Every slot takes exactly one shape. A value in the wrong slot is a
        # programming error, never a dead end - the silent kind of wrong the one home exists to refuse.
        # Driven by the registry, so a new edge kind arrives already vetted. The addressing says what an
        # element must BE. The belongs-elsewhere hint is composed from the OTHER currencies' slots,
        # which is exactly the sentence that used to be spelled by hand three times. Vetted here per
        # INSTANCE (the class-definition guard cannot see an instance assignment), the identity
        # contract's own two-gate doctrine.
        for kind in vocabulary:
            declared = getattr(step, kind.slot, ())
            if not isinstance(declared, tuple):
                raise TypeError(
                    f"{Step.named(step)}.{kind.slot} must be a tuple of {kind.addressing.takes}, got "
                    f"{declared.__class__.__name__}. A single entry still needs a trailing comma - "
                    f"write {kind.slot} = (entry,)."
                )
            for name in declared:
                if not kind.addressing.admits(name):
                    first, second = (other for other in MODES if other is not kind.addressing)
                    raise Malformed(
                        f"{Step.named(step)} names {name!r} in `{kind.slot}`, which takes "
                        f"{kind.addressing.takes}. {first.stray} belongs in {vocabulary.slots_for(first)} and "
                        f"{second.stray.lower()} in {vocabulary.slots_for(second)}."
                    )
        # The label SETS, vetted the same way for the same reason. A bare string is the silent one - it
        # iterates into single characters, so `provides = "database"` would offer six capabilities named
        # d, a, t, b, s and e. Every match would miss without a word.
        for slot, noun in (("provides", "capability labels"), ("produces", "artifact keys"),
                           ("consumes", "artifact keys")):
            declared = getattr(step, slot)
            if isinstance(declared, str):
                raise Malformed(
                    f"{Step.named(step)}.{slot} must be a set of {noun}, got the string {declared!r}. "
                    f"Wrap it - {slot} = frozenset({{{declared!r}}})."
                )
            for label in declared:
                if not isinstance(label, str):
                    raise Malformed(
                        f"{Step.named(step)} names {label!r} in `{slot}`, which takes {noun}."
                    )

    @property
    def vocabulary(self) -> Vocabulary:
        # The language this derivation spoke, published for the same reason as `steps`. explain() renders
        # the declarations and the drawing styles the arrows BY the run's own kinds, so handing either a
        # different vocabulary than the derivation used would be the two-arguments disease again.
        return self.__vocabulary

    @property
    def steps(self) -> tuple[Step, ...]:
        # The membership this derivation was built over, in supplied order - the run's final set, since a
        # Graph is only ever derived once the scope has spoken. PUBLISHED because every consumer needs both
        # the set and the edges over it. Handing those down as two arguments made their correspondence
        # the caller's discipline. A graph of one world passed alongside the steps of another surfaced as a
        # raw KeyError inside a placement check or as a coverage error blaming the Ordering for a fault
        # that was never its own. Read from here they cannot disagree.
        return self.__steps

    def dependencies(self, step: Step) -> tuple[Step, ...]:
        # Everything this step declared it comes after, resolved to present instances in first-seen order.
        # The read every consumer shares. An Ordering feeds it to its sorter, a partition checks each entry's
        # placement, a closure walks it - so a new edge kind lands in the derivation above and nowhere else.
        return self.__edges[step]

    def matching(self, step: Step) -> tuple[Match, ...]:
        # The per-NAME twin of dependencies(). Every name this step declares, paired with what it matched -
        # the names that matched NOTHING included, which the edge view above cannot show, since a miss
        # contributes no edge and leaves no trace. The misses are the whole reason this read exists. A soft
        # name gone quiet, a leaning on the world, a fan-in that thinned are all invisible in the resolved
        # edges, since only this one home knows the lookups that produced them.
        #
        # It KEEPS NOTHING. It re-runs the same lookups against the same tables the derivation used, which
        # outlive it for demand() anyway - so the misses were never lost, only never surfaced. A run
        # that never asks pays nothing. The inversion's discipline, one step further.
        #
        # Deliberately NOT deduplicated, unlike the edge view. A provider reached by both `expects` and
        # `wants` is TWO declarations that both landed, so collapsing them would hide one.
        return tuple(
            Match(step, kind, name, self.__found(kind, name))
            for kind in self.__vocabulary
            for name in getattr(step, kind.slot, ())
        )

    def dependents(self, step: Step) -> tuple[Step, ...]:
        # The inversion. Every step that declared THIS one (directly or through its kind) as a prerequisite.
        # Built lazily on the first ask and cached - the Ledger only ever asks after a failure, so a clean
        # run never pays for the inversion at all.
        inverted = self.__inverted
        if inverted is None:
            gathered: defaultdict[Step, list[Step]] = defaultdict(list)
            for dependent, prerequisites in self.__edges.items():
                for prerequisite in prerequisites:
                    gathered[prerequisite].append(dependent)
            inverted = {prerequisite: tuple(dependents) for prerequisite, dependents in gathered.items()}
            self.__inverted = inverted
        return inverted.get(step, ())

    def closure(self, seeds: Iterable[Step]) -> frozenset[Step]:
        # The seeds plus every transitive PREREQUISITE - the walk a targeted scope needs, so a target never
        # converges before what it declared. Edges only lead to present steps (derivation is total), so the
        # closure stays inside this graph.
        return self.__reached(seeds, self.dependencies)

    def fallout(self, seeds: Iterable[Step]) -> frozenset[Step]:
        # The seeds plus every transitive DEPENDENT, closure() read the other way. Where closure() answers
        # what must converge BEFORE these, this answers what stands ON them and would be left holding
        # nothing if they failed. It grows along the inversion, so it pays for the inversion exactly as
        # every dependents() caller does, while a clean run never asks.
        #
        # ONE home, because its two callers must agree. The Ledger blames a failure's fallout under
        # BestEffort and the counterfactual read forecasts it. Written twice they could drift. The
        # forecast would quietly stop describing the handling.
        return self.__reached(seeds, self.dependents)

    @staticmethod
    def __reached(seeds: Iterable[Step], along: Callable[[Step], tuple[Step, ...]]) -> frozenset[Step]:
        # The seeds plus everything reachable from them, grown until nothing new joins. ONE walk, because
        # the two directions differ in nothing but the neighbours they follow. Closure() goes up the edges
        # and fallout() down the inversion. Written twice they would be two chances to get a frontier walk
        # subtly wrong, so the direction is the parameter and the walk is written once.
        reached = set(seeds)
        frontier = list(reached)
        while frontier:
            for neighbour in along(frontier.pop()):
                if neighbour not in reached:
                    reached.add(neighbour)
                    frontier.append(neighbour)
        return frozenset(reached)

    def components(self) -> tuple[tuple[Step, ...], ...]:
        # The weakly-connected split. Maximal groups with no edge crossing between them, the groups and the
        # steps within each in supplied order. Union-find with path halving over the derived edges - kept
        # HERE so the split and the edges it follows can never disagree, which is what lets a chain-fanning
        # consumer treat every component as edge-closed by construction.
        parent = {step: step for step in self.__steps}

        def root(node: Step) -> Step:
            while parent[node] is not node:
                parent[node] = parent[parent[node]]   # path halving
                node = parent[node]
            return node

        for step in self.__steps:
            for prerequisite in self.__edges[step]:
                parent[root(step)] = root(prerequisite)

        members: defaultdict[Step, list[Step]] = defaultdict(list)
        for step in self.__steps:
            members[root(step)].append(step)
        return tuple(tuple(members[component]) for component in dict.fromkeys(root(step) for step in self.__steps))

    def demand(self) -> None:
        # The hard-edge presence guard, deliberately apart from the (total) derivation. `requires` orders
        # exactly like `expects` and is already derived above, yet it additionally DEMANDS an instance of the
        # named class be present. The arranger fires this on the post-scope set - the moment membership is
        # final and before any Ordering verb runs, so no strategy can forget it - while consumers that
        # legitimately face absence (a scope mid-narrowing) read the derivation without tripping it.
        # The registry's HARD kinds, nothing named by hand. A new hard kind is a row in the
        # vocabulary and this guard enforces it unedited. The wording is composed from the record - the
        # counterpart is what the refusal contrasts against, the addressing picks the nouns.
        for step in self.__steps:
            for kind in self.__vocabulary:
                if not kind.hard:
                    continue
                for name in getattr(step, kind.slot, ()):
                    if self.__found(kind, name):
                        continue
                    named = kind.addressing.spoken(name)
                    raise Presence(
                        f"{Step.named(step)} {kind.slot} {named} {kind.addressing.absent(named)}. "
                        f"Unlike `{kind.counterpart}`, which trusts an absent {kind.addressing.noun}, "
                        f"`{kind.slot}` {kind.addressing.vow}."
                    )
            self.__supplied(step)

    def __supplied(self, step: Step) -> None:
        # THE DATA-PLANE RULE, the twin of the hard-edge one above and deliberately NOT an edge kind. A
        # declared key changes no order - the dependency plane says WHEN a step runs, this says only that
        # what it reads will actually be there - so the two planes stay separable and a step may still come
        # after another for reasons that carry no payload.
        #
        # It asks the DIRECT prerequisites and nothing wider, because that is exactly what the payload is
        # mounted from (Ledger.mounted merges the direct set). A producer sitting two hops upstream never
        # reaches this step's `inputs`, so counting it here would bless the very hole this refuses.
        consumed: frozenset[str] = getattr(step, "consumes", frozenset())
        if not consumed:
            return   # the common case pays one attribute read and stops
        upstream = self.dependencies(step)
        for key in sorted(consumed):
            if any(key in getattr(prerequisite, "produces", frozenset()) for prerequisite in upstream):
                continue
            elsewhere = [other for other in self.__steps if key in getattr(other, "produces", frozenset())]
            misplaced = (
                f" {Step.named(elsewhere[0])} produces it but is not a prerequisite of this step, so its "
                f"payload never reaches here - declare the edge that carries it."
                if elsewhere else
                " Nothing in this run produces it."
            )
            raise DataFlow(
                f"{Step.named(step)} consumes {key!r} and no prerequisite of it produces that key."
                f"{misplaced} A payload assembled from an absent key arrives as a default the hook cannot "
                f"tell from a real one, so the run would report clean against a world nobody supplied."
            )

