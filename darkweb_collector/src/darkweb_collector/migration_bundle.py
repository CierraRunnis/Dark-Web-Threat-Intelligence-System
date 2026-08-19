from __future__ import annotations

import base64
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sqlite3
from typing import Any, Callable, Iterator, Sequence
from urllib.parse import quote
import uuid
import zipfile

from darkweb_collector.runtime import active_release_path, user_data_root


BUNDLE_FORMAT = "dwti-migration-bundle"
BUNDLE_VERSION = 1
SCHEMA_VERSION = "0002_sqlite_compat"
MAX_MANIFEST_BYTES = 8 * 1024 * 1024
MAX_CHECKSUM_BYTES = 64 * 1024 * 1024
DEFAULT_MAX_BUNDLE_BYTES = 20 * 1024 * 1024 * 1024
DEFAULT_MAX_UNCOMPRESSED_BYTES = 100 * 1024 * 1024 * 1024
DEFAULT_MAX_ENTRIES = 250_000
DEFAULT_MAX_ROW_BYTES = 64 * 1024 * 1024
SENSITIVE_COLUMN_MARKERS = ("password", "secret", "token", "cookie", "credential")
SENSITIVE_ARTIFACT_PARTS = {
    "platform_sessions",
    "browser_sessions",
    "credentials",
    "cookies",
    "secrets",
}
PORTABLE_ARTIFACT_PATH_PREFIX = "dwti-artifact://"
PORTABLE_ARTIFACT_PATH_COLUMNS = {
    "document_hit_snapshots": {"html_path", "screenshot_path"},
    "code_hit_snapshots": {"html_path", "screenshot_path", "raw_artifact_path"},
}
PORTABLE_CASE_COLLISION_ROOTS = {"code_monitoring", "document_exposure"}
ProgressCallback = Callable[[str, int, str], None]


class MigrationBundleError(RuntimeError):
    pass


def _progress(callback: ProgressCallback | None, phase: str, percent: int, message: str) -> None:
    if callback:
        callback(phase, max(0, min(100, int(percent))), message)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def migration_root() -> Path:
    override = os.environ.get("DARKWEB_MIGRATION_ROOT", "").strip()
    root = Path(override).expanduser().resolve() if override else user_data_root() / "migrations"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sqlite_identifier(name: str) -> str:
    return '"' + str(name).replace('"', '""') + '"'


def _safe_identifier(name: str) -> str:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,62}", str(name)):
        raise MigrationBundleError(f"不支持的数据库标识符：{name!r}")
    return str(name)


def _sqlite_readonly_uri(resolved: Path) -> str:
    rendered = str(resolved)
    if os.name == "nt" and rendered.startswith("\\\\"):
        uri_path = rendered.replace("\\", "/").lstrip("/")
        return f"file:////{quote(uri_path, safe='/:')}?mode=ro"
    return f"file:{quote(resolved.as_posix(), safe='/:')}?mode=ro"


def _open_sqlite_readonly(path: Path) -> sqlite3.Connection:
    resolved = path.expanduser().resolve(strict=True)
    database_uri = _sqlite_readonly_uri(resolved)
    connection = sqlite3.connect(database_uri, uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    if connection.execute("PRAGMA query_only").fetchone()[0] != 1:
        connection.close()
        raise MigrationBundleError("无法将 SQLite 源库设置为只读")
    return connection


def _is_windows_unc_path(path: Path) -> bool:
    return os.name == "nt" and str(path).startswith("\\\\")


def _sqlite_file_signatures(path: Path) -> dict[str, tuple[int, int]]:
    signatures: dict[str, tuple[int, int]] = {}
    for suffix in ("", "-wal", "-shm", "-journal"):
        candidate = Path(str(path) + suffix)
        try:
            stat = candidate.stat()
        except FileNotFoundError:
            continue
        signatures[suffix] = (int(stat.st_size), int(stat.st_mtime_ns))
    return signatures


def _stage_unc_sqlite(source_path: Path, snapshot_path: Path) -> Path:
    staged_path = snapshot_path.with_name("source-staged.db")
    try:
        before = _sqlite_file_signatures(source_path)
        if "" not in before:
            raise MigrationBundleError("WSL SQLite 数据库不存在")
        for suffix in before:
            shutil.copy2(Path(str(source_path) + suffix), Path(str(staged_path) + suffix))
        after = _sqlite_file_signatures(source_path)
        if before != after:
            raise MigrationBundleError("复制期间 WSL SQLite 数据库仍在变化，请停止服务后重试")
        return staged_path
    except Exception:
        _remove_staged_sqlite(staged_path)
        raise


def _remove_staged_sqlite(path: Path) -> None:
    for suffix in ("", "-wal", "-shm", "-journal"):
        Path(str(path) + suffix).unlink(missing_ok=True)


def _snapshot_sqlite(source_path: Path, snapshot_path: Path) -> None:
    resolved_source = source_path.expanduser().resolve(strict=True)
    staged_source = _stage_unc_sqlite(resolved_source, snapshot_path) if _is_windows_unc_path(resolved_source) else None
    source = None
    try:
        source = _open_sqlite_readonly(staged_source or resolved_source)
        destination = sqlite3.connect(snapshot_path)
        try:
            source.backup(destination, pages=4096, sleep=0.05)
            result = destination.execute("PRAGMA quick_check").fetchone()[0]
            if result != "ok":
                raise MigrationBundleError(f"SQLite 快照完整性检查失败：{result}")
        finally:
            destination.close()
    finally:
        if source is not None:
            source.close()
        if staged_source is not None:
            _remove_staged_sqlite(staged_source)


def _upgrade_snapshot_schema(snapshot_path: Path) -> None:
    from darkweb_collector.db import _ensure_schema

    connection = sqlite3.connect(snapshot_path)
    try:
        _ensure_schema(connection)
        connection.commit()
        result = str(connection.execute("PRAGMA quick_check").fetchone()[0])
        if result.lower() != "ok":
            raise MigrationBundleError(f"升级后的 SQLite 快照校验失败：{result}")
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def _pragma(connection: sqlite3.Connection, pragma: str, name: str) -> list[sqlite3.Row]:
    return list(connection.execute(f"PRAGMA {pragma}({_sqlite_identifier(name)})"))


def _supported_checks(table_sql: str, table_name: str, columns: set[str]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    for start in re.finditer(r"\bCHECK\s*\(", table_sql, flags=re.IGNORECASE):
        position = start.end()
        depth = 1
        quote = ""
        while position < len(table_sql) and depth:
            character = table_sql[position]
            if quote:
                if character == quote:
                    if position + 1 < len(table_sql) and table_sql[position + 1] == quote:
                        position += 1
                    else:
                        quote = ""
            elif character in {'"', "'"}:
                quote = character
            elif character == "(":
                depth += 1
            elif character == ")":
                depth -= 1
            position += 1
        if depth:
            raise MigrationBundleError(f"无法解析 CHECK 约束：{table_name}")
        expression = table_sql[start.end() : position - 1].strip()
        match = re.fullmatch(
            r'(?P<column>"(?:""|[^"])+"|[A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?P<value>[-+]?\d+)',
            expression,
        )
        if not match:
            raise MigrationBundleError(f"CHECK 约束需要显式映射：{table_name}: {expression}")
        raw_column = match.group("column")
        column = raw_column[1:-1].replace('""', '"') if raw_column.startswith('"') else raw_column
        if column not in columns:
            raise MigrationBundleError(f"CHECK 约束引用未知字段：{table_name}.{column}")
        checks.append({"column": column, "operator": "=", "value": int(match.group("value"))})
    return checks


def sqlite_schema_spec(connection: sqlite3.Connection) -> dict[str, Any]:
    unsupported = list(
        connection.execute(
            "SELECT type, name FROM sqlite_master "
            "WHERE type IN ('view', 'trigger') AND name NOT LIKE 'sqlite_%' ORDER BY type, name"
        )
    )
    if unsupported:
        rendered = ", ".join(f"{row[0]}:{row[1]}" for row in unsupported)
        raise MigrationBundleError(f"视图或触发器需要专用迁移：{rendered}")

    tables: list[dict[str, Any]] = []
    table_names = [
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
    ]
    for table_name in table_names:
        _safe_identifier(table_name)
        master = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table_name,)
        ).fetchone()
        table_sql = str(master[0] or "")
        columns = []
        for row in _pragma(connection, "table_xinfo", table_name):
            hidden = int(row[6]) if len(row) > 6 else 0
            if hidden:
                raise MigrationBundleError(f"不支持生成列或隐藏列：{table_name}.{row[1]}")
            _safe_identifier(str(row[1]))
            columns.append(
                {
                    "name": str(row[1]),
                    "type": str(row[2] or ""),
                    "notnull": bool(row[3]),
                    "default": row[4],
                    "pk_order": int(row[5]),
                }
            )

        foreign_keys: dict[int, dict[str, Any]] = {}
        for row in _pragma(connection, "foreign_key_list", table_name):
            group = foreign_keys.setdefault(
                int(row[0]),
                {
                    "table": str(row[2]),
                    "from": [],
                    "to": [],
                    "on_update": str(row[5]),
                    "on_delete": str(row[6]),
                    "match": str(row[7]),
                },
            )
            group["from"].append(str(row[3]))
            group["to"].append(str(row[4]))

        indexes = []
        for row in _pragma(connection, "index_list", table_name):
            index_name = str(row[1])
            unique = bool(row[2])
            origin = str(row[3]) if len(row) > 3 else "c"
            partial = bool(row[4]) if len(row) > 4 else False
            if origin == "pk":
                continue
            index_columns = []
            for index_row in _pragma(connection, "index_xinfo", index_name):
                if len(index_row) > 5 and not bool(index_row[5]):
                    continue
                if int(index_row[1]) < 0 or index_row[2] is None:
                    raise MigrationBundleError(f"不支持表达式索引：{table_name}.{index_name}")
                if (len(index_row) > 3 and bool(index_row[3])) or str(index_row[4] or "BINARY").upper() != "BINARY":
                    raise MigrationBundleError(f"不支持降序或自定义排序索引：{table_name}.{index_name}")
                index_columns.append(str(index_row[2]))
            sql_row = connection.execute(
                "SELECT sql FROM sqlite_master WHERE type='index' AND name=?", (index_name,)
            ).fetchone()
            index_sql = str(sql_row[0] or "") if sql_row else ""
            where = ""
            if partial:
                match = re.search(r"\bWHERE\b(.+)$", index_sql, flags=re.IGNORECASE | re.DOTALL)
                if not match:
                    raise MigrationBundleError(f"无法解析部分索引：{index_name}")
                where = match.group(1).strip()
            indexes.append(
                {
                    "name": index_name,
                    "columns": index_columns,
                    "unique": unique,
                    "origin": origin,
                    "where": where,
                }
            )

        tables.append(
            {
                "name": table_name,
                "columns": columns,
                "checks": _supported_checks(table_sql, table_name, {c["name"] for c in columns}),
                "foreign_keys": list(foreign_keys.values()),
                "indexes": indexes,
            }
        )
    return {"tables": tables}


def schema_fingerprint(spec: dict[str, Any]) -> str:
    encoded = json.dumps(spec, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _canonical_value(value: Any) -> bytes:
    if value is None:
        return b"N"
    if isinstance(value, bool):
        return b"I1" if value else b"I0"
    if isinstance(value, int):
        return b"I" + str(value).encode("ascii")
    if isinstance(value, Decimal):
        if value == value.to_integral_value():
            return b"I" + str(int(value)).encode("ascii")
        value = float(value)
    if isinstance(value, float):
        if math.isnan(value):
            return b"Fnan"
        if math.isinf(value):
            return b"Finf" if value > 0 else b"F-inf"
        return b"F" + value.hex().encode("ascii")
    if isinstance(value, memoryview):
        value = value.tobytes()
    if isinstance(value, bytes):
        return b"B" + str(len(value)).encode("ascii") + b":" + value
    if isinstance(value, str):
        encoded = value.encode("utf-8")
        return b"S" + str(len(encoded)).encode("ascii") + b":" + encoded
    raise MigrationBundleError(f"不支持的数据类型：{type(value).__name__}")


def _empty_stats(columns: Sequence[str]) -> dict[str, Any]:
    return {"rows": 0, "xor256": 0, "sum256": 0, "null_counts": {name: 0 for name in columns}}


def _update_stats(stats: dict[str, Any], columns: Sequence[str], values: Sequence[Any]) -> None:
    framed = bytearray()
    for name, value in zip(columns, values):
        encoded = _canonical_value(value)
        framed.extend(len(encoded).to_bytes(8, "big"))
        framed.extend(encoded)
        if value is None:
            stats["null_counts"][name] += 1
    row_hash = int.from_bytes(hashlib.sha256(framed).digest(), "big")
    stats["rows"] += 1
    stats["xor256"] ^= row_hash
    stats["sum256"] = (stats["sum256"] + row_hash) % (1 << 256)


def _finalize_stats(stats: dict[str, Any]) -> dict[str, Any]:
    return {
        "rows": stats["rows"],
        "xor256": f"{stats['xor256']:064x}",
        "sum256": f"{stats['sum256']:064x}",
        "null_counts": stats["null_counts"],
    }


def _encode_json_value(value: Any) -> Any:
    if isinstance(value, memoryview):
        value = value.tobytes()
    if isinstance(value, bytes):
        return {"$binary": base64.b64encode(value).decode("ascii")}
    return value


def _decode_json_value(value: Any) -> Any:
    if isinstance(value, dict) and set(value) == {"$binary"}:
        try:
            return base64.b64decode(str(value["$binary"]), validate=True)
        except ValueError as exc:
            raise MigrationBundleError("迁移包包含无效二进制字段") from exc
    return value


def _sanitized_row(table: str, columns: Sequence[str], values: Sequence[Any]) -> tuple[list[Any], list[str]]:
    result = list(values)
    sanitized: list[str] = []
    for index, column in enumerate(columns):
        lowered = column.lower()
        if any(marker in lowered for marker in SENSITIVE_COLUMN_MARKERS):
            result[index] = ""
            sanitized.append(f"{table}.{column}")
    if table == "platform_sessions":
        for field, replacement in (("storage_state_path", ""), ("metadata_json", "{}"), ("last_error", "")):
            if field in columns:
                result[columns.index(field)] = replacement
                sanitized.append(f"{table}.{field}")
    return result, sanitized


def _zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o100600 << 16
    return info


def _write_zip_bytes(archive: zipfile.ZipFile, name: str, payload: bytes) -> str:
    archive.writestr(_zip_info(name), payload)
    return hashlib.sha256(payload).hexdigest()


def _is_reparse_point(path: Path) -> bool:
    try:
        return bool(getattr(path.stat(follow_symlinks=False), "st_file_attributes", 0) & 0x400)
    except OSError:
        return True


def _artifact_allowed(relative: Path) -> bool:
    lowered = {part.lower() for part in relative.parts}
    return not lowered.intersection(SENSITIVE_ARTIFACT_PARTS)


def _artifact_relative_name(relative: Path) -> str:
    name = relative.as_posix()
    path = PurePosixPath(name)
    if not path.parts or path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise MigrationBundleError(f"镜像目录包含非法相对路径：{name}")
    if "\\" in name or "\x00" in name:
        raise MigrationBundleError(f"镜像目录包含非法文件名：{name}")
    return path.as_posix()


def _collision_safe_artifact_names(relatives: Sequence[Path]) -> tuple[dict[str, str], dict[str, str]]:
    originals = [_artifact_relative_name(relative) for relative in relatives]
    groups: dict[str, list[str]] = defaultdict(list)
    for name in originals:
        groups[name.casefold()].append(name)
    assigned = {names[0]: names[0] for names in groups.values() if len(names) == 1}
    used = {name.casefold() for name in assigned.values()}
    renamed: dict[str, str] = {}
    for names in groups.values():
        if len(names) == 1:
            continue
        roots = {PurePosixPath(name).parts[0].casefold() for name in names}
        if not roots or not roots.issubset(PORTABLE_CASE_COLLISION_ROOTS):
            raise MigrationBundleError(f"镜像目录包含无法安全迁移的大小写冲突路径：{names[0]}")
        for name in sorted(names):
            path = PurePosixPath(name)
            suffix = path.suffix
            stem = path.name[: -len(suffix)] if suffix else path.name
            digest = hashlib.sha256(name.encode("utf-8")).hexdigest()
            for length in (10, 16, 24, 64):
                candidate = str(path.with_name(f"{stem}~{digest[:length]}{suffix}"))
                if candidate.casefold() not in used:
                    break
            else:  # pragma: no cover - SHA-256 suffixes make this unreachable
                raise MigrationBundleError(f"无法为大小写冲突镜像生成唯一文件名：{name}")
            assigned[name] = candidate
            renamed[name] = candidate
            used.add(candidate.casefold())
    return assigned, renamed


class _ArtifactPathIndex:
    def __init__(self, archive_names: dict[str, str]) -> None:
        self._exact = dict(archive_names)
        groups: dict[str, list[str]] = defaultdict(list)
        for original in self._exact:
            groups[original.casefold()].append(original)
        self._folded = {
            lowered: self._exact[names[0]]
            for lowered, names in groups.items()
            if len(names) == 1
        }

    def encode(self, table: str, column: str, value: Any) -> str:
        raw = str(value or "").strip()
        if not raw:
            return ""
        normalized = raw.replace("\\", "/")
        if normalized.startswith(PORTABLE_ARTIFACT_PATH_PREFIX):
            normalized = normalized[len(PORTABLE_ARTIFACT_PATH_PREFIX) :]
        parts = [part for part in normalized.split("/") if part not in {"", "."}]
        if not parts or ".." in parts:
            raise MigrationBundleError(f"镜像路径非法：{table}.{column}: {raw}")
        for offset in range(len(parts)):
            candidate = "/".join(parts[offset:])
            archive_name = self._exact.get(candidate)
            if archive_name:
                return PORTABLE_ARTIFACT_PATH_PREFIX + archive_name
        for offset in range(len(parts)):
            candidate = "/".join(parts[offset:])
            archive_name = self._folded.get(candidate.casefold())
            if archive_name:
                return PORTABLE_ARTIFACT_PATH_PREFIX + archive_name
        raise MigrationBundleError(f"数据库镜像路径在所选镜像目录中没有对应文件：{table}.{column}: {raw}")


def _portable_artifact_row(
    table: str,
    columns: Sequence[str],
    values: Sequence[Any],
    artifact_paths: _ArtifactPathIndex,
) -> tuple[list[Any], list[str]]:
    result = list(values)
    rewritten: list[str] = []
    for column in PORTABLE_ARTIFACT_PATH_COLUMNS.get(table, set()):
        if column not in columns:
            continue
        index = columns.index(column)
        if result[index] in (None, ""):
            continue
        result[index] = artifact_paths.encode(table, column, result[index])
        rewritten.append(f"{table}.{column}")
    return result, rewritten


def _native_path(path: Path) -> str:
    rendered = str(path.resolve())
    if os.name != "nt" or rendered.startswith("\\\\?\\"):
        return rendered
    if rendered.startswith("\\\\"):
        return "\\\\?\\UNC\\" + rendered[2:]
    return "\\\\?\\" + rendered


def export_bundle(
    database_path: Path,
    artifacts_root: Path,
    output_path: Path,
    *,
    progress: ProgressCallback | None = None,
    upgrade_schema: bool = True,
) -> dict[str, Any]:
    database_path = database_path.expanduser().resolve(strict=True)
    artifacts_root = artifacts_root.expanduser().resolve(strict=True)
    output_path = output_path.expanduser().resolve()
    if output_path.exists():
        raise MigrationBundleError(f"输出文件已存在：{output_path}")
    if not artifacts_root.is_dir():
        raise MigrationBundleError("镜像目录不存在")
    resolved_artifacts_root = artifacts_root.resolve()
    if output_path == resolved_artifacts_root or resolved_artifacts_root in output_path.parents:
        raise MigrationBundleError("迁移包不能写入待打包的镜像目录")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    bundle_id = str(uuid.uuid4())
    checksums: dict[str, tuple[str, int]] = {}
    skipped_artifacts: list[str] = []
    sanitized_fields: set[str] = set()
    portable_path_fields: dict[str, int] = defaultdict(int)
    artifact_count = 0
    artifact_bytes = 0
    artifact_files = sorted(path for path in artifacts_root.rglob("*") if path.is_file())
    included_artifacts: list[tuple[Path, Path]] = []
    for source in artifact_files:
        relative = source.relative_to(artifacts_root)
        resolved_source = source.resolve()
        if (
            source.is_symlink()
            or _is_reparse_point(source)
            or resolved_artifacts_root not in resolved_source.parents
            or not _artifact_allowed(relative)
        ):
            skipped_artifacts.append(relative.as_posix())
            continue
        included_artifacts.append((source, relative))
    artifact_archive_names, case_collision_renames = _collision_safe_artifact_names(
        [relative for _source, relative in included_artifacts]
    )
    artifact_paths = _ArtifactPathIndex(artifact_archive_names)

    temp_dir = output_path.parent / f".dwti-export-{uuid.uuid4().hex}"
    temp_dir.mkdir()
    try:
        snapshot_path = temp_dir / "collector.snapshot.db"
        _progress(progress, "snapshot", 5, "正在创建 SQLite 只读快照")
        _snapshot_sqlite(database_path, snapshot_path)
        if upgrade_schema:
            _progress(progress, "snapshot", 8, "正在升级迁移快照的数据库结构")
            _upgrade_snapshot_schema(snapshot_path)
        connection = _open_sqlite_readonly(snapshot_path)
        try:
            quick_check = str(connection.execute("PRAGMA quick_check").fetchone()[0])
            spec = sqlite_schema_spec(connection)
            fingerprint = schema_fingerprint(spec)
            tables: dict[str, Any] = {}
            with zipfile.ZipFile(output_path, "w", allowZip64=True) as archive:
                for table_index, table in enumerate(spec["tables"]):
                    table_name = table["name"]
                    columns = [column["name"] for column in table["columns"]]
                    data_path = f"data/{table_name}.jsonl"
                    digest = hashlib.sha256()
                    stats = _empty_stats(columns)
                    with archive.open(_zip_info(data_path), "w", force_zip64=True) as target:
                        query = "SELECT " + ", ".join(_sqlite_identifier(name) for name in columns)
                        query += " FROM " + _sqlite_identifier(table_name)
                        cursor = connection.execute(query)
                        while True:
                            rows = cursor.fetchmany(1000)
                            if not rows:
                                break
                            for row in rows:
                                values, sanitized = _sanitized_row(table_name, columns, tuple(row))
                                sanitized_fields.update(sanitized)
                                values, rewritten_paths = _portable_artifact_row(
                                    table_name,
                                    columns,
                                    values,
                                    artifact_paths,
                                )
                                for field in rewritten_paths:
                                    portable_path_fields[field] += 1
                                _update_stats(stats, columns, values)
                                encoded = (
                                    json.dumps(
                                        [_encode_json_value(value) for value in values],
                                        ensure_ascii=False,
                                        separators=(",", ":"),
                                    )
                                    + "\n"
                                ).encode("utf-8")
                                target.write(encoded)
                                digest.update(encoded)
                    size = archive.getinfo(data_path).file_size
                    checksums[data_path] = (digest.hexdigest(), size)
                    tables[table_name] = {
                        "path": data_path,
                        "columns": columns,
                        "stats": _finalize_stats(stats),
                    }
                    _progress(
                        progress,
                        "database",
                        10 + int(35 * (table_index + 1) / max(1, len(spec["tables"]))),
                        f"已导出数据库表 {table_index + 1}/{len(spec['tables'])}",
                    )

                for file_index, (source, relative) in enumerate(included_artifacts):
                    original_name = _artifact_relative_name(relative)
                    archive_name = "artifacts/" + artifact_archive_names[original_name]
                    digest = hashlib.sha256()
                    size = 0
                    with source.open("rb") as handle, archive.open(
                        _zip_info(archive_name), "w", force_zip64=True
                    ) as target:
                        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                            target.write(chunk)
                            digest.update(chunk)
                            size += len(chunk)
                    checksums[archive_name] = (digest.hexdigest(), size)
                    artifact_count += 1
                    artifact_bytes += size
                    if file_index % 100 == 0 or file_index + 1 == len(included_artifacts):
                        _progress(
                            progress,
                            "artifacts",
                            45 + int(40 * (file_index + 1) / max(1, len(included_artifacts))),
                            f"已打包镜像文件 {file_index + 1}/{len(included_artifacts)}",
                        )

                checksum_payload = "".join(
                    f"{digest}  {name}\n" for name, (digest, _size) in sorted(checksums.items())
                ).encode("utf-8")
                _write_zip_bytes(archive, "checksums.sha256", checksum_payload)
                manifest = {
                    "format": BUNDLE_FORMAT,
                    "format_version": BUNDLE_VERSION,
                    "bundle_id": bundle_id,
                    "created_at": _utc_now(),
                    "source": {
                        "database_engine": "sqlite",
                        "quick_check": quick_check,
                        "schema_fingerprint": fingerprint,
                        "snapshot_bytes": snapshot_path.stat().st_size,
                        "snapshot_sha256": _sha256_file(snapshot_path),
                        "schema_upgraded": upgrade_schema,
                    },
                    "schema": spec,
                    "tables": tables,
                    "artifacts": {
                        "count": artifact_count,
                        "bytes": artifact_bytes,
                        "root": "artifacts/",
                        "skipped_sensitive_count": len(skipped_artifacts),
                        "portable_path_fields": dict(sorted(portable_path_fields.items())),
                        "case_collision_renames": dict(sorted(case_collision_renames.items())),
                    },
                    "sanitized_fields": sorted(sanitized_fields),
                }
                _write_zip_bytes(
                    archive,
                    "manifest.json",
                    (json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8"),
                )
        except Exception:
            output_path.unlink(missing_ok=True)
            raise
        finally:
            connection.close()
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

    _progress(progress, "complete", 100, "迁移包创建完成")
    return {
        "bundle": str(output_path),
        "bundle_id": bundle_id,
        "bundle_bytes": output_path.stat().st_size,
        "tables": len(tables),
        "rows": sum(int(item["stats"]["rows"]) for item in tables.values()),
        "artifacts": artifact_count,
        "artifact_bytes": artifact_bytes,
        "schema_fingerprint": fingerprint,
        "sanitized_fields": sorted(sanitized_fields),
        "skipped_sensitive_artifacts": len(skipped_artifacts),
        "portable_artifact_paths": dict(sorted(portable_path_fields.items())),
        "case_collision_renames": len(case_collision_renames),
    }


def _validate_member_name(name: str) -> str:
    if "\\" in name or "\x00" in name:
        raise MigrationBundleError("迁移包包含非法文件名")
    path = PurePosixPath(name)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise MigrationBundleError(f"迁移包包含越界路径：{name}")
    if re.match(r"^[A-Za-z]:", name):
        raise MigrationBundleError(f"迁移包包含 Windows 绝对路径：{name}")
    return path.as_posix()


def _portable_artifact_archive_name(value: Any, table: str, column: str) -> str:
    raw = str(value or "")
    if not raw.startswith(PORTABLE_ARTIFACT_PATH_PREFIX):
        raise MigrationBundleError(f"迁移包包含未归一化的镜像路径：{table}.{column}")
    relative = raw[len(PORTABLE_ARTIFACT_PATH_PREFIX) :]
    return _validate_member_name("artifacts/" + relative)


def _validate_portable_artifact_references(
    archive: zipfile.ZipFile,
    manifest: dict[str, Any],
    artifact_names: set[str],
) -> dict[str, int] | None:
    artifact_manifest = manifest.get("artifacts")
    if not isinstance(artifact_manifest, dict) or "portable_path_fields" not in artifact_manifest:
        return None
    raw_declared = artifact_manifest.get("portable_path_fields")
    if not isinstance(raw_declared, dict):
        raise MigrationBundleError("迁移包可移植镜像路径清单格式错误")
    allowed_fields = {
        f"{table}.{column}"
        for table, columns in PORTABLE_ARTIFACT_PATH_COLUMNS.items()
        for column in columns
    }
    declared: dict[str, int] = {}
    for key, value in raw_declared.items():
        if key not in allowed_fields or not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise MigrationBundleError(f"迁移包可移植镜像路径清单无效：{key}")
        if value:
            declared[str(key)] = int(value)

    observed: dict[str, int] = defaultdict(int)
    max_row_bytes = int(os.environ.get("DARKWEB_MIGRATION_MAX_ROW_BYTES", DEFAULT_MAX_ROW_BYTES))
    for table, path_columns in PORTABLE_ARTIFACT_PATH_COLUMNS.items():
        table_manifest = manifest.get("tables", {}).get(table)
        if not isinstance(table_manifest, dict):
            continue
        columns = list(table_manifest.get("columns") or [])
        indexes = [(column, columns.index(column)) for column in path_columns if column in columns]
        if not indexes:
            continue
        with archive.open(str(table_manifest.get("path") or "")) as raw:
            line_number = 0
            while True:
                encoded_line = raw.readline(max_row_bytes + 1)
                if not encoded_line:
                    break
                line_number += 1
                if len(encoded_line) > max_row_bytes:
                    raise MigrationBundleError(f"表 {table} 第 {line_number} 行超过大小限制")
                try:
                    values = json.loads(encoded_line.decode("utf-8"))
                except (ValueError, UnicodeDecodeError) as exc:
                    raise MigrationBundleError(f"表 {table} 第 {line_number} 行不是有效 JSON") from exc
                if not isinstance(values, list) or len(values) != len(columns):
                    raise MigrationBundleError(f"表 {table} 第 {line_number} 行数据列数错误")
                for column, index in indexes:
                    value = values[index]
                    if value in (None, ""):
                        continue
                    archive_name = _portable_artifact_archive_name(value, table, column)
                    if archive_name not in artifact_names:
                        raise MigrationBundleError(
                            f"数据库镜像路径未包含在迁移包中：{table}.{column}: {archive_name}"
                        )
                    observed[f"{table}.{column}"] += 1
    normalized_observed = dict(sorted(observed.items()))
    if normalized_observed != dict(sorted(declared.items())):
        raise MigrationBundleError("迁移包可移植镜像路径数量与清单不一致")
    return normalized_observed


def _validate_case_collision_renames(
    manifest: dict[str, Any],
    artifact_names: set[str],
) -> dict[str, str]:
    artifact_manifest = manifest.get("artifacts")
    raw_renames = artifact_manifest.get("case_collision_renames", {}) if isinstance(artifact_manifest, dict) else {}
    if not isinstance(raw_renames, dict):
        raise MigrationBundleError("迁移包大小写冲突重命名清单格式错误")
    renames: dict[str, str] = {}
    used: set[str] = set()
    for original, assigned in raw_renames.items():
        original_name = _validate_member_name("artifacts/" + str(original)).removeprefix("artifacts/")
        assigned_archive_name = _validate_member_name("artifacts/" + str(assigned))
        root = PurePosixPath(original_name).parts[0].casefold()
        if root not in PORTABLE_CASE_COLLISION_ROOTS:
            raise MigrationBundleError(f"迁移包包含不允许重命名的镜像路径：{original_name}")
        if assigned_archive_name not in artifact_names:
            raise MigrationBundleError(f"大小写冲突重命名文件不在迁移包中：{assigned_archive_name}")
        lowered = assigned_archive_name.casefold()
        if lowered in used:
            raise MigrationBundleError(f"大小写冲突重命名目标重复：{assigned_archive_name}")
        used.add(lowered)
        renames[original_name] = assigned_archive_name.removeprefix("artifacts/")
    return dict(sorted(renames.items()))


def _read_limited(archive: zipfile.ZipFile, name: str, limit: int) -> bytes:
    info = archive.getinfo(name)
    if info.file_size > limit:
        raise MigrationBundleError(f"迁移包元数据过大：{name}")
    with archive.open(info) as handle:
        payload = handle.read(limit + 1)
    if len(payload) > limit:
        raise MigrationBundleError(f"迁移包元数据过大：{name}")
    return payload


def _parse_checksums(payload: bytes) -> dict[str, tuple[str, int | None]]:
    result: dict[str, tuple[str, int | None]] = {}
    try:
        lines = payload.decode("utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise MigrationBundleError("checksums.sha256 不是 UTF-8") from exc
    for line in lines:
        match = re.fullmatch(r"([0-9a-f]{64})  (.+)", line)
        if not match:
            raise MigrationBundleError("checksums.sha256 格式错误")
        name = _validate_member_name(match.group(2))
        if name in result:
            raise MigrationBundleError(f"校验清单包含重复路径：{name}")
        result[name] = (match.group(1), None)
    return result


def _validate_schema_manifest(manifest: dict[str, Any]) -> None:
    if manifest.get("format") != BUNDLE_FORMAT or manifest.get("format_version") != BUNDLE_VERSION:
        raise MigrationBundleError("不支持的迁移包格式或版本")
    if not re.fullmatch(r"[0-9a-f-]{36}", str(manifest.get("bundle_id") or "")):
        raise MigrationBundleError("迁移包批次编号无效")
    spec = manifest.get("schema")
    if not isinstance(spec, dict) or not isinstance(spec.get("tables"), list):
        raise MigrationBundleError("迁移包缺少数据库结构")
    actual = schema_fingerprint(spec)
    expected = str(manifest.get("source", {}).get("schema_fingerprint") or "")
    if actual != expected:
        raise MigrationBundleError("迁移包数据库结构指纹不一致")
    table_payload = manifest.get("tables")
    if not isinstance(table_payload, dict) or set(table_payload) != {table["name"] for table in spec["tables"]}:
        raise MigrationBundleError("迁移包表清单与数据库结构不一致")


def preflight_bundle(
    bundle_path: Path,
    *,
    progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    bundle_path = bundle_path.expanduser().resolve(strict=True)
    max_bundle = int(os.environ.get("DARKWEB_MIGRATION_MAX_BUNDLE_BYTES", DEFAULT_MAX_BUNDLE_BYTES))
    if bundle_path.stat().st_size > max_bundle:
        raise MigrationBundleError("迁移包超过允许大小")
    try:
        archive = zipfile.ZipFile(bundle_path, "r", allowZip64=True)
    except zipfile.BadZipFile as exc:
        raise MigrationBundleError("迁移包不是有效 ZIP64 文件") from exc
    with archive:
        infos = archive.infolist()
        max_entries = int(os.environ.get("DARKWEB_MIGRATION_MAX_ENTRIES", DEFAULT_MAX_ENTRIES))
        if len(infos) > max_entries:
            raise MigrationBundleError("迁移包文件数量超过限制")
        names: dict[str, zipfile.ZipInfo] = {}
        casefolded: set[str] = set()
        total_size = 0
        for info in infos:
            name = _validate_member_name(info.filename)
            lowered = name.casefold()
            if lowered in casefolded:
                raise MigrationBundleError(f"迁移包包含重复路径：{name}")
            casefolded.add(lowered)
            if info.is_dir():
                continue
            mode = (info.external_attr >> 16) & 0o170000
            if mode == 0o120000:
                raise MigrationBundleError(f"迁移包不允许符号链接：{name}")
            total_size += info.file_size
            if info.compress_size and info.file_size > max(100 * 1024 * 1024, info.compress_size * 200):
                raise MigrationBundleError(f"迁移包疑似压缩炸弹：{name}")
            names[name] = info
        max_uncompressed = int(
            os.environ.get("DARKWEB_MIGRATION_MAX_UNCOMPRESSED_BYTES", DEFAULT_MAX_UNCOMPRESSED_BYTES)
        )
        if total_size > max_uncompressed:
            raise MigrationBundleError("迁移包解压后大小超过限制")
        for required in ("manifest.json", "checksums.sha256"):
            if required not in names:
                raise MigrationBundleError(f"迁移包缺少 {required}")
        try:
            manifest = json.loads(_read_limited(archive, "manifest.json", MAX_MANIFEST_BYTES))
        except (ValueError, UnicodeDecodeError) as exc:
            raise MigrationBundleError("manifest.json 格式错误") from exc
        if not isinstance(manifest, dict):
            raise MigrationBundleError("manifest.json 必须是对象")
        _validate_schema_manifest(manifest)
        checksums = _parse_checksums(_read_limited(archive, "checksums.sha256", MAX_CHECKSUM_BYTES))
        payload_names = set(names) - {"manifest.json", "checksums.sha256"}
        if payload_names != set(checksums):
            missing = sorted(payload_names.symmetric_difference(checksums))[:5]
            raise MigrationBundleError(f"迁移包载荷与校验清单不一致：{missing}")
        table_paths = {str(item.get("path") or "") for item in manifest["tables"].values()}
        if not table_paths or not table_paths.issubset(payload_names):
            raise MigrationBundleError("迁移包缺少表数据文件")
        if any(not path.startswith("data/") for path in table_paths):
            raise MigrationBundleError("数据库表数据路径非法")

        artifact_names = {name for name in payload_names if name.startswith("artifacts/")}
        if len(artifact_names) != int(manifest.get("artifacts", {}).get("count", -1)):
            raise MigrationBundleError("镜像文件数量与清单不一致")
        if sum(names[name].file_size for name in artifact_names) != int(
            manifest.get("artifacts", {}).get("bytes", -1)
        ):
            raise MigrationBundleError("镜像文件大小与清单不一致")
        case_collision_renames = _validate_case_collision_renames(manifest, artifact_names)

        ordered_payloads = sorted(payload_names)
        for index, name in enumerate(ordered_payloads):
            digest = hashlib.sha256()
            with archive.open(names[name]) as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
            if digest.hexdigest() != checksums[name][0]:
                raise MigrationBundleError(f"文件校验失败：{name}")
            if index % 100 == 0 or index + 1 == len(ordered_payloads):
                _progress(
                    progress,
                    "preflight",
                    5 + int(25 * (index + 1) / max(1, len(ordered_payloads))),
                    f"正在校验迁移包 {index + 1}/{len(ordered_payloads)}",
                )
        portable_artifact_paths = _validate_portable_artifact_references(
            archive,
            manifest,
            artifact_names,
        )
        if portable_artifact_paths is not None:
            _progress(progress, "preflight", 32, "数据库镜像路径已与迁移包文件逐项核对")

    return {
        "bundle_id": manifest["bundle_id"],
        "created_at": manifest.get("created_at"),
        "schema_fingerprint": manifest["source"]["schema_fingerprint"],
        "tables": len(manifest["tables"]),
        "rows": sum(int(item["stats"]["rows"]) for item in manifest["tables"].values()),
        "artifacts": len(artifact_names),
        "artifact_bytes": int(manifest["artifacts"]["bytes"]),
        "uncompressed_bytes": total_size,
        "portable_artifact_paths": portable_artifact_paths or {},
        "case_collision_renames": len(case_collision_renames),
        "manifest": manifest,
    }


def _postgres_type(sqlite_type: str) -> str:
    normalized = sqlite_type.strip().upper()
    if "INT" in normalized or "BOOL" in normalized:
        return "BIGINT"
    if any(token in normalized for token in ("CHAR", "CLOB", "TEXT", "DATE", "TIME")):
        return "TEXT"
    if any(token in normalized for token in ("REAL", "FLOA", "DOUB")):
        return "DOUBLE PRECISION"
    if any(token in normalized for token in ("NUMERIC", "DECIMAL")):
        return "NUMERIC"
    if "BLOB" in normalized or not normalized:
        return "BYTEA"
    raise MigrationBundleError(f"不支持的 SQLite 字段类型：{sqlite_type!r}")


def _postgres_default(value: Any) -> str | None:
    if value is None:
        return None
    rendered = str(value).strip()
    if re.fullmatch(r"[-+]?\d+(?:\.\d+)?", rendered):
        return rendered
    if re.fullmatch(r"'(?:''|[^'])*'", rendered):
        return rendered
    if rendered.upper() in {"NULL", "CURRENT_TIMESTAMP"}:
        return rendered.upper()
    raise MigrationBundleError(f"不支持的 SQLite 默认值：{rendered}")


def _ordered_tables(spec: dict[str, Any]) -> list[dict[str, Any]]:
    tables = {table["name"]: table for table in spec["tables"]}
    dependencies = {
        name: {
            foreign_key["table"]
            for foreign_key in table["foreign_keys"]
            if foreign_key["table"] in tables and foreign_key["table"] != name
        }
        for name, table in tables.items()
    }
    ordered: list[dict[str, Any]] = []
    remaining = set(tables)
    while remaining:
        ready = sorted(name for name in remaining if not dependencies[name] & remaining)
        if not ready:
            raise MigrationBundleError("循环外键需要专用迁移")
        for name in ready:
            ordered.append(tables[name])
            remaining.remove(name)
    return ordered


def _validate_partial_where(where: str, columns: set[str]) -> str:
    if not where:
        return ""
    match = re.fullmatch(
        r'\s*("(?:""|[^"])+"|[A-Za-z_][A-Za-z0-9_]*)\s*(=|<>)\s*\'(?:\'\'|[^\'])*\'\s*',
        where,
    )
    if not match:
        raise MigrationBundleError(f"不支持的部分索引条件：{where}")
    raw = match.group(1)
    column = raw[1:-1].replace('""', '"') if raw.startswith('"') else raw
    if column not in columns:
        raise MigrationBundleError(f"部分索引引用未知字段：{column}")
    return where


def _create_schema(connection, schema_name: str, spec: dict[str, Any], fingerprint: str) -> None:
    from psycopg2 import sql  # type: ignore

    with connection.cursor() as cursor:
        cursor.execute("SELECT 1 FROM information_schema.schemata WHERE schema_name=%s", (schema_name,))
        if cursor.fetchone():
            raise MigrationBundleError(f"目标 PostgreSQL schema 已存在：{schema_name}")
        cursor.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema_name)))
        cursor.execute(sql.SQL("SET search_path TO {}, public").format(sql.Identifier(schema_name)))
        for table in _ordered_tables(spec):
            columns = table["columns"]
            primary = sorted((c for c in columns if c["pk_order"]), key=lambda c: c["pk_order"])
            definitions = []
            for column in columns:
                parts = [sql.Identifier(column["name"]), sql.SQL(_postgres_type(column["type"]))]
                identity = len(primary) == 1 and primary[0]["name"] == column["name"] and "INT" in column["type"].upper()
                if identity:
                    parts.append(sql.SQL("GENERATED BY DEFAULT AS IDENTITY"))
                if column["notnull"] or column["pk_order"]:
                    parts.append(sql.SQL("NOT NULL"))
                default = _postgres_default(column["default"])
                if default is not None and not identity:
                    parts.extend((sql.SQL("DEFAULT"), sql.SQL(default)))
                definitions.append(sql.SQL(" ").join(parts))
            if primary:
                definitions.append(
                    sql.SQL("PRIMARY KEY ({})").format(
                        sql.SQL(", ").join(sql.Identifier(column["name"]) for column in primary)
                    )
                )
            for check in table.get("checks", []):
                if check.get("operator") != "=" or not isinstance(check.get("value"), int):
                    raise MigrationBundleError("不支持的 CHECK 约束")
                definitions.append(
                    sql.SQL("CHECK ({} = {})").format(
                        sql.Identifier(check["column"]), sql.Literal(check["value"])
                    )
                )
            cursor.execute(
                sql.SQL("CREATE TABLE {} ({})").format(
                    sql.Identifier(table["name"]), sql.SQL(", ").join(definitions)
                )
            )

        for table in _ordered_tables(spec):
            for fk_index, foreign_key in enumerate(table.get("foreign_keys", [])):
                actions = {"NO ACTION", "RESTRICT", "SET NULL", "SET DEFAULT", "CASCADE"}
                on_update = str(foreign_key.get("on_update") or "NO ACTION").upper()
                on_delete = str(foreign_key.get("on_delete") or "NO ACTION").upper()
                if on_update not in actions or on_delete not in actions:
                    raise MigrationBundleError("不支持的外键动作")
                constraint = f"fk_{table['name']}_{fk_index}"
                cursor.execute(
                    sql.SQL(
                        "ALTER TABLE {} ADD CONSTRAINT {} FOREIGN KEY ({}) REFERENCES {} ({}) "
                        f"ON UPDATE {on_update} ON DELETE {on_delete}"
                    ).format(
                        sql.Identifier(table["name"]),
                        sql.Identifier(constraint),
                        sql.SQL(", ").join(sql.Identifier(name) for name in foreign_key["from"]),
                        sql.Identifier(foreign_key["table"]),
                        sql.SQL(", ").join(sql.Identifier(name) for name in foreign_key["to"]),
                    )
                )

        used_indexes: set[str] = set()
        for table in spec["tables"]:
            columns = {column["name"] for column in table["columns"]}
            for index in table.get("indexes", []):
                base = re.sub(r"[^a-zA-Z0-9_]", "_", str(index["name"]))[:48].strip("_") or "idx"
                suffix = hashlib.sha256(f"{table['name']}:{index['name']}".encode()).hexdigest()[:8]
                name = f"{base}_{suffix}"[:63]
                if name in used_indexes:
                    raise MigrationBundleError("索引名称冲突")
                used_indexes.add(name)
                where = _validate_partial_where(str(index.get("where") or ""), columns)
                statement = sql.SQL("CREATE {}INDEX {} ON {} ({})").format(
                    sql.SQL("UNIQUE " if index.get("unique") else ""),
                    sql.Identifier(name),
                    sql.Identifier(table["name"]),
                    sql.SQL(", ").join(sql.Identifier(column) for column in index["columns"]),
                )
                if where:
                    statement += sql.SQL(" WHERE ") + sql.SQL(where)
                cursor.execute(statement)

        cursor.execute(
            """
            CREATE TABLE schema_migrations (
                version TEXT PRIMARY KEY,
                checksum TEXT NOT NULL,
                source_schema_fingerprint TEXT,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cursor.executemany(
            "INSERT INTO schema_migrations(version, checksum, source_schema_fingerprint) VALUES (%s, %s, %s)",
            [
                ("0001_baseline", hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest(), fingerprint),
                (SCHEMA_VERSION, hashlib.sha256(b"sqlite datetime compatibility v1").hexdigest(), None),
            ],
        )
        cursor.execute(
            """
            CREATE OR REPLACE FUNCTION datetime(value TEXT)
            RETURNS TIMESTAMP WITHOUT TIME ZONE
            LANGUAGE plpgsql IMMUTABLE AS $$
            BEGIN
                RETURN NULLIF(BTRIM(value), '')::TIMESTAMP WITHOUT TIME ZONE;
            EXCEPTION WHEN OTHERS THEN
                RETURN NULL;
            END;
            $$
            """
        )


def _table_stats_postgres(connection, table: dict[str, Any]) -> dict[str, Any]:
    from psycopg2 import sql  # type: ignore

    columns = [column["name"] for column in table["columns"]]
    stats = _empty_stats(columns)
    with connection.cursor(name=f"verify_{table['name']}") as cursor:
        cursor.itersize = 1000
        cursor.execute(
            sql.SQL("SELECT {} FROM {}").format(
                sql.SQL(", ").join(sql.Identifier(name) for name in columns),
                sql.Identifier(table["name"]),
            )
        )
        for row in cursor:
            _update_stats(stats, columns, row)
    return _finalize_stats(stats)


def _reset_identity(connection, table: dict[str, Any], schema_name: str) -> None:
    from psycopg2 import sql  # type: ignore

    primary = [column for column in table["columns"] if column["pk_order"]]
    if len(primary) != 1 or "INT" not in primary[0]["type"].upper():
        return
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT pg_get_serial_sequence(%s, %s)",
            (f'{schema_name}."{table["name"]}"', primary[0]["name"]),
        )
        sequence = cursor.fetchone()[0]
        if not sequence:
            return
        cursor.execute(
            sql.SQL("SELECT MAX({}) FROM {}").format(
                sql.Identifier(primary[0]["name"]), sql.Identifier(table["name"])
            )
        )
        maximum = cursor.fetchone()[0]
        cursor.execute(
            "SELECT setval(%s::regclass, %s, %s)",
            (sequence, int(maximum or 1), bool(maximum is not None)),
        )


def _extract_artifacts(archive: zipfile.ZipFile, release_root: Path, progress: ProgressCallback | None) -> None:
    artifact_infos = sorted(
        (info for info in archive.infolist() if info.filename.startswith("artifacts/") and not info.is_dir()),
        key=lambda info: info.filename,
    )
    artifact_root = release_root / "artifacts"
    artifact_root.mkdir(parents=True, exist_ok=False)
    for index, info in enumerate(artifact_infos):
        relative = PurePosixPath(info.filename).relative_to("artifacts")
        target = artifact_root.joinpath(*relative.parts)
        resolved_parent = target.parent.resolve()
        if artifact_root.resolve() not in (resolved_parent, *resolved_parent.parents):
            raise MigrationBundleError("镜像文件路径越界")
        os.makedirs(_native_path(target.parent), exist_ok=True)
        with archive.open(info) as source, open(_native_path(target), "xb") as destination:
            shutil.copyfileobj(source, destination, length=1024 * 1024)
        if index % 100 == 0 or index + 1 == len(artifact_infos):
            _progress(
                progress,
                "artifacts",
                30 + int(20 * (index + 1) / max(1, len(artifact_infos))),
                f"正在释放镜像文件 {index + 1}/{len(artifact_infos)}",
            )


def _materialize_portable_artifact_row(
    table: str,
    columns: Sequence[str],
    values: Sequence[Any],
    artifact_root: Path,
    artifact_names: set[str],
) -> list[Any]:
    result = list(values)
    indexes = [
        (column, columns.index(column))
        for column in PORTABLE_ARTIFACT_PATH_COLUMNS.get(table, set())
        if column in columns and result[columns.index(column)] not in (None, "")
    ]
    if not indexes:
        return result
    resolved_root = artifact_root.resolve(strict=True)
    for column, index in indexes:
        archive_name = _portable_artifact_archive_name(result[index], table, column)
        if archive_name not in artifact_names:
            raise MigrationBundleError(f"数据库镜像路径未包含在迁移包中：{table}.{column}")
        relative = PurePosixPath(archive_name).relative_to("artifacts")
        target = artifact_root.joinpath(*relative.parts).resolve(strict=True)
        if resolved_root not in target.parents:
            raise MigrationBundleError(f"数据库镜像路径越界：{table}.{column}")
        result[index] = str(target)
    return result


def import_bundle(
    bundle_path: Path,
    target_database_url: str,
    job_id: str,
    *,
    progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    if not target_database_url.lower().startswith(("postgres://", "postgresql://")):
        raise MigrationBundleError("目标数据库必须是 PostgreSQL URL")
    summary = preflight_bundle(bundle_path, progress=progress)
    manifest = summary.pop("manifest")
    normalized_id = re.sub(r"[^a-z0-9]", "", str(manifest["bundle_id"]).lower())[:24]
    schema_name = f"dwti_{normalized_id}"
    release_root = migration_root() / "releases" / job_id
    if release_root.exists():
        raise MigrationBundleError("迁移批次目录已存在")
    release_root.mkdir(parents=True)
    connection = None
    schema_created = False
    try:
        with zipfile.ZipFile(bundle_path, "r", allowZip64=True) as archive:
            _extract_artifacts(archive, release_root, progress)
            artifact_root = release_root / "artifacts"
            artifact_names = {
                info.filename
                for info in archive.infolist()
                if info.filename.startswith("artifacts/") and not info.is_dir()
            }
            portable_paths_enabled = "portable_path_fields" in manifest.get("artifacts", {})
            try:
                import psycopg2  # type: ignore
                from psycopg2 import sql  # type: ignore
                from psycopg2.extras import execute_values  # type: ignore
            except ImportError as exc:
                raise MigrationBundleError("未安装 PostgreSQL 驱动 psycopg2") from exc
            connection = psycopg2.connect(target_database_url, application_name="dwti-migration-import")
            _create_schema(connection, schema_name, manifest["schema"], summary["schema_fingerprint"])
            schema_created = True
            with connection.cursor() as cursor:
                cursor.execute(sql.SQL("SET search_path TO {}, public").format(sql.Identifier(schema_name)))
            ordered = _ordered_tables(manifest["schema"])
            import_expected_stats: dict[str, dict[str, Any]] = {}
            for index, table in enumerate(ordered):
                table_name = table["name"]
                table_manifest = manifest["tables"][table_name]
                columns = [column["name"] for column in table["columns"]]
                insert_sql = sql.SQL("INSERT INTO {} ({}) VALUES %s").format(
                    sql.Identifier(table_name),
                    sql.SQL(", ").join(sql.Identifier(name) for name in columns),
                )
                batch: list[tuple[Any, ...]] = []
                transformed_stats = (
                    _empty_stats(columns)
                    if portable_paths_enabled and table_name in PORTABLE_ARTIFACT_PATH_COLUMNS
                    else None
                )
                with archive.open(table_manifest["path"]) as raw:
                    max_row_bytes = int(
                        os.environ.get("DARKWEB_MIGRATION_MAX_ROW_BYTES", DEFAULT_MAX_ROW_BYTES)
                    )
                    line_number = 0
                    while True:
                        encoded_line = raw.readline(max_row_bytes + 1)
                        if not encoded_line:
                            break
                        line_number += 1
                        if len(encoded_line) > max_row_bytes:
                            raise MigrationBundleError(
                                f"表 {table_name} 第 {line_number} 行超过大小限制"
                            )
                        try:
                            values = json.loads(encoded_line.decode("utf-8"))
                        except (ValueError, UnicodeDecodeError) as exc:
                            raise MigrationBundleError(
                                f"表 {table_name} 第 {line_number} 行不是有效 JSON"
                            ) from exc
                        if not isinstance(values, list) or len(values) != len(columns):
                            raise MigrationBundleError(f"表 {table_name} 数据列数错误")
                        decoded_values = tuple(_decode_json_value(value) for value in values)
                        if portable_paths_enabled and table_name in PORTABLE_ARTIFACT_PATH_COLUMNS:
                            decoded_values = tuple(
                                _materialize_portable_artifact_row(
                                    table_name,
                                    columns,
                                    decoded_values,
                                    artifact_root,
                                    artifact_names,
                                )
                            )
                        if transformed_stats is not None:
                            _update_stats(transformed_stats, columns, decoded_values)
                        batch.append(decoded_values)
                        if len(batch) >= 500:
                            with connection.cursor() as cursor:
                                execute_values(cursor, insert_sql.as_string(connection), batch, page_size=500)
                            batch.clear()
                    if batch:
                        with connection.cursor() as cursor:
                            execute_values(cursor, insert_sql.as_string(connection), batch, page_size=500)
                if transformed_stats is not None:
                    import_expected_stats[table_name] = _finalize_stats(transformed_stats)
                _reset_identity(connection, table, schema_name)
                _progress(
                    progress,
                    "database",
                    50 + int(30 * (index + 1) / max(1, len(ordered))),
                    f"正在导入数据库表 {index + 1}/{len(ordered)}",
                )

            mismatches = []
            for index, table in enumerate(ordered):
                actual = _table_stats_postgres(connection, table)
                expected = import_expected_stats.get(
                    table["name"],
                    manifest["tables"][table["name"]]["stats"],
                )
                if actual != expected:
                    mismatches.append({"table": table["name"], "expected": expected, "actual": actual})
                _progress(
                    progress,
                    "verify",
                    80 + int(15 * (index + 1) / max(1, len(ordered))),
                    f"正在校验数据库表 {index + 1}/{len(ordered)}",
                )
            if mismatches:
                raise MigrationBundleError(
                    "PostgreSQL 数据摘要不一致：" + ", ".join(item["table"] for item in mismatches[:5])
                )
            connection.commit()
            with connection.cursor() as cursor:
                cursor.execute("SELECT current_database()")
                database_name = str(cursor.fetchone()[0])
        report = {
            **summary,
            "status": "ready",
            "job_id": job_id,
            "database_engine": "postgresql",
            "database_name": database_name,
            "database_schema": schema_name,
            "output_root": str((release_root / "artifacts").resolve()),
            "verified_at": _utc_now(),
        }
        (release_root / "import-report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        _progress(progress, "ready", 100, "迁移包已导入并通过联合校验，等待激活")
        return report
    except Exception:
        if connection is not None:
            try:
                connection.rollback()
                if schema_created:
                    from psycopg2 import sql  # type: ignore

                    connection.autocommit = True
                    with connection.cursor() as cursor:
                        cursor.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema_name)))
            except Exception:
                pass
        shutil.rmtree(release_root, ignore_errors=True)
        raise
    finally:
        if connection is not None:
            connection.close()


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    try:
        temporary.chmod(0o600)
    except OSError:
        pass
    os.replace(temporary, path)


def activate_import(report: dict[str, Any], target_database_url: str) -> dict[str, Any]:
    release_root = migration_root() / "releases" / str(report["job_id"])
    expected_output = (release_root / "artifacts").resolve(strict=True)
    if expected_output != Path(report["output_root"]).resolve(strict=True):
        raise MigrationBundleError("迁移批次镜像路径不一致")
    current_path = active_release_path()
    previous = None
    if current_path.exists():
        try:
            previous = json.loads(current_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            previous = None
    if isinstance(previous, dict) and previous.get("job_id") == report["job_id"]:
        public = dict(previous)
        public.pop("database_url", None)
        return public
    if previous:
        _atomic_json(release_root / "previous-active-release.json", previous)
    active = {
        "format": 1,
        "activated_at": _utc_now(),
        "job_id": report["job_id"],
        "bundle_id": report["bundle_id"],
        "database_engine": "postgresql",
        "database_url": target_database_url,
        "database_schema": report["database_schema"],
        "schema_fingerprint": report["schema_fingerprint"],
        "schema_version": SCHEMA_VERSION,
        "output_root": str(expected_output),
    }
    _atomic_json(current_path, active)
    public = dict(active)
    public.pop("database_url", None)
    return public


def restore_previous_active(job_id: str) -> None:
    release_root = migration_root() / "releases" / job_id
    previous = release_root / "previous-active-release.json"
    current = active_release_path()
    if previous.exists():
        current.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(previous, current)
    else:
        current.unlink(missing_ok=True)


def public_active_release() -> dict[str, Any]:
    path = active_release_path()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"database_engine": "sqlite", "active": False}
    if not isinstance(payload, dict):
        return {"database_engine": "sqlite", "active": False}
    payload.pop("database_url", None)
    payload["active"] = True
    return payload
