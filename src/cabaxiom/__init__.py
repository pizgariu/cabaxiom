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

from .adversary import Adversary, ChaosDispatcher, Sabotage, Targeted
from .arranger import Arranger, BaseFan, Chains, Walk, Waves
from .cancellation import (
    AllOf,
    AnyOf,
    Cancellation,
    Cancelled,
    Deadline,
    Deferred,
    Every,
    Fault,
    Flag,
    Majority,
    Most,
    Quorum,
    Rule,
    Skew,
    Some,
)
from .convergence import (
    Backoff,
    BaseLooping,
    Budget,
    Convergence,
    Exponential,
    Fibonacci,
    Fixed,
    Fixpoint,
    Jitter,
    Linear,
    Once,
    Shrinking,
)
from .diagram import Diagram, Dot, Mermaid, Tone
from .dispatcher import (
    BaseDispatcher,
    Crossing,
    Dispatcher,
    Flow,
    Parallel,
    RemoteDispatcher,
    RunMode,
    Serial,
    Settled,
    Supervised,
    ThreadDispatcher,
    WavesDispatcher,
    Write,
)
from .drift import Artifacts, Assessment, Changes, Drift, DriftItem
from .enclave import Enclave, Unpublished
from .enclosure import Enclosure, Severance, Severed
from .errors import (
    Coverage,
    Cycle,
    DataFlow,
    Identity,
    Malformed,
    Misconfigured,
    Pairing,
    Presence,
    Seating,
    Unresolvable,
)
from .fanout import Fanout
from .graph import Declared, Graph, Match
from .idempotence import Idempotence, Proof
from .isolation import Charge, Churn, Indictment, Isolation, Stall
from .itinerary import Itinerary, Passage
from .lease import Authority, Local, Permit
from .ledger import Ledger, OnError, Reading, Statement
from .observer import Chorus, Journal, Logging, Observer, Pass, Span, Stamp, Timing
from .ordering import DFS, Components, Kahn, Ordering, Priority
from .partition import ChainsPartition, Overlap, Partition, Placement, Seat, WalkPartition, WavesPartition
from .reconciler import Reconciler
from .records import Casualty, Explanation, Residual
from .retry import BaseRetry, Retry
from .reversibility import Reversibility, Roundtrip
from .scope import BaseNamed, BaseTagged, Only, Scope, Skip, WithEveryTag, WithoutTag, WithTag
from .settle import Clean, Settle, Stable
from .siege import Breach, Siege
from .step import Step
from .succession import Rift, Shift, Succession
from .transition import Cutover, Transition
from .vocabulary import (
    BY_CLASS,
    BY_INSTANCE,
    BY_LABEL,
    Addressing,
    EdgeKind,
    Vocabulary,
)
from .warrant import Ceiling, Charter, Warrant

# The installed distribution's version, the single source of truth (pyproject.toml), read back through
# packaging metadata so the two can never drift.
__version__ = _metadata.version("cabaxiom")

# One canonical order, twice. Groups mirror the import block above (alphabetical by module, the order
# isort enforces there) and each group mirrors its module's own definition order - protocols and Base*
# parents before the implementations that stand on them. Reading either list reads the other.
__all__ = [
    # arranger
    "Arranger", "BaseFan", "Waves", "Chains", "Walk",
    # cancellation
    "Cancelled", "Skew", "Deferred", "Fault", "Cancellation", "Deadline", "Flag",
    "Rule", "Some", "Every", "Most",
    "Quorum", "AnyOf", "AllOf", "Majority",
    # convergence
    "Convergence", "Once", "Backoff", "Fixed", "Exponential", "Linear", "Fibonacci", "Jitter",
    "BaseLooping", "Fixpoint", "Shrinking", "Budget",
    # drift
    "Drift", "DriftItem", "Assessment", "Artifacts", "Changes",
    # enclave
    "Breach", "Siege",
    "Enclave", "Unpublished",
    # errors - three unrelated bases, each for a different audience
    "Malformed", "Unresolvable", "Misconfigured",
    "Cycle", "Coverage", "Seating", "Pairing", "Presence", "DataFlow", "Identity",
    # enclosure
    "Severed", "Severance", "Enclosure",
    # fanout
    "Fanout",
    # dispatcher
    "OnError", "Overlap", "Ledger", "Statement", "Reading", "Settled", "Write", "Crossing", "Permit", "Authority", "Local", "Warrant", "Charter", "Ceiling", "BaseDispatcher",
    "Dispatcher", "WavesDispatcher", "RunMode", "Parallel", "Supervised", "Serial", "Flow", "ThreadDispatcher", "RemoteDispatcher",
    "Adversary", "Sabotage", "Targeted", "ChaosDispatcher",
    # graph
    "Declared", "Match", "Graph",
    "Addressing", "BY_CLASS", "BY_LABEL", "BY_INSTANCE", "EdgeKind", "Vocabulary",
    "Diagram", "Dot", "Mermaid", "Tone",
    # idempotence
    "Proof", "Idempotence",
    # isolation
    "Charge", "Churn", "Stall", "Indictment", "Isolation",
    # itinerary
    "Passage", "Itinerary",
    # observer
    "Observer", "Chorus", "Pass", "Journal", "Logging", "Stamp", "Span", "Timing",
    # ordering
    "Ordering", "Kahn", "DFS", "Priority", "Components",
    # partition
    "Seat", "Placement", "Partition", "WavesPartition", "ChainsPartition", "WalkPartition",
    # reconciler
    "Residual", "Explanation", "Casualty", "Reconciler",
    # retry
    "Retry", "BaseRetry",
    # reversibility
    "Roundtrip", "Reversibility",
    # scope
    "Scope", "BaseNamed", "Only", "Skip", "BaseTagged", "WithTag", "WithEveryTag", "WithoutTag",
    # settle
    "Settle", "Clean", "Stable",
    # step
    "Step",
    # succession
    "Shift", "Rift", "Succession",
    # transition
    "Cutover", "Transition",
]

