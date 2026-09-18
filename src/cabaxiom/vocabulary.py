"""The edge language as DATA - what kinds of dependency a declaration may draw and how each is addressed.

Growing the language is adding a row here, not editing a derivation. Every consumer reads the table
rather than a slot name, so a kind added tomorrow is honoured by the ordering, the seating guard, the
scope closure and the drawing without any of them learning it exists."""
from abc import ABC, abstractmethod
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar, final, overload

from ._compat import override
from .errors import Misconfigured

if TYPE_CHECKING:                      # step.py imports THIS module while its own class body runs, so the
    from .step import Step  # step type may only ever be quoted here, never imported for real.


class Addressing(ABC):
    """HOW a slot names what it points at - by class, by capability label or by instance.

    Three axes of one question, kept apart because each answers differently at every point the kernel
    touches an edge - what a slot legally holds, how a name is matched against the run and how a refusal
    words itself. Bundling them into a flag would put three switch statements in three files."""

    __slots__ = ()

    takes: ClassVar[str]       # what a slot of this addressing legally holds, quoted in a refusal
    stray: ClassVar[str]       # how a wrongly-addressed value is named when it turns up in a slot
    noun: ClassVar[str]        # the noun a hard-presence refusal composes with
    indirect: ClassVar[bool]   # whether the edge reaches its target THROUGH an intermediary

    @abstractmethod
    def admits(self, name: object) -> bool:
        # Is this a legal thing to find in a slot addressed this way? Asked at declaration time, which is
        # the earliest moment a forgotten comma can be caught.
        ...

    @abstractmethod
    def found(self, name: object, instances: Mapping[type["Step"], Sequence["Step"]],
              providers: Mapping[str, Sequence["Step"]]) -> tuple["Step", ...]:
        # Every step in the run this name points at. TOTAL - an absent name is an empty match and never an
        # error, because whether absence is fatal is the KIND's business (hard or soft) and not the
        # addressing's. Keeping that decision out of here is what lets one addressing serve both flavours.
        ...

    @abstractmethod
    def spoken(self, name: object) -> str:
        # The name as a person would say it, for a refusal or a drawing.
        ...


@final
class _ByClass(Addressing):
    __slots__ = ()
    takes, stray, noun, indirect = "step CLASSES", "A step class", "dependency", False

    @override
    def admits(self, name: object) -> bool:
        from .step import Step  # the class object, which no annotation rule supplies
        return isinstance(name, type) and issubclass(name, Step)

    @override
    def found(self, name: object, instances: Mapping[type["Step"], Sequence["Step"]],
              providers: Mapping[str, Sequence["Step"]]) -> tuple["Step", ...]:
        # EVERY instance of the class, not the first. Two steps of one kind are two nodes, so a dependent
        # that named the kind meant both of them.
        return tuple(instances.get(name, ())) if isinstance(name, type) else ()

    @override
    def spoken(self, name: object) -> str:
        return name.__name__ if isinstance(name, type) else repr(name)


@final
class _ByLabel(Addressing):
    __slots__ = ()
    takes, stray, noun, indirect = "capability labels", "A capability label", "capability", True

    @override
    def admits(self, name: object) -> bool:
        return isinstance(name, str)

    @override
    def found(self, name: object, instances: Mapping[type["Step"], Sequence["Step"]],
              providers: Mapping[str, Sequence["Step"]]) -> tuple["Step", ...]:
        # A capability fans in. Duplicate providers are not a conflict, they are several things that all
        # satisfy the same promise, so a dependent orders after all of them. The kernel matches and never
        # picks, because picking would be the kernel guessing which provider a domain meant.
        return tuple(providers.get(name, ())) if isinstance(name, str) else ()

    @override
    def spoken(self, name: object) -> str:
        return f"{name!r}"


@final
class Roster(Sequence["Step"]):
    """The instances of one class, in supplied order, with an identity index beside them.

    A plain list answered membership by scanning, while an instance-addressed edge asks that question once
    per name - so a chain where each step names the previous cost O(n) per lookup and O(n squared) to
    derive. Measured on a four-thousand step chain, that was 0.284 seconds and rising by three and a half
    on every doubling.

    The set is beside the tuple rather than replacing it, because ORDER IS PART OF THE ANSWER - a class
    edge reaches every instance of the class and reaches them in the order they were supplied, which is
    what makes a resolved run reproducible."""

    __slots__ = ("__held", "__present")

    def __init__(self, held: Sequence["Step"]):
        self.__held = tuple(held)
        self.__present = frozenset(self.__held)

    @overload
    def __getitem__(self, position: int) -> "Step": ...

    @overload
    def __getitem__(self, position: slice) -> Sequence["Step"]: ...

    def __getitem__(self, position: int | slice) -> "Step | Sequence[Step]":
        return self.__held[position]

    def __len__(self) -> int:
        return len(self.__held)

    def __contains__(self, wanted: object) -> bool:
        # The whole point. A Step hashes and compares by identity, so this is an identity lookup in
        # constant time rather than a walk.
        return wanted in self.__present

    def __iter__(self) -> Iterator["Step"]:
        return iter(self.__held)


@final
class _ByInstance(Addressing):
    __slots__ = ()
    takes, stray, noun, indirect = "step INSTANCES", "A step instance", "instance", False

    @override
    def admits(self, name: object) -> bool:
        from .step import Step
        return isinstance(name, Step)

    @override
    def found(self, name: object, instances: Mapping[type["Step"], Sequence["Step"]],
              providers: Mapping[str, Sequence["Step"]]) -> tuple["Step", ...]:
        from .step import Step
        if not isinstance(name, Step):
            return ()
        # Present by IDENTITY, not by equality. A named instance that is not the one in the run is absent,
        # however alike the two look, which is the same currency every derived structure is keyed by.
        #
        # Asked of the named step's OWN class rather than of every class, answered by an index rather
        # than by a walk. Both halves matter - the first turns a scan of the whole run into a scan of one
        # kind, while the second turns that into a lookup.
        return (name,) if name in instances.get(type(name), ()) else ()

    @override
    def spoken(self, name: object) -> str:
        return type(name).__name__


BY_CLASS: Addressing = _ByClass()
BY_LABEL: Addressing = _ByLabel()
BY_INSTANCE: Addressing = _ByInstance()
MODES: tuple[Addressing, ...] = (BY_CLASS, BY_LABEL, BY_INSTANCE)


@final
@dataclass(frozen=True)
class EdgeKind:
    """One row of the language - a slot a step may declare and what an entry in it means.

    A frozen dataclass and deliberately not a NamedTuple, because tuple-ness would be accidental API and
    somebody would eventually unpack one."""

    slot: str                       # the attribute name a declaration writes
    addressing: Addressing          # how its entries name what they point at
    hard: bool                      # whether an absent target is a refusal or a shrug
    counterpart: str | None         # the slot of the same kind with the other hardness
    precedes: bool = False          # True means this step runs BEFORE the match, not after it

    def __post_init__(self) -> None:
        # The invariants ONE row can check about itself. Anything needing two rows is the table's job.
        if not self.slot.isidentifier():
            raise Misconfigured(f"An edge kind's slot must be a usable attribute name, got {self.slot!r}")
        if self.counterpart == self.slot:
            raise Misconfigured(f"Edge kind {self.slot!r} names itself as its own counterpart")

    @classmethod
    def paired(cls, soft: str, hard: str, addressing: Addressing, *,
               precedes: bool = False) -> tuple["EdgeKind", "EdgeKind"]:
        # The two flavours of one dependency, minted together so they cannot drift apart. Soft trusts the
        # world if the target is absent, hard says so. Every kind this kernel ships comes in both, because
        # "I need this" and "I need this and it had better be here" are different sentences a domain
        # genuinely wants to write.
        return (cls(soft, addressing, hard=False, counterpart=hard, precedes=precedes),
                cls(hard, addressing, hard=True, counterpart=soft, precedes=precedes))


@final
class Vocabulary:
    """The whole language of one run - the rows, in derivation order.

    Injected rather than global, so two runs in one process may speak differently and a domain that
    grows a kind does not mutate a table its neighbour is reading."""

    __slots__ = ("__kinds",)

    def __init__(self, *kinds: EdgeKind):
        if not kinds:
            raise Misconfigured("A vocabulary with no kinds cannot draw an edge - hand it at least one")
        seen: dict[str, EdgeKind] = {}
        for kind in kinds:
            if kind.slot in seen:
                raise Misconfigured(f"Edge kind {kind.slot!r} is declared twice in one vocabulary")
            seen[kind.slot] = kind
        for kind in kinds:
            if kind.counterpart is None:
                continue
            other = seen.get(kind.counterpart)
            if other is None:
                raise Misconfigured(
                    f"Edge kind {kind.slot!r} names {kind.counterpart!r} as its counterpart, yet this "
                    f"vocabulary has no such kind - a pair is only a pair when both halves are present"
                )
            if other.counterpart != kind.slot:
                raise Misconfigured(f"Edge kinds {kind.slot!r} and {other.slot!r} disagree about being a pair")
            if other.hard == kind.hard:
                raise Misconfigured(
                    f"Edge kinds {kind.slot!r} and {other.slot!r} are a pair and are both "
                    f"{'hard' if kind.hard else 'soft'} - a pair is the two flavours of one dependency"
                )
        self.__kinds = tuple(kinds)

    def __iter__(self) -> Iterator[EdgeKind]:
        # ROW ORDER IS DERIVATION ORDER, so a table read twice draws its edges the same way twice. That is
        # what makes a resolved order reproducible rather than merely correct.
        return iter(self.__kinds)

    def __len__(self) -> int:
        return len(self.__kinds)

    @classmethod
    def shipped(cls) -> "Vocabulary":
        # The language this kernel ships with. `expects` and `requires` are one dependency in its two
        # flavours, `wants` and `demands` the same pair addressed by capability rather than by class.
        #
        # Four pairs, three addressings and one of them reversed. That spread is the point - the table is
        # only worth having if it can express kinds that differ in more than their name, which these four
        # differ in how they name their target, in whether absence is fatal and in which direction the
        # edge points. The Graph derives all eight through one loop with no branch naming a slot.
        return cls(*EdgeKind.paired("expects", "requires", BY_CLASS),
                   *EdgeKind.paired("prepares", "mandates", BY_CLASS, precedes=True),
                   *EdgeKind.paired("wants", "demands", BY_LABEL),
                   *EdgeKind.paired("uses", "needs", BY_INSTANCE))

    def grown(self, *kinds: EdgeKind) -> "Vocabulary":
        # This language plus more. A new Vocabulary rather than a mutation, so the run already holding the
        # old one keeps reading the old one.
        return Vocabulary(*self.__kinds, *kinds)
