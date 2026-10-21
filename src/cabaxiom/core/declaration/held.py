"""The frozen sequence three of the kernel's records ARE, implemented once instead of three times."""
from collections.abc import Iterable, Sequence
from typing import overload, override


class _Held[T](Sequence[T]):
    """A record that presents as an immutable Sequence over what it holds.

    Three records need this and each used to hand-roll it - `Roster` (who is in the run, of one class),
    `Residual` (what converge left behind) and `Reading` (what one probe read). Ten lines of protocol
    apiece. The copies had already drifted apart in the one place a reader is least likely to look at
    three files at once - two typed a slice as `tuple`, the third as `Sequence`, so the same expression
    meant two different things depending on which record answered it.

    THE SLICE HANDS BACK A TUPLE. That is the decision this class exists to make exactly once. It is
    the truth about every one of these records - they hold a tuple, so slicing one always produced a tuple
    and the annotation saying `Sequence` was merely the vaguer of two true statements. Narrowing a return
    in an override is sound and both type checkers agree, so the precise one wins. A caller slicing a
    record gets something it can index, compare and hand on without asking what it really is.

    One IDE warns that the slice overload does not match the base. It warns identically on a signature
    written back to the base's own `Sequence[T]`, measured with the gates green both ways, so the flag is
    that tool's reading of overloaded overrides and not a price this narrowing pays. Widening would spend
    the caller's precision and silence nothing.

    Storage is `_held`, one underscore, because a subclass reads it. The private slots the subclasses keep
    are their own extra channels, which is the part that genuinely differs between them - and the part
    worth writing three times."""

    __slots__ = ("_held",)

    def __init__(self, held: Iterable[T]) -> None:
        # Copied at construction, every time, which is what makes the record frozen rather than a view of
        # somebody else's list. A verdict the caller can still append to is not a verdict.
        self._held = tuple(held)

    @overload
    def __getitem__(self, index: int) -> T: ...

    @overload
    def __getitem__(self, index: slice) -> tuple[T, ...]: ...

    @override
    def __getitem__(self, index: int | slice) -> "T | tuple[T, ...]":
        # THE ARMS ARE IDENTICAL ON PURPOSE, because the guard is for the checker and not for the runtime.
        # isinstance NARROWS the index, so each return hits ONE overload of tuple.__getitem__ - without it
        # the argument is the union, so a checker that does not distribute a union over overloads cannot
        # match the call at all. This is the canonical way to implement an overloaded __getitem__ and an
        # earlier commit deleted it as a branch that decided nothing, which was wrong about what it decided.
        # The alternatives are worse, measured rather than assumed - a typing.cast here is a REDUNDANT cast
        # under mypy --strict (a gate error, since mypy needs no help) and costs the same fifteen
        # nanoseconds this check does, buying nothing for the price of something.
        if isinstance(index, slice):
            return self._held[index]
        return self._held[index]

    @override
    def __len__(self) -> int:
        return len(self._held)

    @override
    def __eq__(self, other: object) -> bool:
        # BY ITEMS, against a record of the same kind or any plain sequence. Every extra channel a subclass
        # keeps - a residual's failures, a reading's produced map, a roster's index - is context about the
        # items and never their identity, so two records holding the same items in the same order are equal
        # whatever else they carry. Residual and Reading each wrote this rule out by hand, seven identical
        # lines apiece with only the class name differing, which is the exact shape _Held exists to end.
        # Anything else answers NotImplemented, so Python asks the other side before deciding they differ.
        if isinstance(other, type(self)):
            return self._held == other._held
        if isinstance(other, (list, tuple)):
            return len(self._held) == len(other) and all(a == b for a, b in zip(self._held, other))
        return NotImplemented

    # Writing __eq__ silences the inherited __hash__, which is right. A record compared by items cannot be
    # a set member or a dict key without its hash moving whenever the items would. None of the three
    # is ever asked for one. Said here rather than left for a reader to infer from the absence.
    __hash__ = None  # type: ignore[assignment]
