from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import os
from threading import Barrier, Event, Lock
import time
from unittest.mock import patch

import pytest

from darkweb_collector import postgres_backend
from darkweb_collector.postgres_backend import (
    PostgreSQLOperationalError,
    _CheckoutGate,
    _PoolEntry,
    connect_postgres,
)


class RawConnection:
    def __init__(self, identifier: int) -> None:
        self.identifier = identifier
        self.closed = False
        self.autocommit = False

    def get_transaction_status(self) -> int:
        return (
            postgres_backend._TX_UNKNOWN
            if self.closed
            else postgres_backend._TX_IDLE
        )

    def close(self) -> None:
        self.closed = True


class ConcurrentPool:
    maxconn = 4

    def __init__(self) -> None:
        self._lock = Lock()
        self._available = [
            RawConnection(index)
            for index in range(self.maxconn)
        ]
        self.active = 0
        self.peak_active = 0
        self.returned = 0
        self.get_calls = 0
        self.closed = False
        self.saturated = Event()

    def getconn(self) -> RawConnection:
        with self._lock:
            self.get_calls += 1
            if not self._available:
                raise AssertionError(
                    "underlying pool was called without a checkout permit"
                )
            raw = self._available.pop()
            self.active += 1
            self.peak_active = max(self.peak_active, self.active)
            if self.active == self.maxconn:
                self.saturated.set()
            return raw

    def putconn(self, connection: RawConnection, close: bool = False) -> None:
        with self._lock:
            self.active -= 1
            self.returned += 1
            if close:
                connection.close()
                connection = RawConnection(connection.identifier)
            self._available.append(connection)

    def closeall(self) -> None:
        self.closed = True


def _connect_with_entry(entry: _PoolEntry):
    return (
        patch.object(postgres_backend, "_pool_entry", return_value=entry),
        patch.object(postgres_backend, "_pool_wait_timeout", return_value=2),
        patch.object(postgres_backend, "_set_session"),
        patch.object(
            postgres_backend,
            "_validate_release",
            return_value=frozenset(),
        ),
    )


def test_eight_threads_wait_behind_four_slots_and_all_succeed() -> None:
    pool = ConcurrentPool()
    gate = _CheckoutGate(4)
    entry = _PoolEntry(pool, checkout_gate=gate)
    start = Barrier(8)
    release_first_wave = Event()

    def worker(index: int) -> int:
        start.wait(timeout=5)
        connection = connect_postgres(
            "postgresql://runtime@localhost/darkweb",
            schema="dwti_fixture",
        )
        if index < 8:
            release_first_wave.wait(timeout=5)
        try:
            return connection._raw.identifier
        finally:
            connection.close()

    patches = _connect_with_entry(entry)
    with patches[0], patches[1], patches[2], patches[3]:
        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = [
                executor.submit(worker, index)
                for index in range(8)
            ]
            assert pool.saturated.wait(timeout=2)
            time.sleep(0.05)
            assert sum(future.done() for future in futures) == 0
            assert pool.active == 4
            assert pool.get_calls == 4
            release_first_wave.set()
            results = [future.result(timeout=5) for future in futures]

    assert len(results) == 8
    assert pool.peak_active == 4
    assert pool.get_calls == 8
    assert pool.returned == 8
    assert pool.active == 0
    assert gate.available == 4


def test_checkout_timeout_is_operational_and_does_not_call_pool() -> None:
    pool = ConcurrentPool()
    gate = _CheckoutGate(1)
    entry = _PoolEntry(pool, checkout_gate=gate)
    held = gate.acquire(0.1)
    assert held is not None

    with patch.object(
        postgres_backend,
        "_pool_entry",
        return_value=entry,
    ), patch.object(
        postgres_backend,
        "_pool_wait_timeout",
        return_value=0.05,
    ):
        started = time.perf_counter()
        with pytest.raises(
            PostgreSQLOperationalError,
            match="timed out waiting",
        ):
            connect_postgres(
                "postgresql://runtime@localhost/darkweb"
            )
        elapsed = time.perf_counter() - started

    assert elapsed >= 0.04
    assert pool.get_calls == 0
    assert gate.available == 0
    held.release()
    assert gate.available == 1


def test_getconn_failure_releases_slot_exactly_once() -> None:
    class PoolError(Exception):
        pass

    class FailingPool(ConcurrentPool):
        maxconn = 1

        def getconn(self):
            self.get_calls += 1
            raise PoolError("driver pool failed")

    pool = FailingPool()
    gate = _CheckoutGate(1)
    entry = _PoolEntry(pool, checkout_gate=gate)
    with patch.object(
        postgres_backend,
        "_pool_entry",
        return_value=entry,
    ), patch.object(
        postgres_backend,
        "_pool_wait_timeout",
        return_value=1,
    ):
        with pytest.raises(PostgreSQLOperationalError):
            connect_postgres(
                "postgresql://runtime@localhost/darkweb"
            )

    assert pool.get_calls == 1
    assert gate.available == 1


def test_session_failure_and_putconn_failure_release_slot() -> None:
    pool = ConcurrentPool()
    pool.maxconn = 1
    pool._available = [RawConnection(1)]
    gate = _CheckoutGate(1)
    entry = _PoolEntry(pool, checkout_gate=gate)

    with patch.object(
        postgres_backend,
        "_pool_entry",
        return_value=entry,
    ), patch.object(
        postgres_backend,
        "_pool_wait_timeout",
        return_value=1,
    ), patch.object(
        postgres_backend,
        "_set_session",
        side_effect=PostgreSQLOperationalError("setup failed"),
    ):
        with pytest.raises(PostgreSQLOperationalError):
            connect_postgres(
                "postgresql://runtime@localhost/darkweb"
            )
    assert gate.available == 1

    class BrokenReturnPool(ConcurrentPool):
        maxconn = 1

        def __init__(self) -> None:
            super().__init__()
            self._available = [RawConnection(2)]

        def putconn(self, connection, close=False) -> None:
            raise RuntimeError("putconn failed")

    broken_pool = BrokenReturnPool()
    broken_gate = _CheckoutGate(1)
    broken_entry = _PoolEntry(
        broken_pool,
        checkout_gate=broken_gate,
    )
    patches = _connect_with_entry(broken_entry)
    with patches[0], patches[1], patches[2], patches[3]:
        connection = connect_postgres(
            "postgresql://runtime@localhost/darkweb"
        )
        raw = connection._raw
        connection.close()
        connection.close()

    assert raw.closed is True
    assert broken_gate.available == 1


def test_gate_close_wakes_waiters_and_pool_timeout_config_is_validated() -> None:
    gate = _CheckoutGate(1)
    held = gate.acquire(0.1)
    assert held is not None

    def wait_for_slot() -> str:
        with pytest.raises(
            PostgreSQLOperationalError,
            match="pool is closed",
        ):
            gate.acquire(5)
        return "woken"

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(wait_for_slot)
        time.sleep(0.05)
        gate.close()
        assert future.result(timeout=1) == "woken"
    held.release()
    assert gate.available == 1

    with patch.dict(
        os.environ,
        {"DARKWEB_POSTGRES_POOL_WAIT_TIMEOUT_SECONDS": "30"},
        clear=False,
    ):
        assert postgres_backend._pool_wait_timeout() == 30
    for invalid in ("0", "301", "invalid"):
        with patch.dict(
            os.environ,
            {"DARKWEB_POSTGRES_POOL_WAIT_TIMEOUT_SECONDS": invalid},
            clear=False,
        ):
            with pytest.raises(postgres_backend.PostgreSQLBackendError):
                postgres_backend._pool_wait_timeout()


def test_close_all_closes_gate_and_driver_pool() -> None:
    pool = ConcurrentPool()
    gate = _CheckoutGate(4)
    entry = _PoolEntry(pool, checkout_gate=gate)
    old_pools = postgres_backend._POOLS
    try:
        postgres_backend._POOLS = {
            ("dsn", 1, 4, 5): entry
        }
        postgres_backend.close_postgres_pools()
        assert pool.closed is True
        with pytest.raises(
            PostgreSQLOperationalError,
            match="pool is closed",
        ):
            gate.acquire(0.1)
    finally:
        postgres_backend._POOLS = old_pools
