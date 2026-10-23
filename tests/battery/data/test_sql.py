"""The SQL batteries against a REAL relational engine, the standard library's sqlite3 in memory. No
mocks and no fakes - the port is the actual PEP-249 surface, which is the whole claim of the beachhead:
the domain brings the driver, the battery brings the state machine."""
import sqlite3
import unittest

from battery.data import SQLITE, Fresh, Loaded, Quality, Schema, Table
from cabaxiom import Reconciler
from cabaxiom.laboratory import Idempotence


class _SqlCase(unittest.IsolatedAsyncioTestCase):
    def _court(self) -> sqlite3.Connection:
        court = sqlite3.connect(":memory:")
        self.addCleanup(court.close)
        return court


class BareBridgeTests(_SqlCase):
    """The bridge's defaults are the contract a domain's own battery builds on, exactly as the other two
    beachheads pin theirs. Override only the judgements you own, where the rest stays quiet."""

    async def test_a_battery_that_overrides_nothing_is_quiet_on_every_channel(self):
        from battery.data.sql import _Sql

        class Inert(_Sql):
            pass

        reconciler = Reconciler((Inert(self._court(), SQLITE),))
        self.assertEqual(await reconciler.converge(), [])
        self.assertEqual(await reconciler.prune(), [])


class SchemaTests(_SqlCase):
    async def test_it_converges_self_verifies_and_proves_idempotent(self):
        court = self._court()
        reconciler = Reconciler((Schema(court, "analytics", dialect=SQLITE),))
        residual = await reconciler.converge()
        self.assertEqual(residual, [])
        self.assertEqual([item.message for item in residual.applied], ["schema created"])
        proof = await Idempotence(reconciler).prove()
        self.assertTrue(proof.stable)

    async def test_prune_removes_an_empty_schema_and_refuses_a_full_one(self):
        court = self._court()
        schema = Schema(court, "analytics", dialect=SQLITE)
        reconciler = Reconciler((schema,))
        await reconciler.converge()
        court.execute("CREATE TABLE analytics.kept (id INTEGER)")
        court.commit()
        residue = await reconciler.prune()
        self.assertEqual([item.message for item in residue], ["left standing: schema holds 1 tables"])
        court.execute("DROP TABLE analytics.kept")
        court.commit()
        self.assertEqual(await reconciler.prune(), [])          # empty now, so the teardown completes
        self.assertEqual(await Reconciler((schema,)).prune(), [])   # and pruning the absent is a no-op

    async def test_the_footprint_names_what_a_teardown_would_remove(self):
        court = self._court()
        schema = Schema(court, "analytics", dialect=SQLITE)
        assessment, _ = schema.assess({})
        self.assertEqual(list(assessment.footprint), [])        # nothing standing, nothing to remove
        await Reconciler((schema,)).converge()
        assessment, _ = schema.assess({})
        self.assertEqual([item.message for item in assessment.footprint], ["schema"])

    def test_a_name_that_would_need_quoting_is_refused_not_quoted(self):
        with self.assertRaises(ValueError) as refused:
            Schema(self._court(), "analytics; DROP TABLE users", dialect=SQLITE)
        self.assertIn("is not a plain SQL identifier", str(refused.exception))
        self.assertIn("refused, not quoted", str(refused.exception))
        with self.assertRaises(ValueError):
            Schema(self._court(), "1st", dialect=SQLITE)   # a leading digit is no identifier either


class TableTests(_SqlCase):
    async def test_it_creates_widens_and_settles(self):
        court = self._court()
        table = Table(court, "events", ("id INTEGER", "ts REAL"), dialect=SQLITE)
        reconciler = Reconciler((table,))
        residual = await reconciler.converge()
        self.assertEqual(residual, [])
        self.assertEqual([item.message for item in residual.applied], ["table created"])
        widened = Table(court, "events", ("id INTEGER", "ts REAL", "amount REAL"), dialect=SQLITE)
        residual = await Reconciler((widened,)).converge()
        self.assertEqual([item.message for item in residual.applied], ["columns added: amount"])
        proof = await Idempotence(Reconciler((widened,))).prove()
        self.assertTrue(proof.stable)

    async def test_the_drift_names_the_missing_columns(self):
        court = self._court()
        court.execute("CREATE TABLE events (id INTEGER)")
        court.commit()
        table = Table(court, "events", ("id INTEGER", "ts REAL", "amount REAL"), dialect=SQLITE)
        assessment, _ = table.assess({})
        self.assertEqual([item.message for item in assessment.deviation], ["columns missing: ts, amount"])

    async def test_prune_drops_an_empty_table_and_leaves_data_standing(self):
        court = self._court()
        table = Table(court, "events", ("id INTEGER",), dialect=SQLITE)
        reconciler = Reconciler((table,))
        await reconciler.converge()
        court.execute("INSERT INTO events VALUES (1)")
        court.commit()
        residue = await reconciler.prune()
        self.assertEqual([item.message for item in residue], ["left standing: table holds 1 rows"])
        court.execute("DELETE FROM events")
        court.commit()
        self.assertEqual(await reconciler.prune(), [])
        self.assertEqual(await Reconciler((table,)).prune(), [])   # absent already: a clean no-op
        assessment, _ = table.assess({})
        self.assertEqual(list(assessment.footprint), [])

    def test_a_table_without_columns_is_refused(self):
        with self.assertRaises(ValueError) as refused:
            Table(self._court(), "events", (), dialect=SQLITE)
        self.assertIn("declares no columns", str(refused.exception))

    def test_a_column_name_is_vetted_like_every_identifier(self):
        with self.assertRaises(ValueError) as refused:
            Table(self._court(), "events", ("id; DROP TABLE users INTEGER",), dialect=SQLITE)
        self.assertIn("is not a plain SQL identifier", str(refused.exception))


class LoadedTests(_SqlCase):
    def _world(self):
        court = self._court()
        court.execute("CREATE TABLE raw (id INTEGER, amount REAL)")
        court.execute("CREATE TABLE events (id INTEGER, amount REAL)")
        court.executemany("INSERT INTO raw VALUES (?, ?)", [(1, 5.0), (2, 7.0)])
        court.commit()
        return court

    async def test_it_loads_then_loads_only_the_increment(self):
        court = self._world()
        loaded = Loaded(court, "events", "SELECT * FROM raw", "id", dialect=SQLITE)
        reconciler = Reconciler((loaded,))
        residual = await reconciler.converge()
        self.assertEqual(residual, [])
        self.assertEqual([item.message for item in residual.applied], ["2 rows loaded"])
        self.assertEqual(residual.produced[loaded], {"events/rows": 2, "events/watermark": 2})

        court.execute("INSERT INTO raw VALUES (3, 9.0)")   # the world moves
        court.commit()
        residual = await reconciler.converge()
        self.assertEqual([item.message for item in residual.applied], ["1 rows loaded"])
        self.assertEqual(residual.produced[loaded]["events/watermark"], 3)
        proof = await Idempotence(reconciler).prove()
        self.assertTrue(proof.stable)

    async def test_prune_is_a_deliberate_no_op_because_an_unload_is_a_data_loss(self):
        court = self._world()
        reconciler = Reconciler((Loaded(court, "events", "SELECT * FROM raw", "id", dialect=SQLITE),))
        await reconciler.converge()
        self.assertEqual(await reconciler.prune(), [])
        held = court.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        self.assertEqual(held, 2)   # the rows stand: some state has no absent form worth restoring

    async def test_a_non_numeric_watermark_is_refused_never_quoted_around(self):
        court = self._court()
        court.execute("CREATE TABLE raw (name TEXT)")
        court.execute("CREATE TABLE events (name TEXT)")
        court.execute("INSERT INTO events VALUES ('zeta')")
        court.commit()
        loaded = Loaded(court, "events", "SELECT * FROM raw", "name", dialect=SQLITE)
        with self.assertRaises(ValueError) as refused:
            loaded.assess({})
        self.assertIn("is not a number", str(refused.exception))
        self.assertIn("misquotes", str(refused.exception))


class FreshTests(_SqlCase):
    def _world(self, latest: float):
        court = self._court()
        court.execute("CREATE TABLE events (ts REAL)")
        court.execute(f"INSERT INTO events VALUES ({latest})")
        court.commit()
        return court

    def test_fresh_within_budget_is_clean_and_points_at_the_latest_mark(self):
        fresh = Fresh(self._world(90.0), "events", "ts", within=30.0, dialect=SQLITE, now=lambda: 100.0)
        assessment, artifacts = fresh.assess({})
        self.assertEqual(list(assessment.deviation), [])
        self.assertEqual(artifacts, {"events/latest": 90.0})

    def test_stale_says_the_age_against_the_budget(self):
        fresh = Fresh(self._world(10.0), "events", "ts", within=30.0, dialect=SQLITE, now=lambda: 100.0)
        assessment, _ = fresh.assess({})
        self.assertEqual([item.message for item in assessment.deviation],
                         ["stale: newest ts is 90s old against a budget of 30s"])

    def test_an_empty_table_cannot_be_fresh_and_says_so(self):
        court = self._court()
        court.execute("CREATE TABLE events (ts REAL)")
        court.commit()
        fresh = Fresh(court, "events", "ts", within=30.0, dialect=SQLITE, now=lambda: 100.0)
        assessment, artifacts = fresh.assess({})
        self.assertEqual([item.message for item in assessment.deviation], ["holds no rows to be fresh"])
        self.assertEqual(artifacts, {})


class QualityTests(_SqlCase):
    def _world(self):
        court = self._court()
        court.execute("CREATE TABLE events (amount REAL, name TEXT)")
        court.executemany("INSERT INTO events VALUES (?, ?)", [(5.0, "a"), (-1.0, None)])
        court.commit()
        return court

    async def test_a_critical_check_dirties_the_proof_and_an_advisory_never_does(self):
        court = self._world()
        gate = Quality(court,
                       critical={"no_negative_amount": "SELECT COUNT(*) FROM events WHERE amount < 0"},
                       advisory={"names_filled": "SELECT COUNT(*) FROM events WHERE name IS NULL"},
                       dialect=SQLITE)
        assessment, _ = gate.assess({})
        self.assertEqual([item.message for item in assessment.deviation], ["1 rows violate no_negative_amount"])
        self.assertEqual([item.message for item in assessment.advisory], ["1 rows violate names_filled"])

        court.execute("DELETE FROM events WHERE amount < 0")   # fix the critical, keep the advisory
        court.commit()
        residual = await Reconciler((gate,)).converge()
        self.assertEqual(residual, [])   # advice never dirties a proof - that is the channel's whole point
        assessment, _ = gate.assess({})
        self.assertEqual(len(assessment.advisory), 0)   # the offending row left with the delete

    async def test_a_clean_gate_is_silent_on_both_channels(self):
        court = self._world()
        court.execute("DELETE FROM events")
        court.commit()
        gate = Quality(court, critical={"any": "SELECT COUNT(*) FROM events"}, dialect=SQLITE)
        assessment, _ = gate.assess({})
        self.assertEqual(list(assessment.deviation), [])
        self.assertEqual(list(assessment.advisory), [])


if __name__ == "__main__":
    unittest.main()
