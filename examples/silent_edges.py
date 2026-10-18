"""Two guards for the failures that never fail - a refactor that silently unwires your ordering.

Every other proof in this kernel answers "did the world end up right?". These two answer a question
that comes earlier and cannot be asked at run time at all: "does the ordering I declared still
EXIST?". They matter because a lost ordering is not an error. Nothing raises, nothing is logged, a
step simply stops waiting for something and the run stays green until the day the timing is
unlucky.

The scenario is one ordinary refactor. A flat declaration runs {database, api, worker}, where api
and worker both declare `wants = ("database",)` and the database declares `provides`. Somebody
extracts the database into its own stack, which an Enclave joins to the parent as one step. Nothing
is deleted, nothing is renamed and the world still converges. But an Enclave is one opaque step to
its parent, so it does not carry the capability the step inside it provides and both edges vanish.

Succession and Enclosure catch the same break from two directions:

  Succession(previous, desired).compare()  compares the declaration to the one it replaces, so it
  reports what the change TOOK AWAY: a soft name that resolved before and resolves to nothing now.

  Enclosure(top).prove()  reads the tree as it stands, with no history at all, so it reports what
  the nesting VOIDS right now. A step leaning on something that lives at another level, with
  nothing ordering the two boundaries.

Run it:

    python examples/silent_edges.py

Expected stdout - the refactor passes Transition, Idempotence and explain() without a mark, then
both guards name the two edges it silently dropped and the exact fix, then the fixed declaration
passes both. The "world" is an in-memory set of live resource names.
"""

import asyncio
import sys
from pathlib import Path

try:
    from cabaxiom import Assessment, DriftItem, Enclave, Enclosure, Reconciler, Step, Succession, Transition
    from cabaxiom.laboratory import Idempotence
except ModuleNotFoundError:  # running from a source checkout without an install
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
    from cabaxiom import Assessment, DriftItem, Enclave, Enclosure, Reconciler, Step, Succession, Transition
    from cabaxiom.laboratory import Idempotence

world: set[str] = set()


class Resource(Step):
    """A resource whose existence is a name in a shared in-memory `world` set."""

    name = "resource"

    def assess(self, inputs):
        return Assessment(deviation=[] if self.name in world else [DriftItem(self.name, "not up")]), {}

    def apply(self, inputs):
        if self.name in world:
            return None, {}
        world.add(self.name)
        return [DriftItem(self.name, "brought up")], {}

    def prune(self, inputs):
        world.discard(self.name)
        return [], {}


class Database(Resource):
    name = "database"
    provides = frozenset({"database"})


class Api(Resource):
    name = "api"
    wants = ("database",)          # after every present provider of "database"


class Worker(Resource):
    name = "worker"
    wants = ("database",)


class DataStack(Enclave):
    """The database extracted into its own stack. An Enclave is ONE step to its parent."""


class CarryingStack(Enclave):
    """The same extraction, with the enclave announcing the capability its contents provide."""

    provides = frozenset({"database"})


async def main() -> None:
    database, api, worker = Database(), Api(), Worker()
    flat = (database, api, worker)

    print("BEFORE - one flat declaration")
    ordered = dict(Reconciler(flat).explain().dependencies)   # label -> its prerequisites
    print(f"    api is ordered after: {ordered['Api']}, worker after: {ordered['Worker']}")
    await Reconciler(flat).converge()
    print(f"    world: {sorted(world)}\n")

    # --- the refactor - the database moves into its own stack -------------------------------------
    extracted = (DataStack(Reconciler((database,))), api, worker)

    print("AFTER the refactor - what every existing check says")
    cutover = await Transition(flat, extracted).converge()
    print(f"    Transition cutover.clean : {cutover.clean}")
    print(f"    Idempotence prove().stable: {(await Idempotence(Reconciler(extracted)).prove()).stable}")
    print(f"    explain() dependencies    : {Reconciler(extracted).explain().dependencies}")
    print(f"    world: {sorted(world)}")
    print("    Every mark is green, because nothing failed. Nothing CAN fail here.\n")

    # --- guard one - what the change took away ----------------------------------------------------
    rift = Succession(flat, extracted).compare()
    print("SUCCESSION - compared to the declaration it replaces")
    print(f"    torn: {rift.torn}")
    for shift in rift.quieted:
        lost = ", ".join(step.__class__.__name__ for step in shift.lost)
        print(f"    QUIET  {shift.step.__class__.__name__}.{shift.slot} {shift.name!r}"
              f" stopped waiting for {lost}")
    print()

    # --- guard two - what the tree voids right now ------------------------------------------------
    severance = Enclosure(Reconciler(extracted)).prove()
    print("ENCLOSURE - reading the tree as it stands, with no history")
    print(f"    airtight: {severance.airtight}   (boundaries walked: {severance.boundaries})")
    for cut in severance.severed:
        print(f"    CUT    {cut.leaner}.{cut.slot} {cut.named} is answered by {cut.resolver}")
        print(f"           fix: order {cut.boundary} after {cut.against}")
    print()

    # --- the fix ---------------------------------------------------------------------------------
    fresh_db, fresh_api, fresh_worker = Database(), Api(), Worker()
    plain = (fresh_db, fresh_api, fresh_worker)
    carried = (CarryingStack(Reconciler((fresh_db,))), fresh_api, fresh_worker)

    print("THE FIX - the enclave announces the capability it carries")
    ordered = dict(Reconciler(carried).explain().dependencies)
    print(f"    api is ordered after: {ordered['Api']}")
    healed = Succession(plain, carried).compare()
    airtight = Enclosure(Reconciler(carried)).prove().airtight
    print(f"    Succession torn   : {healed.torn}"
          f"   (the provider changed identity, so it reads as widened and narrowed, not lost)")
    print(f"    Enclosure airtight: {airtight}")

    assert rift.torn and len(rift.quieted) == 2                 # the refactor dropped both edges
    assert not severance.airtight and len(severance.severed) == 2
    assert not healed.torn and airtight

    print("\nOne refactor, two readings, one fix. Neither guard touches the world, so both belong")
    print("in a pre-commit hook or a pull request, where a rehearsal world is not on offer.")


if __name__ == "__main__":
    asyncio.run(main())
