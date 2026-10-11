"""SQL state as desired state - a schema, a table, a load, a freshness window and a quality gate, each a
Step over an injected PEP-249 connection - the battery takes a PORT, never a driver.

The zero-dependency paradox is resolved the way the repository beachhead resolved it. The battery never
bundles a client. The domain hands in the connection its own driver minted - Snowflake, Postgres, DuckDB,
sqlite3 - and the battery speaks plain SQL through it. The suite and the examples run against the
standard library's sqlite3 in memory, so every claim here is proven on a REAL relational engine with not
one dependency added.

Identifiers are VETTED, never quoted. A schema, table or column name is refused at construction unless
it is a plain SQL identifier (a letter or underscore, then letters, digits, underscores) and only vetted
names are ever interpolated into a statement - the vet IS the injection guard and it also sidesteps the
PEP-249 paramstyle lottery, because nothing here binds a parameter. A name that would need quoting is
refused, not quoted.

What differs between engines is confined to a Dialect - the existence probes and the schema mechanics,
six sentences. The shipped ANSI speaks information_schema (Postgres, Snowflake and friends). The shipped
SQLITE speaks sqlite_master and pragma_table_info and its schema trio speaks ATTACH - an attached
database is what a schema IS on that engine, said plainly rather than papered over."""
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol, final, override

from ..drift import Artifacts, Assessment, Changes, Drift, DriftItem, FlowAssessment, FlowOutcome
from ..step import Step


class Cursor(Protocol):
    """The slice of PEP-249 a battery actually uses - execute one statement, read its rows."""

    def execute(self, sql: str, /) -> object: ...

    def fetchone(self) -> Any: ...

    def fetchall(self) -> Any: ...


class Connection(Protocol):
    """The port a battery is handed - mint a cursor, commit a write. Any PEP-249 connection satisfies it
    structurally - the domain brings the driver, the battery brings the state machine."""

    def cursor(self) -> Cursor: ...

    def commit(self) -> None: ...


@final
@dataclass(frozen=True)
class Dialect:
    """The six sentences that genuinely differ between engines - existence probes and schema mechanics -
    as a value object, so one battery serves every engine and the difference is data, not subclasses.
    Each sentence is a format string over ONE vetted identifier, `{name}`."""

    schema_exists: str
    create_schema: str
    drop_schema: str
    tables_in_schema: str
    table_exists: str
    column_names: str


# The shipped dialects. ANSI is the information_schema family (Postgres, Snowflake and friends).
# SQLITE says what a schema IS on that engine - an attached database - instead of pretending otherwise.
ANSI = Dialect(
    schema_exists="SELECT schema_name FROM information_schema.schemata WHERE schema_name = '{name}'",
    create_schema="CREATE SCHEMA {name}",
    drop_schema="DROP SCHEMA {name}",
    tables_in_schema="SELECT table_name FROM information_schema.tables WHERE table_schema = '{name}'",
    table_exists="SELECT table_name FROM information_schema.tables WHERE table_name = '{name}'",
    column_names="SELECT column_name FROM information_schema.columns WHERE table_name = '{name}'",
)
SQLITE = Dialect(
    schema_exists="SELECT name FROM pragma_database_list WHERE name = '{name}'",
    create_schema="ATTACH ':memory:' AS {name}",
    drop_schema="DETACH {name}",
    tables_in_schema="SELECT name FROM {name}.sqlite_master WHERE type = 'table'",
    table_exists="SELECT name FROM sqlite_master WHERE type = 'table' AND name = '{name}'",
    column_names="SELECT name FROM pragma_table_info('{name}')",
)


class _Sql(Step):
    """The data-flow bridge the SQL batteries share, the sibling of setup's Fixture and the repository's
    _Standard: a battery reads and writes through the port synchronously and the bridge adapts that to
    the kernel's contract.

    One rule the bridge enforces BY CONSTRUCTION rather than by each battery's discipline. assess() and
    apply() hand back the SAME _produced() reading, taken fresh from the world after the verb ran. That
    is the level-triggered artifacts contract - artifacts are a function of the world, not of the work -
    so a battery cannot accidentally produce on the write and go silent on the read, the exact violation
    the Enclave's clean-reading refusal exists to catch."""

    def __init__(self, connection: Connection, dialect: Dialect) -> None:
        self._connection = connection
        self._dialect = dialect

    @override
    def assess(self, inputs: Artifacts) -> FlowAssessment:
        return Assessment(deviation=self._drift(), footprint=self._footprint()), self._produced()

    @override
    def apply(self, inputs: Artifacts) -> FlowOutcome:
        return self._apply(), self._produced()

    @override
    def prune(self, inputs: Artifacts) -> FlowOutcome:
        return self._prune(), {}

    def _drift(self) -> list[Drift]:
        return []

    def _apply(self) -> Changes:
        return None

    def _prune(self) -> list[Drift]:
        return []

    def _footprint(self) -> list[Drift]:
        return []

    def _produced(self) -> Artifacts:
        return {}

    @staticmethod
    def _named(name: str, slot: str) -> str:
        # The vet that doubles as the injection guard. Only a plain identifier is ever interpolated into
        # a statement. A name that would need quoting is refused, not quoted.
        if name and not name[0].isdigit() and all(ch.isalnum() or ch == "_" for ch in name) and name.isascii():
            return name
        raise ValueError(
            f"{slot} {name!r} is not a plain SQL identifier (a letter or underscore, then letters, digits "
            f"and underscores). Only vetted names are interpolated into statements - the vet is the "
            f"injection guard - so a name that would need quoting is refused, not quoted."
        )

    def _one(self, sql: str) -> object:
        cursor = self._connection.cursor()
        cursor.execute(sql)
        row = cursor.fetchone()
        return None if row is None else row[0]

    def _many(self, sql: str) -> list[object]:
        cursor = self._connection.cursor()
        cursor.execute(sql)
        return [row[0] for row in cursor.fetchall()]

    def _run(self, sql: str) -> None:
        self._connection.cursor().execute(sql)
        self._connection.commit()


class Schema(_Sql):
    """A schema that must exist. Converges with the dialect's create sentence and prunes ONLY when
    empty - a schema holding tables is left standing and named, never cascaded away, exactly as the
    filesystem battery refuses to rm -rf a directory it finds full."""

    def __init__(self, connection: Connection, name: str, dialect: Dialect = ANSI) -> None:
        super().__init__(connection, dialect)
        self._name = self._named(name, "Schema name")

    def __exists(self) -> bool:
        return self._one(self._dialect.schema_exists.format(name=self._name)) is not None

    @override
    def _drift(self) -> list[Drift]:
        return [] if self.__exists() else [DriftItem(self._name, "schema missing")]

    @override
    def _apply(self) -> Changes:
        if self.__exists():
            return None
        self._run(self._dialect.create_schema.format(name=self._name))
        return [DriftItem(self._name, "schema created")]

    @override
    def _prune(self) -> list[Drift]:
        if not self.__exists():
            return []
        tables = self._many(self._dialect.tables_in_schema.format(name=self._name))
        if tables:
            return [DriftItem(self._name, f"left standing: schema holds {len(tables)} tables")]
        self._run(self._dialect.drop_schema.format(name=self._name))
        return []

    @override
    def _footprint(self) -> list[Drift]:
        return [DriftItem(self._name, "schema")] if self.__exists() else []


class Table(_Sql):
    """A table whose declared columns must exist. Creates the table when absent, ADDS a missing column
    when the table stands (additive only - this battery creates and widens, it never retypes and never
    drops a column) and prunes ONLY when the table holds no rows. Data is left standing and named,
    because an honest teardown does not become a data loss.

    Columns are declared as column DDL strings (`"id INTEGER"`, `"name TEXT"`). The NAME - the first
    word - is vetted and checked against the world. The type is the engine's dialect and this battery
    deliberately does not pretend to normalise type names across engines - presence is the contract."""

    def __init__(self, connection: Connection, name: str, columns: tuple[str, ...], dialect: Dialect = ANSI) -> None:
        super().__init__(connection, dialect)
        self._name = self._named(name, "Table name")
        if not columns:
            raise ValueError(f"Table {name!r} declares no columns. A table is its columns - declare at least one.")
        self._columns = columns
        self._heads = tuple(self._named(column.split()[0], "Column name") for column in columns)

    def __exists(self) -> bool:
        return self._one(self._dialect.table_exists.format(name=self._name)) is not None

    def __missing(self) -> list[str]:
        present = {str(column) for column in self._many(self._dialect.column_names.format(name=self._name))}
        return [column for column, head in zip(self._columns, self._heads) if head not in present]

    @override
    def _drift(self) -> list[Drift]:
        if not self.__exists():
            return [DriftItem(self._name, "table missing")]
        missing = self.__missing()
        if missing:
            named = ", ".join(column.split()[0] for column in missing)
            return [DriftItem(self._name, f"columns missing: {named}")]
        return []

    @override
    def _apply(self) -> Changes:
        if not self.__exists():
            self._run(f"CREATE TABLE {self._name} ({', '.join(self._columns)})")
            return [DriftItem(self._name, "table created")]
        missing = self.__missing()
        if not missing:
            return None
        for column in missing:
            self._run(f"ALTER TABLE {self._name} ADD COLUMN {column}")
        named = ", ".join(column.split()[0] for column in missing)
        return [DriftItem(self._name, f"columns added: {named}")]

    @override
    def _prune(self) -> list[Drift]:
        if not self.__exists():
            return []
        held = self._one(f"SELECT COUNT(*) FROM {self._name}")
        if isinstance(held, int) and held > 0:
            return [DriftItem(self._name, f"left standing: table holds {held} rows")]
        self._run(f"DROP TABLE {self._name}")
        return []

    @override
    def _footprint(self) -> list[Drift]:
        return [DriftItem(self._name, "table")] if self.__exists() else []


class Loaded(_Sql):
    """A table loaded from a source query, incrementally, idempotently - the watermark is the judge.

    `source` is the domain's own SELECT (its SQL, its responsibility), `key` a NUMERIC, monotonically
    growing column - an id, an epoch. Numeric on purpose. The watermark's VALUE is interpolated into the
    incremental insert and a battery that quotes your values is a battery that one day misquotes them,
    so a non-numeric watermark is refused at the moment it is read, never guessed around.

    Prune is a deliberate no-op. An un-load that deletes rows is not an undo, it is a data loss, so the
    rows are left standing exactly as a RepoSetting leaves its setting - some state has no absent form
    worth restoring. The artifacts speak the pointers doctrine. The row count and the watermark cross
    the run, the rows themselves stay in the engine."""

    def __init__(self, connection: Connection, table: str, source: str, key: str, dialect: Dialect = ANSI) -> None:
        super().__init__(connection, dialect)
        self._table = self._named(table, "Loaded table")
        self._source = source
        self._key = self._named(key, "Watermark key")

    def __watermark(self) -> float | None:
        mark = self._one(f"SELECT MAX({self._key}) FROM {self._table}")
        if mark is None or isinstance(mark, (int, float)):
            return mark
        raise ValueError(
            f"Loaded {self._table!r} read the watermark {mark!r} from `{self._key}`, which is not a "
            f"number. The watermark key must be numeric (an id, an epoch), because its value is "
            f"interpolated into the incremental insert and a battery that quotes your values is a "
            f"battery that one day misquotes them."
        )

    def __pending(self) -> int:
        mark = self.__watermark()
        gate = "" if mark is None else f" WHERE pending.{self._key} > {mark}"
        counted = self._one(f"SELECT COUNT(*) FROM ({self._source}) AS pending{gate}")
        return counted if isinstance(counted, int) else 0

    @override
    def _drift(self) -> list[Drift]:
        pending = self.__pending()
        return [] if pending == 0 else [DriftItem(self._table, f"{pending} source rows not loaded")]

    @override
    def _apply(self) -> Changes:
        mark = self.__watermark()
        pending = self.__pending()
        if pending == 0:
            return None
        gate = "" if mark is None else f" WHERE pending.{self._key} > {mark}"
        self._run(f"INSERT INTO {self._table} SELECT * FROM ({self._source}) AS pending{gate}")
        return [DriftItem(self._table, f"{pending} rows loaded")]

    @override
    def _produced(self) -> Artifacts:
        held = self._one(f"SELECT COUNT(*) FROM {self._table}")
        mark = self.__watermark()
        return {f"{self._table}/rows": held, f"{self._table}/watermark": mark}


class Fresh(_Sql):
    """A freshness window, read-only. The newest value of a timestamp column must be within `within`
    seconds of now. A pure sensor - no apply, no prune - whose deviation is the staleness said in
    seconds and whose artifact is the latest mark, a pointer for whoever downstream wants it. `now` is
    injectable for the same reason every clock in this kernel is. A test rehearses time, it does not
    wait for it."""

    def __init__(self, connection: Connection, table: str, column: str, within: float,
                 dialect: Dialect = ANSI, now: Callable[[], float] = time.time) -> None:
        super().__init__(connection, dialect)
        self._table = self._named(table, "Fresh table")
        self._column = self._named(column, "Fresh column")
        self._within = within
        self._now = now

    def __latest(self) -> float | None:
        mark = self._one(f"SELECT MAX({self._column}) FROM {self._table}")
        return mark if isinstance(mark, (int, float)) else None

    @override
    def _drift(self) -> list[Drift]:
        latest = self.__latest()
        if latest is None:
            return [DriftItem(self._table, "holds no rows to be fresh")]
        age = self._now() - latest
        if age <= self._within:
            return []
        return [DriftItem(self._table, f"stale: newest {self._column} is {age:.0f}s old against a budget of {self._within:.0f}s")]

    @override
    def _produced(self) -> Artifacts:
        latest = self.__latest()
        return {} if latest is None else {f"{self._table}/latest": latest}


class Quality(_Sql):
    """A quality gate, read-only, speaking the Assessment's channels as they were meant. Each check is a
    SQL sentence returning ONE number, the count of violating rows and zero means it holds. A CRITICAL
    check that fires lands in `deviation` and dirties the proof. An ADVISORY check lands in `advisory`,
    which never dirties a proof - advice is exactly what that channel exists for and no residual is
    poisoned by a warning."""

    def __init__(self, connection: Connection, critical: Mapping[str, str] | None = None,
                 advisory: Mapping[str, str] | None = None, dialect: Dialect = ANSI) -> None:
        super().__init__(connection, dialect)
        self._critical = dict(critical or {})
        self._advisory = dict(advisory or {})

    def __fired(self, checks: Mapping[str, str]) -> list[Drift]:
        findings: list[Drift] = []
        for name, sql in checks.items():
            violations = self._one(sql)
            if isinstance(violations, int) and violations > 0:
                findings.append(DriftItem(name, f"{violations} rows violate {name}"))
        return findings

    @override
    def assess(self, inputs: Artifacts) -> FlowAssessment:
        return Assessment(deviation=self.__fired(self._critical), advisory=self.__fired(self._advisory)), {}

