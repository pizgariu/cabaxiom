"""A miniature warehouse as desired state, proven end to end on the standard library's sqlite3.

The battery.data batteries take a PORT, never a driver: the connection below is stdlib sqlite3 and the
same five steps run unchanged against Postgres or Snowflake the moment the domain injects its own PEP-249
connection and the ANSI dialect. The arc is the beachhead's whole pitch - not rigor, PROOFS:

    declare -> converge -> lineage for free -> prove idempotent -> forecast a failure -> tear down HONESTLY
"""
import asyncio
import io
import sqlite3

from battery.data import SQLITE, Fresh, Lineage, Loaded, Quality, Schema, Table

from cabaxiom import Journal, Reconciler
from cabaxiom.core.record import Chorus
from cabaxiom.laboratory import Idempotence

NOW = 1_000_000.0   # the example rehearses time instead of waiting for it, like every test in this house


async def main() -> None:
    court = sqlite3.connect(":memory:")

    # The world that already exists. A landing table some upstream keeps feeding.
    court.execute("CREATE TABLE raw (id INTEGER, ts REAL, amount REAL, label TEXT)")
    court.executemany("INSERT INTO raw VALUES (?, ?, ?, ?)",
                      [(1, NOW - 90, 5.0, "a"), (2, NOW - 60, 7.5, None), (3, NOW - 30, 2.5, "c")])
    court.commit()

    # The desired state, declared - a schema, a typed table, an incremental load, a freshness window and
    # a quality gate - reads ordered after the load through `uses`, an instance edge.
    schema = Schema(court, "analytics", dialect=SQLITE)
    events = Table(court, "events", ("id INTEGER", "ts REAL", "amount REAL", "label TEXT"), dialect=SQLITE)
    loaded = Loaded(court, "events", "SELECT * FROM raw", "id", dialect=SQLITE)
    loaded.uses = (events,)
    fresh = Fresh(court, "events", "ts", within=120.0, dialect=SQLITE, now=lambda: NOW)
    gate = Quality(court,
                   critical={"no_negative_amount": "SELECT COUNT(*) FROM events WHERE amount < 0"},
                   advisory={"labels_filled": "SELECT COUNT(*) FROM events WHERE label IS NULL"},
                   dialect=SQLITE)
    fresh.uses = (loaded,)
    gate.uses = (loaded,)

    trace = io.StringIO()
    reconciler = Reconciler((schema, events, loaded, fresh, gate), observer=Chorus(Lineage(trace), Journal()))

    residual = await reconciler.converge()
    print("applied: ", [item.message for item in residual.applied])
    print("residual:", list(residual), "(empty means the warehouse is VERIFIED, advice and all)")

    print("lineage, for free, no step instrumented:")
    for line in trace.getvalue().splitlines():
        print("  ", line)

    proof = await Idempotence(reconciler).prove()
    print("idempotent:", proof.stable, "(a second converge changed nothing)")

    casualty = reconciler.foresee(loaded)
    print(f"if the load fell: blocked={casualty.blocked} (the forecast the Ledger would enforce)")

    court.execute("INSERT INTO raw VALUES (4, ?, 9.0, 'd')", (NOW - 5,))   # the world moves on
    court.commit()
    caught_up = await reconciler.converge()
    print("the world moved:", [item.message for item in caught_up.applied], "- one increment, not a reload")

    residue = await reconciler.prune()
    print("teardown:", [item.message for item in residue])
    print("(the table held rows, so the teardown REFUSED the data loss and said so - honest reversibility)")

    assert residual == [] and proof.stable and any("left standing" in item.message for item in residue)


if __name__ == "__main__":
    asyncio.run(main())
