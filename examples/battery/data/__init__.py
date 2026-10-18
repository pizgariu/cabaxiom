"""cabaxiom.data - batteries for the data plane's control plane.

Not part of the kernel. Import it explicitly. The SQL batteries take a PORT, never a driver - any
PEP-249 connection the domain's own client minted - so `import cabaxiom.data` stays zero-dependency and
the suite proves every battery on the standard library's sqlite3, a real relational engine in memory.
Each battery is a Step. It self-verifies by re-probing, proves idempotent under Idempotence and tears
down HONESTLY - a table holding rows is left standing and named, never dropped. Lineage is an Observer
on the kernel's own produced() seam - one JSONL line per clean producer, with no step instrumented.

    import sqlite3
    from cabaxiom import Reconciler
    from cabaxiom.data import SQLITE, Fresh, Loaded, Quality, Table

    court = sqlite3.connect(":memory:")
    events = Table(court, "events", ("id INTEGER", "ts REAL", "amount REAL"), dialect=SQLITE)
"""
from .dbt import DbtRun
from .lineage import Lineage
from .sql import ANSI, SQLITE, Connection, Cursor, Dialect, Fresh, Loaded, Quality, Schema, Table

__all__ = ["ANSI", "SQLITE", "Dialect", "Connection", "Cursor",
           "Schema", "Table", "Loaded", "Fresh", "Quality", "DbtRun", "Lineage"]
