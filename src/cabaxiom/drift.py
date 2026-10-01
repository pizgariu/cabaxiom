"""The drift contract - one thing found out of desired state, read through a two-field protocol,
and the flow types built on it - what a read assesses and what a write hands back, each ferrying
the artifacts a later step may consume."""
from collections.abc import Coroutine, Sequence
from dataclasses import dataclass
from typing import Any, Protocol, final


class Drift(Protocol):
    # One thing found out of desired state. These two fields are the entire contract a drift exposes,
    # so any domain item satisfies the kernel just by structurally exposing them. Richer payload stays
    # private to the domain item. Read by duck typing, never isinstance-tested. The Protocol names the
    # boundary, it does not gate at runtime.
    #
    # Declared as read-only properties, because the kernel only ever READS them. A frozen dataclass, a
    # NamedTuple or a property-backed domain item all satisfy the contract, where a settable-attribute
    # declaration would reject exactly those most natural carriers. A plain attribute (DriftItem's own
    # shape) satisfies a read-only property, so nothing existing narrows.
    @property
    def name(self) -> str: ...      # the subject that drifted (a config file, an env var, a service)

    @property
    def message(self) -> str: ...   # human-readable one-liner: what is wrong


@final
@dataclass(frozen=True, repr=False)
class DriftItem:
    # The kernel's concrete default Drift, for domains with no carrier of their own. A domain with a
    # richer item just exposes name + message on it and uses that instead.
    #
    # FROZEN, by the standard library's own frozen dataclass rather than by hand. `frozen` refuses
    # assignment after construction, the slots keep the two fields the whole object and the generated
    # equality and hash both read exactly the two contract fields. That value hash is the point - an item
    # that can sit in a set must not be assignable in place, the classic mutable-hashable trap - and value
    # equality is what lets a caller assert a drift list against expected items instead of identities.
    # Another Drift carrier is left to Python's fallback, since the protocol is structural for READING and
    # not for equality across carriers. `repr` stays hand-written because the positional form reads as the
    # call that built it. The protocol declares read-only properties precisely so a plain frozen field
    # satisfies it.
    #
    # The slots are declared by hand rather than through `slots=True`, which would rebuild the class and
    # leave the generated __setattr__ closed over the original - so a stray attribute would come back as
    # a confusing TypeError instead of the AttributeError a typo deserves.
    __slots__ = ("name", "message")
    name: str
    message: str

    def __reduce__(self) -> tuple[type["DriftItem"], tuple[str, str]]:
        # Rebuilt through its own constructor. Default pickling restores a slotted object field by field,
        # which the frozen __setattr__ refuses - and the item MUST cross a process boundary, because the
        # frozen Step's whole wire story ships Changes back from a worker, while Changes is a sequence of
        # exactly these. The constructor path keeps the freeze airtight on both sides of the wire.
        return (DriftItem, (self.name, self.message))

    def __repr__(self) -> str:
        return f"DriftItem({self.name!r}, {self.message!r})"

    def __str__(self) -> str:
        return f"{self.name}: {self.message}"


# The data-flow payload - what a step's dependencies produced, keyed by opaque label, assembled by the
# Ledger and handed into every read and write. The one channel state travels between steps - a step that
# needs a generated id or a connection string reads it here instead of smuggling it through a domain
# global, which is the hidden-state class the kernel refuses everywhere else.
Artifacts = dict[str, Any]


@final
@dataclass(frozen=True)
class Assessment:
    """One read of the world, whole - the deviation, the plan, the advice and the footprint in a single
    frozen record, where four separate hooks used to each pay their own probe for a slice of the same
    reading.

    The four channels keep the four meanings apart rather than blurring them into one list. `deviation`
    is what is out of desired state (drift's old answer, empty == verified). `plan` is what a converge
    WOULD do. `advisory` is what deserves attention in a system that already meets desired state, which
    is exactly why it is not deviation - advice must never dirty a proof. `footprint` is what this step
    owns, read in teardown order. A record, like every value the kernel mints - frozen, so a verdict
    cannot be rewritten by the hand that received it."""
    deviation: Sequence[Drift] = ()
    plan: Sequence[Drift] = ()
    advisory: Sequence[Drift] = ()
    footprint: Sequence[Drift] = ()


# A write's outcome, the type a step's apply() or prune() hands back - the changes it reports (or None
# for a clean no-op) paired with the artifacts it produced for its dependents. Changes is a Sequence,
# not a list: list is invariant, so a domain returning its own list[MyDrift] would fail the override
# under strict typing, while Sequence (covariant, read-only) accepts it.
type Changes = Sequence[Drift] | None
type FlowOutcome = tuple[Changes, Artifacts]
type AsyncFlowOutcome = FlowOutcome | Coroutine[Any, Any, FlowOutcome]

# A read's outcome, the same pair for assess() - the Assessment record alongside the artifacts the read
# produced. The async form admits a coroutine, so a plain sync assess() on a step remains a legal typed
# override, bridged onto the loop by the dispatcher that runs it.
type FlowAssessment = tuple[Assessment, Artifacts]
type AsyncFlowAssessment = FlowAssessment | Coroutine[Any, Any, FlowAssessment]

