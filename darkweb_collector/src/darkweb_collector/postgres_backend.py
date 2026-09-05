from __future__ import annotations

import atexit
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
import os
import re
from threading import Condition, Lock, RLock
import time
from typing import Any


DEFAULT_REQUIRED_VERSION = "0006_postgres_read_paths"
_SCHEMA_RE = re.compile(r"[a-z][a-z0-9_]{0,62}")

# libpq transaction status values exposed by psycopg2.extensions.  Keeping the
# constants local avoids importing psycopg2 while SQLite is the active backend.
_TX_IDLE = 0
_TX_ACTIVE = 1
_TX_INTRANS = 2
_TX_INERROR = 3
_TX_UNKNOWN = 4


class PostgreSQLBackendError(RuntimeError):
    """Base error raised by the PostgreSQL compatibility layer."""


class PostgreSQLIntegrityError(PostgreSQLBackendError):
    """A PostgreSQL constraint or integrity violation."""


class PostgreSQLOperationalError(PostgreSQLBackendError):
    """A PostgreSQL connection or operational failure."""


def _compat_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    return value


class CompatRow(Mapping[str, Any]):
    """A small sqlite3.Row compatible mapping with numeric indexing."""

    def __init__(self, columns: Sequence[str], values: Sequence[Any]) -> None:
        self._columns = tuple(columns)
        self._values = tuple(_compat_value(value) for value in values)
        self._mapping = dict(zip(self._columns, self._values))

    def __getitem__(self, key: str | int) -> Any:
        if isinstance(key, int):
            return self._values[key]
        return self._mapping[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._columns)

    def __len__(self) -> int:
        return len(self._columns)

    def keys(self):
        return self._mapping.keys()


def _replace_qmark_parameters(sql_text: str) -> str:
    """Convert SQLite qmarks and escape original percent signs for psycopg2.

    Only placeholders generated from ``?`` remain single ``%s`` tokens.
    """

    result: list[str] = []
    index = 0
    state = "normal"
    while index < len(sql_text):
        char = sql_text[index]
        next_char = sql_text[index + 1] if index + 1 < len(sql_text) else ""
        if state == "normal":
            if char == "'":
                state = "single"
            elif char == '"':
                state = "double"
            elif char == "-" and next_char == "-":
                state = "line_comment"
                result.append(char)
                index += 1
                char = next_char
            elif char == "/" and next_char == "*":
                state = "block_comment"
                result.append(char)
                index += 1
                char = next_char
            elif char == "?":
                result.append("%s")
                index += 1
                continue
        elif state == "single":
            if char == "'" and next_char == "'":
                result.extend([char, next_char])
                index += 2
                continue
            if char == "'":
                state = "normal"
        elif state == "double":
            if char == '"' and next_char == '"':
                result.extend([char, next_char])
                index += 2
                continue
            if char == '"':
                state = "normal"
        elif state == "line_comment":
            if char in "\r\n":
                state = "normal"
        elif state == "block_comment" and char == "*" and next_char == "/":
            result.extend([char, next_char])
            index += 2
            state = "normal"
            continue
        if char == "%":
            result.append("%%")
        else:
            result.append(char)
        index += 1
    return "".join(result)


def translate_sql(sql_text: str) -> str:
    """Translate only syntax that is mechanically equivalent on both engines."""

    translated = _replace_qmark_parameters(sql_text)
    translated = re.sub(r"\bifnull\s*\(", "COALESCE(", translated, flags=re.IGNORECASE)
    translated = re.sub(
        r"\bGROUP_CONCAT\s*\(", "STRING_AGG(", translated, flags=re.IGNORECASE
    )
    if re.search(r"\bINSERT\s+OR\s+IGNORE\s+INTO\b", translated, flags=re.IGNORECASE):
        translated = re.sub(
            r"\bINSERT\s+OR\s+IGNORE\s+INTO\b", "INSERT INTO", translated,
            flags=re.IGNORECASE,
        )
        stripped = translated.rstrip()
        suffix = ";" if stripped.endswith(";") else ""
        if suffix:
            stripped = stripped[:-1].rstrip()
        translated = stripped + " ON CONFLICT DO NOTHING" + suffix
    return translated


def _insert_table(sql_text: str) -> str | None:
    match = re.match(
        r'\s*INSERT\s+INTO\s+(?:public\.)?["\']?([A-Za-z_][A-Za-z0-9_]*)',
        sql_text, flags=re.IGNORECASE,
    )
    return match.group(1).lower() if match else None


def _driver_exception(exc: Exception) -> PostgreSQLBackendError:
    class_name = type(exc).__name__.lower()
    if "integrity" in class_name or getattr(exc, "pgcode", "") in {
        "23502", "23503", "23505", "23514", "23P01"
    }:
        return PostgreSQLIntegrityError(str(exc))
    if any(
        token in class_name
        for token in ("operational", "interface", "timeout", "poolerror")
    ):
        return PostgreSQLOperationalError(str(exc))
    return PostgreSQLBackendError(str(exc))


def _transaction_status(raw: Any) -> int:
    """Return the libpq transaction status; unusable handles are unknown."""

    if bool(getattr(raw, "closed", False)):
        return _TX_UNKNOWN
    getter = getattr(raw, "get_transaction_status", None)
    if not callable(getter):
        return _TX_UNKNOWN
    try:
        status = int(getter())
    except Exception:
        return _TX_UNKNOWN
    if status not in {
        _TX_IDLE, _TX_ACTIVE, _TX_INTRANS, _TX_INERROR, _TX_UNKNOWN,
    }:
        return _TX_UNKNOWN
    return status


def _driver_execute_values(
    cursor: Any,
    sql_text: str,
    parameters: Sequence[Sequence[Any]],
    *,
    template: str | None,
    page_size: int,
) -> None:
    from psycopg2.extras import execute_values  # type: ignore

    execute_values(
        cursor,
        sql_text,
        parameters,
        template=template,
        page_size=page_size,
        fetch=False,
    )


class PostgresCursor:
    def __init__(self, connection: "PostgresConnection") -> None:
        self._connection = connection
        self._cursor = connection._raw.cursor()
        self.lastrowid: int | None = None

    @property
    def rowcount(self) -> int:
        return int(self._cursor.rowcount)

    @property
    def description(self):
        return self._cursor.description

    def _columns(self) -> list[str]:
        return [str(item[0]) for item in (self._cursor.description or ())]

    def execute(
        self,
        sql_text: str,
        parameters: Sequence[Any] | None = None,
        *,
        return_identity: bool | None = None,
    ) -> "PostgresCursor":
        translated = translate_sql(sql_text)
        table_name = _insert_table(translated)
        has_returning = bool(
            re.search(r"\bRETURNING\b", translated, flags=re.IGNORECASE)
        )
        is_identity_insert = table_name in self._connection.identity_tables
        if return_identity is True and not is_identity_insert:
            raise PostgreSQLBackendError(
                "identity RETURNING requested for a non-identity INSERT"
            )
        should_capture_id = (
            is_identity_insert
            if return_identity is None
            else bool(return_identity)
        )
        if should_capture_id and not has_returning:
            stripped = translated.rstrip()
            suffix = ";" if stripped.endswith(";") else ""
            if suffix:
                stripped = stripped[:-1].rstrip()
            translated = stripped + " RETURNING id" + suffix
        try:
            self.lastrowid = None
            self._cursor.execute(translated, tuple(parameters or ()))
            if should_capture_id:
                row = self._cursor.fetchone()
                self.lastrowid = int(row[0]) if row else None
            return self
        except PostgreSQLBackendError:
            raise
        except Exception as exc:
            raise _driver_exception(exc) from exc

    def executemany(
        self, sql_text: str, parameters: Sequence[Sequence[Any]]
    ) -> "PostgresCursor":
        try:
            self.lastrowid = None
            self._cursor.executemany(translate_sql(sql_text), parameters)
            return self
        except Exception as exc:
            raise _driver_exception(exc) from exc

    def execute_values(
        self,
        sql_text: str,
        parameters: Sequence[Sequence[Any]],
        *,
        template: str | None = None,
        page_size: int = 500,
    ) -> "PostgresCursor":
        """Run an explicitly requested psycopg2 ``execute_values`` batch.

        ``sql_text`` uses one qmark for the values list, for example
        ``INSERT INTO t(a, b) VALUES ?``.  An optional template also uses
        qmarks.  Ordinary ``executemany`` remains unchanged.
        """

        if page_size < 1:
            raise PostgreSQLBackendError("execute_values page_size must be positive")
        try:
            self.lastrowid = None
            _driver_execute_values(
                self._cursor,
                translate_sql(sql_text),
                parameters,
                template=(
                    translate_sql(template) if template is not None else None
                ),
                page_size=page_size,
            )
            return self
        except PostgreSQLBackendError:
            raise
        except Exception as exc:
            raise _driver_exception(exc) from exc

    def fetchone(self) -> CompatRow | None:
        try:
            row = self._cursor.fetchone()
        except Exception as exc:
            raise _driver_exception(exc) from exc
        return CompatRow(self._columns(), row) if row is not None else None

    def fetchmany(self, size: int | None = None) -> list[CompatRow]:
        try:
            rows = self._cursor.fetchmany(size) if size is not None else self._cursor.fetchmany()
        except Exception as exc:
            raise _driver_exception(exc) from exc
        columns = self._columns()
        return [CompatRow(columns, row) for row in rows]

    def fetchall(self) -> list[CompatRow]:
        try:
            rows = self._cursor.fetchall()
        except Exception as exc:
            raise _driver_exception(exc) from exc
        columns = self._columns()
        return [CompatRow(columns, row) for row in rows]

    def __iter__(self) -> "PostgresCursor":
        return self

    def __next__(self) -> CompatRow:
        row = self.fetchone()
        if row is None:
            raise StopIteration
        return row

    def close(self) -> None:
        self._cursor.close()

    def __enter__(self) -> "PostgresCursor":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> bool:
        self.close()
        return False


class _CheckoutPermit:
    """Release one checkout slot exactly once."""

    def __init__(self, gate: "_CheckoutGate") -> None:
        self._gate = gate
        self._lock = Lock()
        self._released = False

    def release(self) -> None:
        with self._lock:
            if self._released:
                return
            self._released = True
        self._gate._release()


class _CheckoutGate:
    """A close-aware bounded wait queue in front of psycopg2's pool."""

    def __init__(self, capacity: int) -> None:
        if capacity < 1:
            raise PostgreSQLBackendError(
                "PostgreSQL checkout capacity must be positive"
            )
        self.capacity = int(capacity)
        self._available = int(capacity)
        self._closed = False
        self._condition = Condition(Lock())

    @property
    def available(self) -> int:
        with self._condition:
            return self._available

    def acquire(self, timeout: float) -> _CheckoutPermit | None:
        deadline = time.monotonic() + max(0.0, float(timeout))
        with self._condition:
            while True:
                if self._closed:
                    raise PostgreSQLOperationalError(
                        "PostgreSQL connection pool is closed"
                    )
                if self._available > 0:
                    self._available -= 1
                    return _CheckoutPermit(self)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                self._condition.wait(timeout=remaining)

    def _release(self) -> None:
        with self._condition:
            if self._available >= self.capacity:
                raise PostgreSQLBackendError(
                    "PostgreSQL checkout permit released more than once"
                )
            self._available += 1
            self._condition.notify()

    def close(self) -> None:
        with self._condition:
            self._closed = True
            self._condition.notify_all()


@dataclass
class _PoolEntry:
    pool: Any
    validated_releases: set[tuple[str, str, str]] = field(default_factory=set)
    identity_tables: dict[str, frozenset[str]] = field(default_factory=dict)
    checkout_gate: _CheckoutGate | None = None

    def __post_init__(self) -> None:
        if self.checkout_gate is not None:
            return
        configured_maximum = getattr(self.pool, "maxconn", None)
        try:
            maximum = int(configured_maximum)
        except (TypeError, ValueError):
            maximum = _pool_sizes()[1]
        if maximum < 1:
            maximum = _pool_sizes()[1]
        self.checkout_gate = _CheckoutGate(maximum)


_POOL_LOCK = RLock()
_POOL_PID = os.getpid()
_POOLS: dict[tuple[str, int, int, int], _PoolEntry] = {}


def _pool_sizes() -> tuple[int, int]:
    try:
        minimum = max(1, int(os.environ.get("DARKWEB_POSTGRES_POOL_MIN", "1")))
        maximum = max(1, int(os.environ.get("DARKWEB_POSTGRES_POOL_MAX", "4")))
    except ValueError as exc:
        raise PostgreSQLBackendError("PostgreSQL pool sizes must be integers") from exc
    if minimum > maximum:
        raise PostgreSQLBackendError("PostgreSQL pool minimum cannot exceed maximum")
    return minimum, maximum


def _connect_timeout() -> int:
    try:
        timeout = int(os.environ.get("DARKWEB_POSTGRES_CONNECT_TIMEOUT_SECONDS", "5"))
    except ValueError as exc:
        raise PostgreSQLBackendError("PostgreSQL connect timeout must be an integer") from exc
    if timeout < 1 or timeout > 300:
        raise PostgreSQLBackendError("PostgreSQL connect timeout must be between 1 and 300 seconds")
    return timeout


def _pool_wait_timeout() -> int:
    try:
        timeout = int(
            os.environ.get(
                "DARKWEB_POSTGRES_POOL_WAIT_TIMEOUT_SECONDS",
                "30",
            )
        )
    except ValueError as exc:
        raise PostgreSQLBackendError(
            "PostgreSQL pool wait timeout must be an integer"
        ) from exc
    if timeout < 1 or timeout > 300:
        raise PostgreSQLBackendError(
            "PostgreSQL pool wait timeout must be between 1 and 300 seconds"
        )
    return timeout


def _load_driver():
    try:
        from psycopg2 import pool, sql  # type: ignore
    except ImportError as exc:
        raise PostgreSQLBackendError(
            "PostgreSQL selected but psycopg2-binary is not installed"
        ) from exc
    return pool.ThreadedConnectionPool, sql


def _discard_inherited_pools() -> None:
    """Drop pool objects inherited across fork without checking out their sockets."""

    global _POOL_PID, _POOLS
    current_pid = os.getpid()
    if current_pid == _POOL_PID:
        return
    _POOLS = {}
    _POOL_PID = current_pid


def close_postgres_pools() -> None:
    global _POOLS
    with _POOL_LOCK:
        _discard_inherited_pools()
        entries = list(_POOLS.values())
        _POOLS = {}
    for entry in entries:
        entry.checkout_gate.close()
        try:
            entry.pool.closeall()
        except Exception:
            pass


atexit.register(close_postgres_pools)


def _pool_entry(database_url: str) -> _PoolEntry:
    minimum, maximum = _pool_sizes()
    timeout = _connect_timeout()
    key = (database_url, minimum, maximum, timeout)
    with _POOL_LOCK:
        _discard_inherited_pools()
        existing = _POOLS.get(key)
        if existing is not None:
            return existing
        pool_class, _ = _load_driver()
        try:
            raw_pool = pool_class(
                minimum, maximum, database_url,
                application_name="darkweb-threat-intelligence",
                connect_timeout=timeout,
            )
        except Exception as exc:
            raise _driver_exception(exc) from exc
        entry = _PoolEntry(
            pool=raw_pool,
            checkout_gate=_CheckoutGate(maximum),
        )
        _POOLS[key] = entry
        return entry


def _set_session(raw: Any, schema: str, *, read_only: bool) -> None:
    if schema and not _SCHEMA_RE.fullmatch(schema):
        raise PostgreSQLBackendError("Invalid PostgreSQL release schema")
    try:
        status = _transaction_status(raw)
        if status in {_TX_INTRANS, _TX_INERROR}:
            raw.rollback()
        elif status != _TX_IDLE:
            raise PostgreSQLOperationalError(
                "PostgreSQL pooled connection is not safe to configure"
            )
        raw.autocommit = True
        with raw.cursor() as cursor:
            if schema:
                _, sql = _load_driver()
                cursor.execute(
                    sql.SQL("SET search_path TO {}, pg_catalog").format(sql.Identifier(schema))
                )
            else:
                cursor.execute("SET search_path TO public, pg_catalog")
        raw.autocommit = False
        raw.set_session(readonly=read_only, autocommit=False)
    except PostgreSQLBackendError:
        raise
    except Exception as exc:
        raise _driver_exception(exc) from exc


def _release_schema(raw: Any) -> str:
    with raw.cursor() as cursor:
        cursor.execute("SELECT current_schema()")
        row = cursor.fetchone()
    return str(row[0] or "public") if row else "public"


def _validate_release(
    entry: _PoolEntry, raw: Any, *, schema: str,
    expected_fingerprint: str, expected_version: str,
) -> frozenset[str]:
    release_schema = schema or _release_schema(raw)
    cache_key = (release_schema, expected_fingerprint, expected_version)
    with _POOL_LOCK:
        if cache_key in entry.validated_releases:
            return entry.identity_tables.get(release_schema, frozenset())
    try:
        with raw.cursor() as cursor:
            cursor.execute(
                "SELECT version, source_schema_fingerprint FROM schema_migrations ORDER BY version"
            )
            migrations = {str(row[0]): str(row[1] or "") for row in cursor.fetchall()}
            cursor.execute(
                """
                SELECT table_name FROM information_schema.columns
                WHERE table_schema = current_schema() AND column_name = 'id'
                  AND is_identity = 'YES'
                """
            )
            identities = frozenset(str(row[0]).lower() for row in cursor.fetchall())
        baseline_fingerprint = migrations.get("0001_baseline", "")
        if expected_fingerprint and baseline_fingerprint != expected_fingerprint:
            raise PostgreSQLBackendError(
                "PostgreSQL baseline fingerprint does not match the active release"
            )
        required_versions = dict.fromkeys(
            version
            for version in (DEFAULT_REQUIRED_VERSION, expected_version)
            if version
        )
        for required_version in required_versions:
            if required_version not in migrations:
                raise PostgreSQLBackendError(
                    "Required PostgreSQL migration is not applied: "
                    f"{required_version}"
                )
        raw.rollback()
    except PostgreSQLBackendError:
        raise
    except Exception as exc:
        raise _driver_exception(exc) from exc
    with _POOL_LOCK:
        entry.validated_releases.add(cache_key)
        entry.identity_tables[release_schema] = identities
    return identities


class PostgresConnection:
    backend_name = "postgresql"

    def __init__(
        self, raw_connection: Any, entry: _PoolEntry, *, schema: str,
        identity_tables: frozenset[str], read_only: bool,
        checkout_permit: _CheckoutPermit | None = None,
    ) -> None:
        self._raw = raw_connection
        self._entry = entry
        self._checkout_permit = checkout_permit
        self.schema = schema
        self.identity_tables = identity_tables
        self.read_only = read_only
        self._closed = False
        self._close_lock = Lock()

    @property
    def closed(self) -> bool:
        return self._closed

    def cursor(self) -> PostgresCursor:
        if self._closed:
            raise PostgreSQLOperationalError("PostgreSQL connection is closed")
        return PostgresCursor(self)

    def execute(
        self,
        sql_text: str,
        parameters: Sequence[Any] | None = None,
        *,
        return_identity: bool | None = None,
    ) -> PostgresCursor:
        return self.cursor().execute(
            sql_text,
            parameters,
            return_identity=return_identity,
        )

    def executemany(
        self, sql_text: str, parameters: Sequence[Sequence[Any]]
    ) -> PostgresCursor:
        return self.cursor().executemany(sql_text, parameters)

    def execute_values(
        self,
        sql_text: str,
        parameters: Sequence[Sequence[Any]],
        *,
        template: str | None = None,
        page_size: int = 500,
    ) -> PostgresCursor:
        return self.cursor().execute_values(
            sql_text,
            parameters,
            template=template,
            page_size=page_size,
        )

    def commit(self) -> None:
        status = _transaction_status(self._raw)
        if status == _TX_IDLE:
            return
        if status == _TX_INERROR:
            try:
                self._raw.rollback()
            except Exception as exc:
                raise _driver_exception(exc) from exc
            raise PostgreSQLBackendError(
                "PostgreSQL transaction is aborted and was rolled back"
            )
        if status != _TX_INTRANS:
            raise PostgreSQLOperationalError(
                "PostgreSQL connection cannot commit in its current state"
            )
        try:
            self._raw.commit()
        except Exception as exc:
            raise _driver_exception(exc) from exc

    def rollback(self) -> None:
        status = _transaction_status(self._raw)
        if status == _TX_IDLE:
            return
        if status not in {_TX_INTRANS, _TX_INERROR}:
            raise PostgreSQLOperationalError(
                "PostgreSQL connection cannot roll back in its current state"
            )
        try:
            self._raw.rollback()
        except Exception as exc:
            raise _driver_exception(exc) from exc

    def database_identity(self) -> str:
        row = self.execute(
            "SELECT current_database() AS database_name, current_schema() AS schema_name"
        ).fetchone()
        if not row:
            return "postgresql"
        return f"postgresql://{row['database_name']}/{row['schema_name']}"

    def close(self) -> None:
        with self._close_lock:
            if self._closed:
                return
            self._closed = True
        broken = bool(getattr(self._raw, "closed", False))
        status = _transaction_status(self._raw)
        if status in {_TX_INTRANS, _TX_INERROR} and not broken:
            try:
                self._raw.rollback()
            except Exception:
                broken = True
            else:
                broken = _transaction_status(self._raw) != _TX_IDLE
        elif status != _TX_IDLE:
            broken = True
        try:
            self._entry.pool.putconn(self._raw, close=broken)
        except Exception:
            try:
                self._raw.close()
            except Exception:
                pass
        permit = self._checkout_permit
        self._checkout_permit = None
        if permit is not None:
            permit.release()

    def __enter__(self) -> "PostgresConnection":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> bool:
        try:
            if exc_type is None:
                self.commit()
            elif _transaction_status(self._raw) in {_TX_INTRANS, _TX_INERROR}:
                self.rollback()
        finally:
            # UNKNOWN, ACTIVE, and closed connections are discarded by close().
            # On an exceptional exit they must not replace the business error.
            self.close()
        return False


def connect_postgres(
    database_url: str,
    *,
    schema: str = "",
    expected_fingerprint: str = "",
    expected_version: str = DEFAULT_REQUIRED_VERSION,
    read_only: bool = False,
) -> PostgresConnection:
    if not str(database_url or "").lower().startswith(("postgres://", "postgresql://")):
        raise PostgreSQLBackendError("configured database URL must use PostgreSQL")
    entry = _pool_entry(database_url)
    permit = entry.checkout_gate.acquire(_pool_wait_timeout())
    if permit is None:
        raise PostgreSQLOperationalError(
            "timed out waiting for a PostgreSQL connection pool slot"
        )
    try:
        raw = entry.pool.getconn()
    except Exception as exc:
        permit.release()
        raise _driver_exception(exc) from exc
    session_setup_failed = False
    try:
        # Keep release validation writable, then reinstall the caller's final
        # mode. This intentionally preserves the established two-session
        # checkout path on both first validation and validation-cache hits.
        try:
            _set_session(raw, schema, read_only=False)
        except Exception:
            session_setup_failed = True
            raise
        identities = _validate_release(
            entry,
            raw,
            schema=schema,
            expected_fingerprint=expected_fingerprint,
            expected_version=expected_version,
        )
        try:
            _set_session(raw, schema, read_only=read_only)
        except Exception:
            session_setup_failed = True
            raise
        return PostgresConnection(
            raw,
            entry,
            schema=schema,
            identity_tables=identities,
            read_only=read_only,
            checkout_permit=permit,
        )
    except Exception:
        # A connection whose session setup failed may still be IDLE but can have
        # an unsafe autocommit/search_path state.  Do not return it to the pool.
        broken = bool(getattr(raw, "closed", False)) or session_setup_failed
        try:
            status = _transaction_status(raw)
            if not broken and status in {_TX_INTRANS, _TX_INERROR}:
                raw.rollback()
            elif status != _TX_IDLE:
                broken = True
        except Exception:
            broken = True
        try:
            entry.pool.putconn(raw, close=broken)
        except Exception:
            try:
                raw.close()
            except Exception:
                pass
        permit.release()
        raise
