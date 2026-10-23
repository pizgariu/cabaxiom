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

# WHERE A NAME WENT, so an upgrade meets a sentence instead of a dead end. The 0.7.0 window narrowed this
# door from a hundred and forty-nine names to fifty-nine and moved the rest one import deeper. For a
# while every one of those moves answered with a bare ImportError naming nothing. This file's own window
# opens by promising that nothing it removes is left without the thing that takes its place, so a caller
# who cannot find that thing has not been given it.
#
# STRINGS, not imports. Resolving this map at import time would drag the laboratory into sys.modules and
# break the very claim the split was made for, so nothing here is imported until somebody asks by name.
# A test walks it against the live packages, which is where that check belongs.
_MOVED: dict[str, tuple[str, ...]] = {
    "cabaxiom.core.declaration": (
        "Addressing", "AllOf", "AnyOf", "Authority", "BY_CLASS", "BY_INSTANCE", "BY_LABEL", "Cancellation",
        "EdgeKind", "Local", "Majority", "Most", "Quorum", "Rule", "Some", "Vocabulary",
    ),
    "cabaxiom.core.plan": (
        "Arranger", "BaseFan", "BaseNamed", "BaseTagged", "Chains", "ChainsPartition", "Components", "DFS",
        "Declared", "Match", "Ordering", "Overlap", "Partition", "Placement", "Priority", "Rift", "Scope",
        "Seat", "Shift", "Walk", "WalkPartition", "Waves", "WavesPartition", "WithEveryTag",
    ),
    "cabaxiom.core.record": (
        "Arrow", "Binding", "Casualty", "Ceiling", "Charter", "Chorus", "Diagram", "Dot", "Explanation", "Node", "Logging", "Mermaid",
        "Pass", "Reading", "Span", "Stamp", "Statement", "Timing", "Tone", "Warrant",
    ),
    "cabaxiom.core.run": (
        "Backoff", "BaseDispatcher", "BaseLooping", "BaseRetry", "Budget", "Convergence", "Decision", "Crossing",
        "Answered", "Dispatcher", "Fibonacci", "Jitter", "Linear", "Once", "Passage", "Payload", "RunMode", "Settle", "Settled",
        "Severance", "Severed", "Shrinking", "Unpublished", "WavesDispatcher", "Write",
    ),
    "cabaxiom.laboratory": (
        "Adversary", "Breach", "ChaosDispatcher", "Charge", "Churn", "Idempotence", "Indictment",
        "Isolation", "Proof", "Reversibility", "Roundtrip", "Sabotage", "Siege", "Stall", "Targeted",
    ),
}

# Names that did not MOVE, they went private, so a caller who reaches for one is reaching for a mistake
# rather than a new address. Each answers with the reason it is gone and what to write instead.
_SEALED: dict[str, str] = {
    "Gather": "every valid pairing of it is a shipped run mode. Use Parallel() or compose your own "
              "worker with RunMode(arranger, worker) from cabaxiom.core.run",
    "Watch": "every valid pairing of it is a shipped run mode. Use Supervised() or compose your own "
             "worker with RunMode(arranger, worker) from cabaxiom.core.run",
    "ident": "Step.identifier is the name since 0.6.0 and Step.ident was never one. It was never a module-level name either",
}


def __getattr__(name: str) -> object:
    # A REFUSAL, not a shim. It hands nothing back, because the whole point of the narrowing is that these
    # names are not here - a silent forward would leave the door as wide as it ever was while pretending
    # otherwise. What it hands back instead is the line to type, which is the bargain every other refusal
    # in this kernel makes.
    #
    # ImportError AND NOT AttributeError, which is the one surprising choice here and was measured rather
    # than assumed. `from cabaxiom import Waves` is the form people actually write, so CPython catches an
    # AttributeError out of a module __getattr__ and replaces it with its own "cannot import name" - so a
    # careful message raised as AttributeError reaches nobody, while the same message raised as ImportError
    # arrives intact. The price is that `hasattr(cabaxiom, "Waves")` RAISES instead of answering False,
    # since hasattr only swallows AttributeError. That trade is deliberate. One of the two is written by
    # every person upgrading and the other by almost nobody.
    #
    # Anything not in the two tables gets a plain AttributeError and that clause is load-bearing rather
    # than tidy. The import machinery probes a module for __path__ and other dunders, so an ImportError
    # raised at one of those breaks importing this package at all. Found by doing exactly that.
    for where, names in _MOVED.items():
        if name in names:
            raise ImportError(
                f"cabaxiom.{name} moved to {where} in 0.7.0. Write `from {where} import {name}`. The front "
                f"door publishes what you DECLARE, RUN and CATCH. An axis base class, a value the "
                f"kernel mints rather than takes and the non-default strategy on an axis all live one "
                f"import deeper. Nothing was removed and nothing is private - see the 0.7.0 section of CHANGELOG.md."
            )
    if name in _SEALED:
        raise ImportError(f"cabaxiom.{name} is not a name this package exports - {_SEALED[name]}.")
    raise AttributeError(f"module 'cabaxiom' has no attribute {name!r}")
