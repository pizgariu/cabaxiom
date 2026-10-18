"""The plan layer - from a bag of steps to a seated, ordered partition, before a single world is touched.

The Graph derives the edges the declarations implied, an Ordering flattens them into one sequence, a
Partition groups that sequence into what may legally run together. An Arranger is the pair of the two
speaking as one. Scope and Succession are the same derivation asked sideways - which steps survive a
filter, plus what one declaration succeeding another does to the structure between them.

Reads the declaration layer and nothing else. Everything this layer refuses, it refuses at BUILD time,
which is the kernel's oldest promise and the reason the whole plan is derived before any run begins."""

from .arranger import Arranger, BaseFan, Chains, Walk, Waves
from .graph import Declared, Graph, Match
from .ordering import DFS, Components, Kahn, Ordering, Priority
from .partition import ChainsPartition, Overlap, Partition, Placement, Seat, WalkPartition, WavesPartition
from .scope import BaseNamed, BaseTagged, Only, Scope, Skip, WithEveryTag, WithoutTag, WithTag
from .succession import Rift, Shift, Succession

__all__ = [
    "Arranger",
    "BaseFan",
    "Chains",
    "Walk",
    "Waves",
    "Declared",
    "Graph",
    "Match",
    "Components",
    "DFS",
    "Kahn",
    "Ordering",
    "Priority",
    "ChainsPartition",
    "Overlap",
    "Partition",
    "Placement",
    "Seat",
    "WalkPartition",
    "WavesPartition",
    "BaseNamed",
    "BaseTagged",
    "Only",
    "Scope",
    "Skip",
    "WithEveryTag",
    "WithTag",
    "WithoutTag",
    "Rift",
    "Shift",
    "Succession",
]
