"""The laboratory - what you INTERROGATE a kernel with, kept outside the kernel it interrogates.

Three benches, each naming the technique rather than the feature. `proof` asks whether a property
holds. `shrink` asks for the smallest thing that breaks it. `rig` is what you mount a run in so that
either question can be put at all.

Everything here imports core. NOTHING IN CORE IMPORTS ANYTHING HERE. That is the whole reason the
line was drawn rather than left implicit. A delta-debugger and an adversary are superb things to own and
have no business being reachable from the object they are pointed at - a kernel that can see its own
interrogator is a kernel whose runtime carries a laboratory into production."""

from .proof import Idempotence, Proof, Reversibility, Roundtrip
from .rig import Adversary, ChaosDispatcher, Sabotage, Targeted
from .shrink import Breach, Charge, Churn, Indictment, Isolation, Siege, Stall

__all__ = [
    "Idempotence",
    "Proof",
    "Reversibility",
    "Roundtrip",
    "Charge",
    "Churn",
    "Indictment",
    "Isolation",
    "Stall",
    "Breach",
    "Siege",
    "Adversary",
    "ChaosDispatcher",
    "Sabotage",
    "Targeted",
]
