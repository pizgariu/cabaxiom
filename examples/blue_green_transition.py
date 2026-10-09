"""Move a running world from one declaration to the next, tearing down what left it.

A reconciler converges the steps it is handed - but a step REMOVED from the declaration just
stops being mentioned and whatever it built leaks forever, since nothing prunes what is no
longer declared. Transition closes that gap without a state store. The caller still holds the
previous declaration, so the difference is computable.

Transition(previous, desired).converge():

  1. prunes exactly the steps present before but absent now (the leavers), in their own reverse
     dependency order, teardown FIRST so a leaver's port, path or name is free before the new
     world claims it,
  2. converges the desired set,
  3. returns both proofs as one Cutover - `pruned` (the leavers' surviving residue) and
     `residual` (the converge outcome). `clean` is true only when both are empty.

The scenario is a blue -> green cutover. The blue world runs {config, db, legacy-api}. The green
declaration keeps config and db (the SAME step instances), drops legacy-api and adds new-api.

Run it:

    python examples/blue_green_transition.py

Expected stdout - the blue world is brought up, then the transition prunes legacy-api and brings
up new-api while config and db carry over untouched and the Cutover comes back clean. The
"world" is an in-memory set of live resource names.
"""

import asyncio
import sys
from pathlib import Path

try:
    from cabaxiom import Assessment, DriftItem, Reconciler, Step, Transition
except ModuleNotFoundError:  # running from a source checkout without an install
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
    from cabaxiom import Assessment, DriftItem, Reconciler, Step, Transition


class Resource(Step):
    """A resource whose existence is a name in a shared in-memory `world` set. apply() creates it,
    prune() removes it and reports nothing survived."""

    def __init__(self, name: str, world: set[str]):
        self.name = name
        self.world = world

    def assess(self, inputs):
        return Assessment(deviation=[] if self.name in self.world else [DriftItem(self.name, "not running")]), {}

    def apply(self, inputs):
        if self.name in self.world:
            return None, {}
        self.world.add(self.name)
        return [DriftItem(self.name, "brought up")], {}

    def prune(self, inputs):
        self.world.discard(self.name)
        return [], {}   # nothing survived the teardown


class Config(Resource):
    pass


class Db(Resource):
    expects = (Config,)


class Api(Resource):
    expects = (Db,)


async def main() -> None:
    world: set[str] = set()

    # config and db are shared between the two declarations - the SAME instances, so the set difference
    # (by instance identity) leaves them out of the teardown. Only legacy-api leaves - new-api joins.
    config = Config("config", world)
    db = Db("db", world)
    legacy_api = Api("legacy-api", world)
    new_api = Api("new-api", world)

    blue = [config, db, legacy_api]
    green = [config, db, new_api]

    print("Bring up the blue world:")
    await Reconciler(blue).converge()
    print(f"    world now: {sorted(world)}")
    assert sorted(world) == ["config", "db", "legacy-api"]
    print()

    print("Transition blue -> green (prune the leaver, converge the desired set):")
    cutover = await Transition(blue, green).converge()
    print(f"    world now: {sorted(world)}")
    print(f"    cutover clean: {cutover.clean}")
    print(f"    pruned residue: {[str(i) for i in cutover.pruned] or 'nothing survived teardown'}")
    print(f"    applied: {[str(i) for i in cutover.residual.applied]}")
    print(f"    residual: {[str(i) for i in cutover.residual] or 'empty -> green verified'}")

    # The gap Transition exists to close. A plain Reconciler(green).converge() would leave legacy-api
    # running forever, because nothing prunes a step that simply stopped being mentioned.
    assert "legacy-api" not in world
    assert sorted(world) == ["config", "db", "new-api"]
    assert cutover.clean                                   # both channels empty: torn down AND stood up
    # Carried over means UNTOUCHED, not re-applied. Only the joiner shows in the applied channel, so the
    # cutover is the difference between the declarations and not a rebuild of the world.
    assert [item.name for item in cutover.residual.applied] == ["new-api"]

    print()
    print("legacy-api was torn down (absent from green). Config and db carried over untouched.")


if __name__ == "__main__":
    asyncio.run(main())

