"""Vocabulary - the dependency edge kinds as DATA. One record per kind and every consumer reads it.

The kernel used to spell its edge kinds into six different places - the Graph's derivation, its per-name
matching(), the softness read on a Match, the presence rule in demand(), the drawing's styling table and
the Explanation's declaration mappings each enumerated the slots by hand. Adding a hypothetical seventh
kind broke all six. The worst of them did not fail - Match.soft answered FALSE for a soft slot, the
flag a Rift's quieted channel votes on. Meanwhile the Graph promised "a new edge kind lands in the
derivation and nowhere else". This module is what makes that sentence true. The next kind is ONE ROW HERE.
"""
from abc import ABC, abstractmethod
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, ClassVar, cast, final, overload, override

# Step is imported for TYPING ONLY and every annotation below quotes it, because step.py imports THIS module at
# module level while Step.__init_subclass__ reads Vocabulary.shipped() at every subclass definition - including
# the ones the package defines while it is still importing. This module therefore has to finish importing before
# step.py does. A module-level `from .step import Step` here closes that cycle - measured, the whole package
# stops importing with `cannot import name 'Step' from partially initialized module`.
#
# MIGRATION, when the floor rises to 3.14: PEP 649 evaluates annotations lazily, so the quotes around "Step" become
# unnecessary and can come off in one sweep. This guard itself STAYS, since the name still must not be bound at
# import time. What must NOT go with the quotes are the three function-local imports in Instance below (admits,
# found and shown). Those need the CLASS OBJECT for isinstance, which no annotation rule can supply, so deleting
# them turns a broken cycle back into a NameError at the first instance edge.
if TYPE_CHECKING:
    from .step import Step


class Addressing(ABC):
    """HOW a declared name addresses what it means - by class, by label or by instance - as a
    strategy rather than a string tag. Everything that differs between
    the three shapes a name can take - the lookup that resolves it, the words a refusal speaks about it,
    the type an element must be and how a declared name reads on a page - differs BY CURRENCY and
    nowhere else. Five consumers used to dispatch on a string for it, each with its own if-chain. The
    dispatch is polymorphism now, so each singleton below is the whole answer for its shape.

    Not an Enum, deliberately: OnError is an Enum because its members are pure LABELS a policy branches
    on, while an addressing's members each carry different BEHAVIOUR - an Enum with methods would put the
    same if-chain back, just centralised. Three stateless singletons are the Strategy pattern's honest
    form of that."""

    __slots__ = ()

    # The refusal vocabulary - what a slot of this addressing takes, how a stray of it is named in somebody
    # else's slot, what an element must BE and the hard-kind nouns a demand() refusal composes with.
    takes: ClassVar[str]
    stray: ClassVar[str]
    noun: ClassVar[str]
    vow: ClassVar[str]
    # Whether the edge leans on an intermediary (a capability reaches its steps THROUGH providers), which
    # is the one semantic the drawing renders differently - a soft indirect lean is dashed.
    indirect: ClassVar[bool]

    @abstractmethod
    def admits(self, name: object) -> bool:
        # Is this a value of MY shape? The vetting question, asked polymorphically - exposing an
        # `expected` type instead would force this module to import Step at module level, which the
        # step module (minting the shipped language at class definition) cannot allow back.
        ...

    @abstractmethod
    def found(self, name: object, instances: Mapping[type["Step"], Sequence["Step"]],
              providers: Mapping[str, Sequence["Step"]]) -> tuple["Step", ...]:
        # THE lookup - what a declared name resolves to. Total - an absent name is an empty match, never
        # an error. The narrows inside the implementations are for the type checker, not from doubt:
        # the Graph vets every element through admits() before it ever resolves one.
        ...

    @abstractmethod
    def shown(self, names: Sequence[object], labels: Mapping["Step", str]) -> tuple[str, ...]:
        # How this addressing's declared names read on a structural page - a kind by its class name, a
        # capability by its label, an instance by its per-run label, present ones only.
        ...

    @abstractmethod
    def spoken(self, name: object) -> str:
        # How ONE declared name reads in a sentence, present or not - a class by its own name, a capability
        # quoted so it cannot be read as a class, an instance by its class name. Match.label and demand()
        # both speak names and each used to carry this dispatch as its own if-chain. One home now.
        ...

    @abstractmethod
    def absent(self, named: str) -> str:
        # The middle of a hard-kind refusal - what exactly is missing when a name of this addressing
        # matched nothing.
        ...


@final
class _ByClass(Addressing):
    __slots__ = ()
    takes = "step CLASSES"
    stray = "A step class"
    noun = "dependency"
    vow = "demands its presence"
    indirect = False

    @override
    def admits(self, name: object) -> bool:
        return isinstance(name, type)

    @override
    def found(self, name: object, instances: Mapping[type["Step"], Sequence["Step"]],
              providers: Mapping[str, Sequence["Step"]]) -> tuple["Step", ...]:
        return tuple(instances.get(cast("type[Step]", name), ())) if isinstance(name, type) else ()

    @override
    def shown(self, names: Sequence[object], labels: Mapping["Step", str]) -> tuple[str, ...]:
        return tuple(named.__name__ for named in names if isinstance(named, type))

    @override
    def spoken(self, name: object) -> str:
        return name.__name__ if isinstance(name, type) else repr(name)

    @override
    def absent(self, named: str) -> str:
        return f"but no {named} is in the run"


@final
class _ByLabel(Addressing):
    __slots__ = ()
    takes = "capability labels"
    stray = "A capability label"
    noun = "capability"
    vow = "insists on a provider"
    indirect = True

    @override
    def admits(self, name: object) -> bool:
        return isinstance(name, str)

    @override
    def found(self, name: object, instances: Mapping[type["Step"], Sequence["Step"]],
              providers: Mapping[str, Sequence["Step"]]) -> tuple["Step", ...]:
        return tuple(providers.get(name, ())) if isinstance(name, str) else ()

    @override
    def shown(self, names: Sequence[object], labels: Mapping["Step", str]) -> tuple[str, ...]:
        return tuple(name for name in names if isinstance(name, str))

    @override
    def spoken(self, name: object) -> str:
        return repr(name)

    @override
    def absent(self, named: str) -> str:
        return "but no step in the run provides it"


@final
class _ByInstance(Addressing):
    __slots__ = ()
    takes = "step INSTANCES"
    stray = "A step instance"
    noun = "instance"
    vow = "demands its presence"
    indirect = False

    @override
    def admits(self, name: object) -> bool:
        # This one survives every annotation reform, PEP 649 included - isinstance takes the class, not the name.
        from .step import Step  # late on purpose: step mints the shipped language at class definition,
        return isinstance(name, Step)   # so the cycle breaks here, where the name is needed at runtime

    @override
    def found(self, name: object, instances: Mapping[type["Step"], Sequence["Step"]],
              providers: Mapping[str, Sequence["Step"]]) -> tuple["Step", ...]:
        from .step import Step
        return (name,) if isinstance(name, Step) and name in instances.get(type(name), ()) else ()

    @override
    def shown(self, names: Sequence[object], labels: Mapping["Step", str]) -> tuple[str, ...]:
        from .step import Step
        # Two if clauses rather than one `and`. Sequential filters narrow the name to Step before the
        # subscript reads it, where a compound condition leaves the union standing in a checker that does
        # not split `and` inside a comprehension. Same semantics either way. Only one of them is readable
        # to every tool.
        return tuple(labels[name] for name in names if isinstance(name, Step) if name in labels)

    @override
    def spoken(self, name: object) -> str:
        return name.__class__.__name__

    @override
    def absent(self, named: str) -> str:
        return "but that instance is not in the run"


@final
class Roster(Sequence["Step"]):
    """WHO is in the run, of one step class, in supplied order - a sequence that can also be ASKED.

    A plain list answers both questions and answers the second one in linear time, `step in instances[cls]`
    walks the list. On a chain of N steps of one class that is N scans of up to N entries, so the whole
    derivation is quadratic. A 200000 step chain took a hundred seconds where the ordering it feeds took
    a third of one. The order is not negotiable (it is the fan order every class-addressed edge lands in and
    the run has to be deterministic), so the membership gets its own index instead."""

    __slots__ = ("__held", "__present")

    def __init__(self, held: Sequence["Step"]):
        self.__held = tuple(held)
        self.__present = frozenset(self.__held)

    @overload
    def __getitem__(self, position: int) -> "Step": ...
    @overload
    def __getitem__(self, position: slice) -> Sequence["Step"]: ...
    @override
    def __getitem__(self, position: int | slice) -> "Step | Sequence[Step]":
        if isinstance(position, slice):
            return self.__held[position]
        return self.__held[position]

    @override
    def __len__(self) -> int:
        return len(self.__held)

    @override
    def __contains__(self, wanted: object) -> bool:
        return wanted in cast(Any, self.__present)

    @override
    def __iter__(self) -> Iterator["Step"]:
        return iter(self.__held)


# The three singletons plus the tuple a refusal hint walks to say where a stray belongs instead.
BY_CLASS: Addressing = _ByClass()
BY_LABEL: Addressing = _ByLabel()
BY_INSTANCE: Addressing = _ByInstance()
MODES: tuple[Addressing, ...] = (BY_CLASS, BY_LABEL, BY_INSTANCE)


@final
@dataclass(frozen=True)
class EdgeKind:
    """One kind of dependency edge, as a VALUE OBJECT - the Type Object pattern. The KINDS of edge are
    data, so consumers iterate a table instead of hardcoding a vocabulary, while growing the language is
    adding a row rather than editing everyone who speaks it.

    A frozen dataclass, NOT a NamedTuple. A Seat is a tuple because its lexicographic order IS the walk
    rule, yet an EdgeKind's tuple-ness would be accidental API - indexable, sliceable, equal to any stray
    six-tuple - and none of that is contract. Value equality and hashing stay, the accidents go, frozen
    already refuses a stray attribute as it refuses a rewrite. The value GUARDS ITSELF. The
    element-level invariants live here at construction, one gate earlier than the Vocabulary's
    collection-level ones. (No hand-written __slots__, unlike DriftItem. A defaulted field stores its
    default as a class attribute, which __slots__ cannot coexist with - `precedes` defaults for every
    shipped row, so five records a process do not need the memory discipline a Drift stream does.)

    `slot` is the Step attribute the declaration is read from. `addressing` is the strategy that resolves,
    vets, renders and speaks for a declared name of this kind (see Addressing). `hard` is the presence
    rule: a soft kind trusts an absent match (a dead end, never an error), a hard one raises at resolution
    through Graph.demand(). `counterpart` names the other-hardness twin, so a refusal can say "unlike
    `expects`..." without anyone re-learning the pairing. `colour` is the kind's one hue, which the diagram
    styles per hardness and indirection - the vocabulary knows no drawing syntax, only that a kind has a
    colour of its own. `precedes` is the DIRECTION: False (the shipped default) means declaring puts THIS
    step after the match, True reverses it - the match comes after the declaring step, which is what a
    `before` kind is, for the domain that cannot edit the step it must precede."""

    slot: str
    addressing: Addressing
    hard: bool
    counterpart: str | None
    colour: str
    precedes: bool = False

    def __post_init__(self) -> None:
        # The invariants ONE row can check about itself - what needs the whole table (duplicate slots,
        # counterpart mutuality) stays the Vocabulary's construction guard.
        if not self.slot.isidentifier():
            raise ValueError(f"EdgeKind slot {self.slot!r} is not an identifier, so no Step could declare it")
        if self.counterpart == self.slot:
            raise ValueError(f"EdgeKind `{self.slot}` names itself as its counterpart - a twin is another kind")

    @classmethod
    def paired(cls, soft: str, hard: str, addressing: Addressing, *,
               trusting: str, insisting: str, precedes: bool = False) -> tuple["EdgeKind", "EdgeKind"]:
        # The soft-and-hard twins minted TOGETHER, counterparts wired both ways over one addressing - the
        # composed form in which a mispairing cannot be written, where two hand-built rows cross-naming
        # each other by string could. The Vocabulary still validates hand-built rows, yet a pair built
        # here is right by construction. `trusting` colours the soft twin (it trusts an absent match),
        # `insisting` the hard one (it refuses to run without one).
        return (cls(soft, addressing, hard=False, counterpart=hard, colour=trusting, precedes=precedes),
                cls(hard, addressing, hard=True, counterpart=soft, colour=insisting, precedes=precedes))


@final
class Vocabulary:
    """The edge kinds ONE RUN speaks - an ordered, validated collection of EdgeKind rows, injected like
    every other axis - `Reconciler(steps, vocabulary=...)` - with the shipped table as the default a run
    gets when it says nothing. Never registered. The kernel holds no global mutable state, so two
    reconcilers in one process cannot share a vocabulary by accident, no import can grow somebody else's
    language, so resolution cannot depend on import order.

    Row order is DERIVATION ORDER - the order prerequisites accumulate before the dedup - so the table is
    load-bearing, not alphabetical.

    Construction VALIDATES, the fail-at-construction doctrine. A duplicate slot, a slot that is not an
    identifier or a counterpart that is missing, one-sided, differently addressed or equally hard is
    refused with the fix in the sentence. A slot shadowing a Step verb needs no rule here. The Graph's
    container vet refuses `apply` the moment it reads a method where a tuple must be. `grown()` is how a
    domain extends the shipped language without mutating anything."""

    __slots__ = ("__kinds",)

    def __init__(self, *kinds: EdgeKind):
        if not kinds:
            raise ValueError("Vocabulary needs at least one edge kind - an empty language is ill-defined")
        slots = [kind.slot for kind in kinds]   # each row vetted itself at construction, a VO's own gate
        if len(set(slots)) != len(slots):
            twice = next(slot for index, slot in enumerate(slots) if slot in slots[:index])
            raise ValueError(f"Vocabulary declares the slot `{twice}` twice - one kind per slot, one row each")
        by_slot = {kind.slot: kind for kind in kinds}
        for kind in kinds:
            if kind.counterpart is None:
                continue
            twin = by_slot.get(kind.counterpart)
            if twin is None:
                raise ValueError(
                    f"`{kind.slot}` names `{kind.counterpart}` as its counterpart, yet no such kind is in "
                    f"this vocabulary - a pairing must name a row that exists."
                )
            if twin.counterpart != kind.slot or twin.addressing is not kind.addressing or twin.hard == kind.hard:
                raise ValueError(
                    f"`{kind.slot}` and `{kind.counterpart}` do not pair: counterparts must name each "
                    f"other, share one addressing and differ in hardness - the soft one trusts what the "
                    f"hard one refuses."
                )
        self.__kinds = kinds

    def __iter__(self) -> Iterator[EdgeKind]:
        return iter(self.__kinds)

    def __len__(self) -> int:
        return len(self.__kinds)

    def slots_for(self, addressing: Addressing) -> str:
        # The slots of THIS language that take a given addressing, joined the way a sentence lists them -
        # so a refusal telling a caller where a stray name belongs can never omit a slot the vocabulary
        # grew and never name one this run does not speak.
        return " or ".join(f"`{kind.slot}`" for kind in self.__kinds if kind.addressing is addressing)

    def grown(self, *kinds: EdgeKind) -> "Vocabulary":
        # This language plus a domain's own rows, as a NEW vocabulary - validated whole, mutating
        # nothing, which is the only growth a zero-global-state kernel can offer.
        return Vocabulary(*self.__kinds, *kinds)

    @classmethod
    def shipped(cls) -> "Vocabulary":
        # The language a run speaks when it says nothing, COMPOSED where it is asked for rather than held
        # as a module table. The kernel's defaults are answered by the class that owns them, never
        # published as a constant lying beside it. The soft-and-hard
        # pairs are minted as pairs, so the table the docs teach cannot be written mispaired.
        return cls(
            *EdgeKind.paired("expects", "requires", BY_CLASS, trusting="#4c6ef5", insisting="#e03131"),
            *EdgeKind.paired("prepares", "mandates", BY_CLASS, trusting="#20c997", insisting="#087f5b", precedes=True),
            *EdgeKind.paired("wants", "demands", BY_LABEL, trusting="#2f9e44", insisting="#e8590c"),
            *EdgeKind.paired("uses", "needs", BY_INSTANCE, trusting="#7048e8", insisting="#5f3dc4"),
        )

