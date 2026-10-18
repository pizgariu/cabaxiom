"""What you mount a run in so a question can be put to it at all.

An Adversary injects the failure a healthy world would not produce, deterministically when it is Targeted
and by a seeded roll when it is Sabotage - seeded, because a chaos finding nobody can re-run is a story
rather than a reproduction. The doubles beside it are the scripted stand-ins this kernel's own suite grew,
published with a compatibility promise so a caller's suite may lean on them too."""

from .adversary import Adversary, ChaosDispatcher, Sabotage, Targeted

__all__ = [
    "Adversary",
    "ChaosDispatcher",
    "Sabotage",
    "Targeted",
]
