"""A domain-agnostic reconciliation kernel. Steps own desired state, a Reconciler resolves their
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
    Cancellation,
    Cancelled,
    Changes,
    Coverage,
    Cycle,
    DataFlow,
    Deadline,
    Deferred,
    Drift,
    DriftItem,
    Exponential,
    Fault,
    Fixed,
    Fixpoint,
    Flag,
    FlowAssessment,
    FlowOutcome,
    Graph,
    Identity,
    Kahn,
    Ledger,
    Malformed,
    Misconfigured,
    Observer,
    OnError,
    Pairing,
    Parallel,
    Presence,
    Reading,
    Reconciler,
    Residual,
    Retry,
    Seating,
    Serial,
    Skew,
    Step,
    Supervised,
    Unresolvable,
    Vocabulary,
)

# ONE SOURCE OF TRUTH still, beside a package that imports without it. The number lives in the distribution
# metadata and is never hand-copied here, since a literal beside pyproject.toml is one fact written twice
# with nothing keeping the two in agreement. What this adds is the case where there IS no distribution - a
# vendored copy, a checkout on sys.path, a zipapp - where the read raised and took the whole import with it.
# The fallback says it does not know rather than guessing, because a wrong version is worse than an absent
# one for anyone deciding whether their bug is fixed.
try:
    __version__ = _metadata.version("cabaxiom")
except _metadata.PackageNotFoundError:
    __version__ = "0+unknown"

__all__ = [
    # what you DECLARE
    "Step",
    "Assessment",
    "Changes",
    "Drift",
    "DriftItem",
    "Artifacts",
    "FlowAssessment",
    "FlowOutcome",
    "AsyncFlowAssessment",
    "AsyncFlowOutcome",
    "Vocabulary",
    # what you RUN
    "Reconciler",
    "Graph",
    "Kahn",
    "Serial",
    "Parallel",
    "Supervised",
    "OnError",
    "Fixpoint",
    "Retry",
    "Fixed",
    "Exponential",
    "Cancellation",
    "Deadline",
    "Flag",
    # what you READ
    "Residual",
    "Reading",
    "Ledger",
    "Observer",
    # what you CATCH
    "Cancelled",
    "Deferred",
    "Fault",
    "Skew",
    "Cycle",
    "Coverage",
    "DataFlow",
    "Identity",
    "Malformed",
    "Misconfigured",
    "Pairing",
    "Presence",
    "Seating",
    "Unresolvable",
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
# WHERE A NAME LIVES and WHEN it left, one row per name so a refusal can name the window it belongs
# to. The table was keyed by layer, which forced one version on a whole layer - true while every
# name left in the same window and false the moment 1.0.0 narrowed the door a second time.
#
# STRINGS, not imports. Resolving this at import time would drag the laboratory into sys.modules and
# break the very claim the split was made for, so nothing here is imported until somebody asks by
# name. A contract test walks it against the live packages, which is where that check belongs.
_MOVED: dict[str, tuple[str, str]] = {
    # cabaxiom.core.declaration, 0.7.0
    "Addressing": ("cabaxiom.core.declaration", "0.7.0"),
    "AllOf": ("cabaxiom.core.declaration", "0.7.0"),
    "AnyOf": ("cabaxiom.core.declaration", "0.7.0"),
    "Authority": ("cabaxiom.core.declaration", "0.7.0"),
    "BY_CLASS": ("cabaxiom.core.declaration", "0.7.0"),
    "BY_INSTANCE": ("cabaxiom.core.declaration", "0.7.0"),
    "BY_LABEL": ("cabaxiom.core.declaration", "0.7.0"),
    "EdgeKind": ("cabaxiom.core.declaration", "0.7.0"),
    "Local": ("cabaxiom.core.declaration", "0.7.0"),
    "Majority": ("cabaxiom.core.declaration", "0.7.0"),
    "Most": ("cabaxiom.core.declaration", "0.7.0"),
    "Quorum": ("cabaxiom.core.declaration", "0.7.0"),
    "Rule": ("cabaxiom.core.declaration", "0.7.0"),
    "Some": ("cabaxiom.core.declaration", "0.7.0"),
    # cabaxiom.core.declaration, 1.0.0
    "Every": ("cabaxiom.core.declaration", "1.0.0"),
    "Permit": ("cabaxiom.core.declaration", "1.0.0"),
    # cabaxiom.core.plan, 0.7.0
    "Arranger": ("cabaxiom.core.plan", "0.7.0"),
    "BaseFan": ("cabaxiom.core.plan", "0.7.0"),
    "BaseNamed": ("cabaxiom.core.plan", "0.7.0"),
    "BaseTagged": ("cabaxiom.core.plan", "0.7.0"),
    "Chains": ("cabaxiom.core.plan", "0.7.0"),
    "ChainsPartition": ("cabaxiom.core.plan", "0.7.0"),
    "Components": ("cabaxiom.core.plan", "0.7.0"),
    "DFS": ("cabaxiom.core.plan", "0.7.0"),
    "Declared": ("cabaxiom.core.plan", "0.7.0"),
    "Match": ("cabaxiom.core.plan", "0.7.0"),
    "Ordering": ("cabaxiom.core.plan", "0.7.0"),
    "Overlap": ("cabaxiom.core.plan", "0.7.0"),
    "Partition": ("cabaxiom.core.plan", "0.7.0"),
    "Placement": ("cabaxiom.core.plan", "0.7.0"),
    "Priority": ("cabaxiom.core.plan", "0.7.0"),
    "Rift": ("cabaxiom.core.plan", "0.7.0"),
    "Scope": ("cabaxiom.core.plan", "0.7.0"),
    "Seat": ("cabaxiom.core.plan", "0.7.0"),
    "Shift": ("cabaxiom.core.plan", "0.7.0"),
    "Walk": ("cabaxiom.core.plan", "0.7.0"),
    "WalkPartition": ("cabaxiom.core.plan", "0.7.0"),
    "Waves": ("cabaxiom.core.plan", "0.7.0"),
    "WavesPartition": ("cabaxiom.core.plan", "0.7.0"),
    "WithEveryTag": ("cabaxiom.core.plan", "0.7.0"),
    # cabaxiom.core.plan, 1.0.0
    "Only": ("cabaxiom.core.plan", "1.0.0"),
    "Skip": ("cabaxiom.core.plan", "1.0.0"),
    "Succession": ("cabaxiom.core.plan", "1.0.0"),
    "WithTag": ("cabaxiom.core.plan", "1.0.0"),
    "WithoutTag": ("cabaxiom.core.plan", "1.0.0"),
    # cabaxiom.core.record, 0.7.0
    "Arrow": ("cabaxiom.core.record", "0.7.0"),
    "Binding": ("cabaxiom.core.record", "0.7.0"),
    "Casualty": ("cabaxiom.core.record", "0.7.0"),
    "Ceiling": ("cabaxiom.core.record", "0.7.0"),
    "Charter": ("cabaxiom.core.record", "0.7.0"),
    "Chorus": ("cabaxiom.core.record", "0.7.0"),
    "Diagram": ("cabaxiom.core.record", "0.7.0"),
    "Dot": ("cabaxiom.core.record", "0.7.0"),
    "Explanation": ("cabaxiom.core.record", "0.7.0"),
    "Logging": ("cabaxiom.core.record", "0.7.0"),
    "Mermaid": ("cabaxiom.core.record", "0.7.0"),
    "Node": ("cabaxiom.core.record", "0.7.0"),
    "Pass": ("cabaxiom.core.record", "0.7.0"),
    "Span": ("cabaxiom.core.record", "0.7.0"),
    "Stamp": ("cabaxiom.core.record", "0.7.0"),
    "Statement": ("cabaxiom.core.record", "0.7.0"),
    "Timing": ("cabaxiom.core.record", "0.7.0"),
    "Tone": ("cabaxiom.core.record", "0.7.0"),
    "Warrant": ("cabaxiom.core.record", "0.7.0"),
    # cabaxiom.core.record, 1.0.0
    "Journal": ("cabaxiom.core.record", "1.0.0"),
    # cabaxiom.core.run, 0.7.0
    "Answered": ("cabaxiom.core.run", "0.7.0"),
    "Backoff": ("cabaxiom.core.run", "0.7.0"),
    "BaseDispatcher": ("cabaxiom.core.run", "0.7.0"),
    "BaseLooping": ("cabaxiom.core.run", "0.7.0"),
    "BaseRetry": ("cabaxiom.core.run", "0.7.0"),
    "Budget": ("cabaxiom.core.run", "0.7.0"),
    "Convergence": ("cabaxiom.core.run", "0.7.0"),
    "Crossing": ("cabaxiom.core.run", "0.7.0"),
    "Decision": ("cabaxiom.core.run", "0.7.0"),
    "Dispatcher": ("cabaxiom.core.run", "0.7.0"),
    "Fibonacci": ("cabaxiom.core.run", "0.7.0"),
    "Jitter": ("cabaxiom.core.run", "0.7.0"),
    "Linear": ("cabaxiom.core.run", "0.7.0"),
    "Once": ("cabaxiom.core.run", "0.7.0"),
    "Passage": ("cabaxiom.core.run", "0.7.0"),
    "Payload": ("cabaxiom.core.run", "0.7.0"),
    "RunMode": ("cabaxiom.core.run", "0.7.0"),
    "Settle": ("cabaxiom.core.run", "0.7.0"),
    "Settled": ("cabaxiom.core.run", "0.7.0"),
    "Severance": ("cabaxiom.core.run", "0.7.0"),
    "Severed": ("cabaxiom.core.run", "0.7.0"),
    "Shrinking": ("cabaxiom.core.run", "0.7.0"),
    "Unpublished": ("cabaxiom.core.run", "0.7.0"),
    "WavesDispatcher": ("cabaxiom.core.run", "0.7.0"),
    "Write": ("cabaxiom.core.run", "0.7.0"),
    # cabaxiom.core.run, 1.0.0
    "Clean": ("cabaxiom.core.run", "1.0.0"),
    "Cutover": ("cabaxiom.core.run", "1.0.0"),
    "Enclave": ("cabaxiom.core.run", "1.0.0"),
    "Enclosure": ("cabaxiom.core.run", "1.0.0"),
    "Fanout": ("cabaxiom.core.run", "1.0.0"),
    "Flow": ("cabaxiom.core.run", "1.0.0"),
    "Itinerary": ("cabaxiom.core.run", "1.0.0"),
    "RemoteDispatcher": ("cabaxiom.core.run", "1.0.0"),
    "Stable": ("cabaxiom.core.run", "1.0.0"),
    "ThreadDispatcher": ("cabaxiom.core.run", "1.0.0"),
    "Transition": ("cabaxiom.core.run", "1.0.0"),
    # cabaxiom.laboratory, 0.7.0
    "Adversary": ("cabaxiom.laboratory", "0.7.0"),
    "Breach": ("cabaxiom.laboratory", "0.7.0"),
    "ChaosDispatcher": ("cabaxiom.laboratory", "0.7.0"),
    "Charge": ("cabaxiom.laboratory", "0.7.0"),
    "Churn": ("cabaxiom.laboratory", "0.7.0"),
    "Idempotence": ("cabaxiom.laboratory", "0.7.0"),
    "Indictment": ("cabaxiom.laboratory", "0.7.0"),
    "Isolation": ("cabaxiom.laboratory", "0.7.0"),
    "Proof": ("cabaxiom.laboratory", "0.7.0"),
    "Reversibility": ("cabaxiom.laboratory", "0.7.0"),
    "Roundtrip": ("cabaxiom.laboratory", "0.7.0"),
    "Sabotage": ("cabaxiom.laboratory", "0.7.0"),
    "Siege": ("cabaxiom.laboratory", "0.7.0"),
    "Stall": ("cabaxiom.laboratory", "0.7.0"),
    "Targeted": ("cabaxiom.laboratory", "0.7.0"),
}

# Names that did not MOVE, they went private, so a caller who reaches for one is reaching for a mistake
# rather than a new address. Each answers with the reason it is gone and what to write instead.
_SEALED: dict[str, str] = {
    "Gather": "every valid pairing of it is a shipped run mode. Use Parallel() or compose your own "
              "worker with RunMode(arranger, worker) from cabaxiom.core.run",
    "Watch": "every valid pairing of it is a shipped run mode. Use Supervised() or compose your own "
             "worker with RunMode(arranger, worker) from cabaxiom.core.run",
    "ident": "Step.identifier is the name since 0.6.0 and Step.ident was never one. It was never a module-level name either",
    # THE THREE THAT WERE REALLY OUT THERE. Every other row above left a door only a reader of the
    # development notes ever saw. These three stood on 0.4.2, a door that went out to PyPI, so an upgrade
    # that met them bare met the one refusal this table exists to prevent - CPython's "cannot import name",
    # which names nothing and helps nobody. A contract test walks every published door against this file.
    "Levels": "the partition is WavesPartition since the plan layer split. Write "
              "`from cabaxiom.core.plan import WavesPartition`",
    "Outcome": "a write answers FlowOutcome or AsyncFlowOutcome, which gained the artifacts half - a hook "
               "hands back `(changes, artifacts)` rather than changes alone. Both are on the front door",
    "Pipeline": "running independent chains is an ARRANGER rather than a dispatcher. Write "
                "`Reconciler(..., arranger=Chains())`, importing Chains from cabaxiom.core.plan",
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
    if name in _MOVED:
        where, window = _MOVED[name]
        raise ImportError(
            f"cabaxiom.{name} moved to {where} in {window}. Write `from {where} import {name}`. The front "
            f"door publishes what you DECLARE, RUN, READ and CATCH. That is the surface 1.0.0 froze. An axis "
            f"base class, a value the kernel mints rather than takes and the non-default strategy on an "
            f"axis all live one import deeper. Nothing was removed and nothing is private - see the "
            f"{window} section of CHANGELOG.md."
        )
    if name in _SEALED:
        raise ImportError(f"cabaxiom.{name} is not a name this package exports - {_SEALED[name]}.")
    raise AttributeError(f"module 'cabaxiom' has no attribute {name!r}")
