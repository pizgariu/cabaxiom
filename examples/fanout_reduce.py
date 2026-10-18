"""Fan-out over a world listed at RUN time, reduced through the data-flow, on the `Fanout` base.

The kernel's membership is a photograph taken at construction. The Graph derives once, the shape is
verified once and everything the run proves leans on that stillness. So a pipeline whose width is only
known at run time (list a bucket, process every object) does not mint steps into a live run. It puts the
LISTING inside one step, which builds a child Reconciler over what it found and awaits it - and since
0.6.0 that step is a shipped base rather than a pattern to copy.

`Fanout.explore()` answers the child. The three verbs are closed, which is the whole reason the base
exists, because the wiring has one rule that reads as success when you get it wrong - apply() hands up
the child's APPLIED channel and never its residual. A hand-rolled version of this example got another
thing wrong more quietly still. It wrote assess() and apply() and simply never wrote prune(), so the fan
was a thing that could be built and never torn down and nothing said so.

Two rules ride along and both are load-bearing.

- The step expands in BOTH read and write. Its assess() lists the world and delegates to a child
  assessment, so "an empty residual means verified" keeps covering the shards - an apply-only expansion
  would leave the re-probe blind to them. The price is stated. Every pass lists the world twice, once
  for the write and once for the re-probe that proves it.
- Every shard writes under its OWN key (`rows/<name>`). Ten thousand shards sharing one key is the
  fan-in the kernel refuses by name (Ledger.mounted), so the namespacing is not etiquette, it is the
  data contract - and it is what lets the reducer read every shard side by side. The reduce therefore
  happens INSIDE the child graph, wired by `uses`, which is also why a fanout publishes nothing back to
  its parent. N shards have no one key to export.
"""
import asyncio

from cabaxiom import Assessment, DriftItem, Fanout, Reconciler, Step
from cabaxiom.laboratory import Idempotence

# The world. Objects landed in a bucket, each waiting to be counted. In a real domain this is an S3
# listing and the values are URIs - artifacts carry POINTERS and the data plane moves the data.
BUCKET: dict[str, str] = {f"events-{stamp}.parquet": "raw" for stamp in ("0900", "0915", "0930")}
TALLIED: dict[str, int] = {}


class Shard(Step):
    """One listed object, processed and published under its own key - the namespaced fan-out unit."""

    def __init__(self, name: str) -> None:
        self.__name = name

    @property
    def identifier(self) -> str:
        # A step minted per row is exactly what this seam is for. Without it every sentence about any of
        # the three reads `Shard` and the labeller's `#2` says only that it was met second.
        return f"shard/{self.__name}"

    def assess(self, inputs):
        done = BUCKET[self.__name] == "tallied"
        drift = [] if done else [DriftItem(self.__name, "not tallied yet")]
        return Assessment(deviation=drift), {f"rows/{self.__name}": len(self.__name)} if done else {}

    def apply(self, inputs):
        if BUCKET[self.__name] == "tallied":
            return None, {f"rows/{self.__name}": len(self.__name)}

        BUCKET[self.__name] = "tallied"
        return [DriftItem(self.__name, "tallied")], {f"rows/{self.__name}": len(self.__name)}

    def prune(self, inputs):
        if BUCKET[self.__name] == "raw":
            return None, {}

        BUCKET[self.__name] = "raw"
        return [DriftItem(self.__name, "untallied")], {}


class Reduce(Step):
    """The fan-in. Reads every shard's key side by side and records the total."""

    def assess(self, inputs):
        counted = sum(value for key, value in inputs.items() if key.startswith("rows/"))
        settled = TALLIED.get("total") == counted and counted > 0
        return Assessment(deviation=[] if settled else [DriftItem("reduce", "total not recorded")]), {}

    def apply(self, inputs):
        counted = sum(value for key, value in inputs.items() if key.startswith("rows/"))
        if TALLIED.get("total") == counted:
            return None, {}   # the bulletproof no-op. The world already holds this total

        TALLIED["total"] = counted
        return [DriftItem("reduce", f"total recorded over {len(inputs)} shards")], {}

    def prune(self, inputs):
        return ([DriftItem("reduce", "total dropped")], {}) if TALLIED.pop("total", None) is not None else (None, {})


class Tally(Fanout):
    """The expansion, held inside ONE step of the parent run. List the world, declare over it, hand it back.

    The child is built fresh in each verb from the CURRENT listing - the level-triggered move, a membership
    re-read from the world instead of remembered - and the reducer is wired to every shard through `uses`,
    so the child's own graph carries the fan-in. The base wires all three verbs from this one method."""

    async def explore(self, inputs):
        shards = tuple(Shard(name) for name in sorted(BUCKET))
        reduce = Reduce()
        reduce.uses = shards
        return Reconciler((*shards, reduce))


async def main() -> None:
    print("bucket before:", dict(BUCKET))
    reconciler = Reconciler((Tally(),))

    residual = await reconciler.converge()
    print("applied:      ", [item.message for item in residual.applied])
    print("residual:     ", list(residual), "(empty means the whole fan-out is verified)")
    print("bucket after: ", dict(BUCKET))
    print("reduced total:", TALLIED["total"])

    proof = await Idempotence(reconciler).prove()
    print("idempotent:   ", proof.stable, "(a second converge changed nothing)")

    # The verb the hand-rolled version never had. A fan lists the world on the way DOWN too, so the
    # teardown covers whatever is standing now rather than whatever was standing when the run started.
    BUCKET["events-0945.parquet"] = "tallied"
    residue = await reconciler.prune()
    print("torn down:    ", [item.message for item in residue])
    print("bucket after: ", dict(BUCKET), "(including the object that landed after the converge)")

    assert residual == [] and proof.stable and not TALLIED
    assert set(BUCKET.values()) == {"raw"}


if __name__ == "__main__":
    asyncio.run(main())
