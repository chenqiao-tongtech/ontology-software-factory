"""Read-only local source connectors for ontology discovery.

This module inventories repository/document directories and SQLite schema metadata.
It does not execute source code, read database rows, or mutate connected systems.
Remote providers should implement the same SourceConnector protocol behind explicit
host allow-lists and credential providers; this module intentionally has no network access.
"""
from __future__ import annotations

import hashlib
import os
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Protocol

TEXT_SUFFIXES = {
    ".md", ".mdx", ".rst", ".txt", ".py", ".pyi", ".js", ".jsx", ".ts", ".tsx",
    ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".sql", ".xml", ".xsd",
    ".ttl", ".owl", ".properties", ".conf", ".sh", ".go", ".java", ".kt", ".rs",
}
EXCLUDED_DIRS = {
    ".git", ".hg", ".svn", ".venv", "venv", "node_modules", "__pycache__",
    ".pytest_cache", ".mypy_cache", ".ruff_cache", "dist", "build", "target",
}
EXCLUDED_NAMES = {
    ".env", ".env.local", ".env.production", "id_rsa", "id_ed25519",
    "credentials", "secrets.json", "secrets.yaml", "secrets.yml",
}
DEFAULT_MAX_FILES = 20_000
DEFAULT_MAX_FILE_BYTES = 1_000_000


class SourceConnectorError(RuntimeError):
    """A source could not be safely inspected."""


@dataclass(frozen=True)
class SourceAsset:
    asset_id: str
    source_id: str
    kind: str
    name: str
    locator: str
    content_sha256: str | None = None
    size_bytes: int | None = None
    metadata: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SourceScanResult:
    source_id: str
    source_type: str
    status: str
    assets: tuple[SourceAsset, ...]
    warnings: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "sourceId": self.source_id,
            "sourceType": self.source_type,
            "status": self.status,
            "assetCount": len(self.assets),
            "assets": [asset.as_dict() for asset in self.assets],
            "warnings": list(self.warnings),
        }


class SourceConnector(Protocol):
    source_type: str

    def scan(self, source_id: str, location: str | Path) -> SourceScanResult: ...


def _asset_id(source_id: str, locator: str, kind: str) -> str:
    seed = f"{source_id}\0{kind}\0{locator}".encode("utf-8")
    return "asset-" + hashlib.sha256(seed).hexdigest()[:20]


def _within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


class LocalDirectoryConnector:
    """Inventory safe text files below an explicitly allowed local directory."""

    source_type = "repository"

    def __init__(self, allowed_roots: list[str | Path], *,
                 source_type: str = "repository",
                 max_files: int = DEFAULT_MAX_FILES,
                 max_file_bytes: int = DEFAULT_MAX_FILE_BYTES):
        if source_type not in {"repository", "documents"}:
            raise ValueError("directory source_type must be repository or documents")
        if max_files < 1 or max_file_bytes < 1:
            raise ValueError("scan limits must be positive")
        self.source_type = source_type
        self.allowed_roots = tuple(Path(item).expanduser().resolve() for item in allowed_roots)
        self.max_files = max_files
        self.max_file_bytes = max_file_bytes

    def _resolve_root(self, location: str | Path) -> Path:
        raw = Path(location).expanduser()
        if raw.is_symlink():
            raise SourceConnectorError("source root must not be a symbolic link")
        try:
            root = raw.resolve(strict=True)
        except OSError as exc:
            raise SourceConnectorError("source root does not exist or cannot be resolved") from exc
        if not root.is_dir():
            raise SourceConnectorError("source root must be a directory")
        if not any(_within(root, allowed) for allowed in self.allowed_roots):
            raise SourceConnectorError("source root is outside configured allowed roots")
        return root

    def scan(self, source_id: str, location: str | Path) -> SourceScanResult:
        if not source_id.strip():
            raise ValueError("source_id must not be blank")
        root = self._resolve_root(location)
        assets: list[SourceAsset] = []
        warnings: list[str] = []
        for current, dirs, files in os.walk(root, topdown=True, followlinks=False):
            current_path = Path(current)
            dirs[:] = sorted(
                name for name in dirs
                if not name.startswith(".")
                and name not in EXCLUDED_DIRS
                and not (current_path / name).is_symlink()
            )
            for name in sorted(files):
                candidate = current_path / name
                if name.startswith(".") or name.casefold() in EXCLUDED_NAMES:
                    continue
                if candidate.is_symlink() or candidate.suffix.casefold() not in TEXT_SUFFIXES:
                    continue
                try:
                    resolved = candidate.resolve(strict=True)
                    if not _within(resolved, root) or not resolved.is_file():
                        warnings.append(f"skipped unsafe path: {candidate.relative_to(root).as_posix()}")
                        continue
                    size = resolved.stat().st_size
                    if size > self.max_file_bytes:
                        warnings.append(f"skipped oversized file: {candidate.relative_to(root).as_posix()}")
                        continue
                    payload = resolved.read_bytes()
                except OSError:
                    warnings.append(f"skipped unreadable file: {candidate.relative_to(root).as_posix()}")
                    continue
                try:
                    payload.decode("utf-8")
                except UnicodeDecodeError:
                    warnings.append(f"skipped non-UTF-8 file: {candidate.relative_to(root).as_posix()}")
                    continue
                locator = candidate.relative_to(root).as_posix()
                assets.append(SourceAsset(
                    asset_id=_asset_id(source_id, locator, "file"),
                    source_id=source_id,
                    kind="file",
                    name=name,
                    locator=locator,
                    content_sha256=hashlib.sha256(payload).hexdigest(),
                    size_bytes=size,
                    metadata={"suffix": candidate.suffix.casefold()},
                ))
                if len(assets) >= self.max_files:
                    warnings.append(f"file limit reached: {self.max_files}")
                    return SourceScanResult(source_id, self.source_type, "partial", tuple(assets), tuple(warnings))
        return SourceScanResult(source_id, self.source_type, "connected", tuple(assets), tuple(warnings))


class SQLiteSchemaConnector:
    """Read SQLite schema metadata through a read-only connection; never reads table rows."""

    source_type = "sqlite"

    def __init__(self, allowed_roots: list[str | Path]):
        self.allowed_roots = tuple(Path(item).expanduser().resolve() for item in allowed_roots)

    def scan(self, source_id: str, location: str | Path) -> SourceScanResult:
        if not source_id.strip():
            raise ValueError("source_id must not be blank")
        raw = Path(location).expanduser()
        if raw.is_symlink():
            raise SourceConnectorError("database path must not be a symbolic link")
        try:
            path = raw.resolve(strict=True)
        except OSError as exc:
            raise SourceConnectorError("database file does not exist or cannot be resolved") from exc
        if not path.is_file() or path.suffix.casefold() not in {".db", ".sqlite", ".sqlite3"}:
            raise SourceConnectorError("source must be an existing SQLite database file")
        if not any(_within(path, root) for root in self.allowed_roots):
            raise SourceConnectorError("database file is outside configured allowed roots")
        uri = path.as_uri() + "?mode=ro"
        assets: list[SourceAsset] = []
        connection = None
        try:
            connection = sqlite3.connect(uri, uri=True, timeout=5)
            connection.execute("PRAGMA query_only = ON")
            objects = connection.execute(
                "SELECT type, name, sql FROM sqlite_master "
                "WHERE type IN ('table', 'view') AND name NOT LIKE 'sqlite_%' "
                "ORDER BY type, name"
            ).fetchall()
            for object_type, name, ddl in objects:
                identifier = '"' + str(name).replace('"', '""') + '"'
                columns = connection.execute(f"PRAGMA table_info({identifier})").fetchall()
                locator = f"{object_type}:{name}"
                assets.append(SourceAsset(
                    asset_id=_asset_id(source_id, locator, object_type),
                    source_id=source_id,
                    kind=object_type,
                    name=str(name),
                    locator=locator,
                    metadata={
                        "columns": [
                            {"name": row[1], "type": row[2], "notNull": bool(row[3]),
                             "primaryKeyPosition": int(row[5])}
                            for row in columns
                        ],
                        "definition": ddl,
                    },
                ))
        except sqlite3.Error as exc:
            raise SourceConnectorError(f"SQLite schema scan failed: {type(exc).__name__}") from exc
        finally:
            if connection is not None:
                connection.close()
        return SourceScanResult(source_id, self.source_type, "connected", tuple(assets))


class SourceConnectorRegistry:
    """Small explicit registry; unknown connector types fail closed."""

    def __init__(self) -> None:
        self._connectors: dict[str, SourceConnector] = {}

    def register(self, connector: SourceConnector) -> None:
        if connector.source_type in self._connectors:
            raise ValueError(f"connector already registered: {connector.source_type}")
        self._connectors[connector.source_type] = connector

    def scan(self, source_type: str, source_id: str, location: str | Path) -> SourceScanResult:
        connector = self._connectors.get(source_type)
        if connector is None:
            raise SourceConnectorError(f"unsupported source type: {source_type}")
        return connector.scan(source_id, location)
