"""A domain-agnostic reconciliation kernel: Steps own desired state, a Reconciler resolves their
order and converges actual -> desired, self-verifying by re-probing for residual drift.

No domain vocabulary lives here. A drift item is read ONLY through the Drift protocol's two
fields (name + message). Everything richer is the domain's own payload. Two reusable behaviours
live here once and are inherited by every caller. One is sequencing steps by the dependencies they
declare - `expects` and its siblings, resolved by a pluggable Ordering strategy with graphlib's Kahn
by default. The other is the self-verifying converge (apply -> re-probe -> residual).

The re-probe is only as strong as a step's drift(). A step that mutates but reports no drift is
trusted to have worked, not verified, so a step guarding a real invariant must expose it through
drift(). That limit also decides what belongs here. A domain whose state cannot be probed
completely and cheaply enough for skip-when-clean to stay correct is no fit, however much it
resembles desired-state work.
"""

from importlib import metadata as _metadata

# WHAT YOU DECLARE, RUN AND CATCH - and deliberately not one name more. An axis's base class, a value
# the kernel mints rather than takes and the non-default strategy on an axis all live one import
# deeper, at `cabaxiom.core.<layer>`, because a name here is a name every reader has to walk past.
# Nothing is hidden by this and nothing is private. The layer says where a thing lives, so saying so
# is the point. `cabaxiom.laboratory` is asked for by name for the same reason.
from .core import (
    Artifacts,
    Assessment,
    AsyncFlowAssessment,
    AsyncFlowOutcome,
    Cancelled,
    Changes,
    Clean,
    Coverage,
    Cutover,
    Cycle,
    DataFlow,
    Deadline,
    Deferred,
    Drift,
    DriftItem,
    Enclave,
    Enclosure,
    Every,
    Exponential,
    Fanout,
    Fault,
    Fixed,
    Fixpoint,
    Flag,
    Flow,
    FlowAssessment,
    FlowOutcome,
    Graph,
    Identity,
    Itinerary,
    Journal,
    Kahn,
    Ledger,
    Malformed,
    Misconfigured,
    Observer,
    OnError,
    Only,
    Pairing,
    Parallel,
    Permit,
    Presence,
    Reconciler,
    RemoteDispatcher,
    Residual,
    Retry,
    Seating,
    Serial,
    Skew,
    Skip,
    Stable,
    Step,
    Succession,
    Supervised,
    ThreadDispatcher,
    Transition,
    Unresolvable,
    WithoutTag,
    WithTag,
)

__version__ = _metadata.version("cabaxiom")

__all__ = [
    "Cancelled",
    "Deadline",
    "Deferred",
    "Every",
    "Fault",
    "Flag",
    "Skew",
    "Artifacts",
    "AsyncFlowAssessment",
    "AsyncFlowOutcome",
    "FlowAssessment",
    "FlowOutcome",
    "Assessment",
    "Changes",
    "Drift",
    "DriftItem",
    "Coverage",
    "Cycle",
    "DataFlow",
    "Identity",
    "Malformed",
    "Misconfigured",
    "Pairing",
    "Presence",
    "Seating",
    "Unresolvable",
    "Permit",
    "Step",
    "Graph",
    "Kahn",
    "Only",
    "Skip",
    "WithTag",
    "WithoutTag",
    "Succession",
    "Ledger",
    "Observer",
    "OnError",
    "Journal",
    "Residual",
    "Exponential",
    "Fixed",
    "Fixpoint",
    "Flow",
    "Parallel",
    "RemoteDispatcher",
    "Serial",
    "Supervised",
    "ThreadDispatcher",
    "Enclave",
    "Enclosure",
    "Fanout",
    "Itinerary",
    "Reconciler",
    "Retry",
    "Clean",
    "Stable",
    "Cutover",
    "Transition",
]
