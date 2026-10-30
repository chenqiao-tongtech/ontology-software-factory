#!/usr/bin/env python3
"""Unified local portal for the ontology-driven software factory.

Binds to loopback by default. It is a development/reference portal, not an authenticated
multi-user production service. Mutating APIs are intended for the local operator only.
"""
from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, unquote, urlparse
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from ontology_software_factory.source_connectors import (
    LocalDirectoryConnector,
    SQLiteSchemaConnector,
    SourceConnectorError,
    SourceConnectorRegistry,
)

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "apps" / "factory-portal" / "index.html"
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))
STATE_DIR = ROOT / ".local-portal"
STATE_PATH = STATE_DIR / "state.json"
SOURCES_PATH = ROOT / "config" / "integrations" / "sources.json"
FORMAL_ONTOLOGY = ROOT / "ontology" / "software-factory-ontology.json"
STATE_LOCK = threading.RLock()

SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", ".idea", ".vscode", ".local-runs", "deliverables", "dist", "build"}
ALLOWED_SUFFIXES = {".py", ".md", ".rst", ".json", ".yaml", ".yml", ".toml", ".sql", ".html", ".js", ".ts", ".tsx", ".jsx", ".mmd", ".xml", ".proto", ".graphql"}
SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,70}$")


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def dump(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def create_demo_db(path: Path) -> None:
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS service_catalog (
          service_id TEXT PRIMARY KEY, service_name TEXT NOT NULL, owner_team TEXT NOT NULL,
          lifecycle_status TEXT NOT NULL, api_version TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS schema_assets (
          asset_id TEXT PRIMARY KEY, service_id TEXT NOT NULL, asset_name TEXT NOT NULL,
          asset_type TEXT NOT NULL, source_revision TEXT NOT NULL
        );
        INSERT OR IGNORE INTO service_catalog VALUES
          ('svc-order-demo','订单服务（示例）','platform-demo','active','v1'),
          ('svc-payment-demo','支付服务（示例）','payments-demo','active','v2');
        INSERT OR IGNORE INTO schema_assets VALUES
          ('asset-order-db','svc-order-demo','orders','table','fixture-1'),
          ('asset-payment-api','svc-payment-demo','PaymentAuthorized','event','fixture-1');
        """)


def ensure_state() -> dict:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    create_demo_db(STATE_DIR / "demo-catalog.sqlite3")
    if not SOURCES_PATH.exists():
        SOURCES_PATH.parent.mkdir(parents=True, exist_ok=True)
        dump(SOURCES_PATH, {"schemaVersion": "1.0.0", "sources": [
            {"id": "source-project", "name": "软件工厂工程目录", "type": "repository", "path": ".", "description": "当前本地工程根目录；有 Git 元数据时读取最近提交，否则按源码目录扫描。", "enabled": True, "fixture": False},
            {"id": "source-docs", "name": "工程文档库", "type": "documents", "path": "docs", "description": "项目架构、ADR、验收和操作手册。", "enabled": True, "fixture": False},
            {"id": "source-demo-db", "name": "业务元数据 SQLite 示例库", "type": "sqlite", "path": ".local-portal/demo-catalog.sqlite3", "description": "本地生成的合成数据，用于演示只读表结构发现，不代表企业数据。", "enabled": True, "fixture": True}
        ]})
    state = load_json(STATE_PATH, None)
    if not isinstance(state, dict) or state.get("schemaVersion") != "1.0.0":
        state = {"schemaVersion": "1.0.0", "ontologyCandidates": [], "ontologyChanges": [], "agentRuns": [], "qualityRuns": [], "portalEvents": [], "releaseApprovals": []}
        dump(STATE_PATH, state)
    return state


def source_configs() -> list[dict]:
    cfg = load_json(SOURCES_PATH, {"sources": []})
    return cfg.get("sources", []) if isinstance(cfg, dict) else []


def save_sources(sources: list[dict]) -> None:
    dump(SOURCES_PATH, {"schemaVersion": "1.0.0", "sources": sources})


def source_path(source: dict) -> Path:
    value = Path(str(source.get("path", ""))).expanduser()
    resolved = (ROOT / value).resolve() if not value.is_absolute() else value.resolve()
    return resolved


def path_is_safe_for_walk(path: Path) -> bool:
    return path.is_dir() and path.exists()


def iter_safe_files(base: Path, max_files: int = 600):
    count = 0
    for current, dirs, files in os.walk(base, followlinks=False):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
        for name in files:
            p = Path(current) / name
            if p.is_symlink() or name.startswith(".") or p.suffix.lower() not in ALLOWED_SUFFIXES:
                continue
            try:
                if p.stat().st_size > 1_500_000:
                    continue
            except OSError:
                continue
            yield p
            count += 1
            if count >= max_files:
                return


def git_metadata(path: Path) -> dict:
    if shutil.which("git") is None:
        return {"available": False, "reason": "git CLI is not installed"}
    try:
        top = subprocess.run(["git", "-C", str(path), "rev-parse", "--show-toplevel"], capture_output=True, text=True, timeout=3)
        if top.returncode:
            return {"available": False, "reason": "path is not a Git working tree"}
        branch = subprocess.run(["git", "-C", str(path), "branch", "--show-current"], capture_output=True, text=True, timeout=3)
        commit = subprocess.run(["git", "-C", str(path), "log", "-1", "--format=%h %s"], capture_output=True, text=True, timeout=3)
        status = subprocess.run(["git", "-C", str(path), "status", "--short"], capture_output=True, text=True, timeout=3)
        return {"available": True, "root": top.stdout.strip(), "branch": branch.stdout.strip() or "detached", "lastCommit": commit.stdout.strip(), "dirtyFileCount": len([x for x in status.stdout.splitlines() if x.strip()])}
    except (OSError, subprocess.TimeoutExpired):
        return {"available": False, "reason": "Git metadata query failed or timed out"}


def _remote_json(url: str, headers: dict[str, str]) -> tuple[int, object]:
    request = Request(url, headers=headers, method="GET")
    try:
        with urlopen(request, timeout=8) as response:
            raw = response.read(2_000_000)
            return response.status, json.loads(raw.decode("utf-8"))
    except HTTPError as exc:
        try: detail = json.loads(exc.read(200_000).decode("utf-8"))
        except Exception: detail = {}
        return exc.code, detail
    except (URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        raise ConnectionError(type(exc).__name__) from exc


def scan_remote_repository(source: dict, result: dict) -> dict:
    """Use the same connector contract for GitHub and GitLab metadata scans."""
    try:
        connector = RemoteRepositoryConnector(
            source["type"], _remote_json,
            token_env=str(source.get("tokenEnv") or ("GITHUB_TOKEN" if source["type"] == "github" else "GITLAB_TOKEN")),
            max_assets=600,
        )
        scanned = connector.scan(source["id"], source.get("url", ""))
        assets = [
            {
                "path": asset.locator,
                "kind": (asset.metadata or {}).get("suffix", "").lstrip("."),
                "bytes": asset.size_bytes,
                "assetId": asset.asset_id,
                "sourceRevision": (asset.metadata or {}).get("sourceRevision"),
            }
            for asset in scanned.assets[:50]
        ]
        first_meta = scanned.assets[0].metadata if scanned.assets else {}
        result.update(
            status=scanned.status,
            assetCount=len(scanned.assets),
            assets=assets,
            details={
                "provider": source["type"],
                "connector": "RemoteRepositoryConnector",
                "defaultBranch": (first_meta or {}).get("defaultBranch"),
                "sourceRevision": (first_meta or {}).get("sourceRevision"),
                "tokenConfigured": bool(os.getenv(str(source.get("tokenEnv") or ("GITHUB_TOKEN" if source["type"] == "github" else "GITLAB_TOKEN")))),
                "warnings": list(scanned.warnings),
                "mode": "repository/file metadata only; no file bodies downloaded",
            },
            message="Remote repository metadata fetched through SourceConnector registry",
        )
    except SourceConnectorError as exc:
        message = str(exc)
        status = "invalid-url" if "URL" in message or "url" in message or "allow-list" in message else "unavailable"
        result.update(status=status, message=message, details={"provider": source["type"], "connector": "RemoteRepositoryConnector"})
    except ConnectionError as exc:
        result.update(status="unavailable", message=f"Remote provider connection failed ({type(exc).__name__})", details={"provider": source["type"]})
    return result
def build_source_connector_registry(allowed_root: Path, *, remote_fetcher=None, source: dict | None = None) -> SourceConnectorRegistry:
    """Build the explicit connector registry used by Portal source scans."""
    registry = SourceConnectorRegistry()
    registry.register(LocalDirectoryConnector([allowed_root], source_type="repository", max_files=600, max_file_bytes=1_500_000))
    registry.register(LocalDirectoryConnector([allowed_root], source_type="documents", max_files=600, max_file_bytes=1_500_000))
    registry.register(SQLiteSchemaConnector([allowed_root]))
    if remote_fetcher is not None:
        for provider in ("github", "gitlab"):
            token_default = "GITHUB_TOKEN" if provider == "github" else "GITLAB_TOKEN"
            registry.register(RemoteRepositoryConnector(provider, remote_fetcher, token_env=str((source or {}).get("tokenEnv") or token_default), max_assets=600))
    if source:
        allowed_hosts = source.get("allowedHosts", [])
        if source.get("type") == "postgresql" and allowed_hosts:
            registry.register(PostgreSQLSchemaConnector(allowed_hosts=allowed_hosts))
        if source.get("type") == "mysql" and allowed_hosts:
            registry.register(MySQLSchemaConnector(allowed_hosts=allowed_hosts))
    return registry
    if source["type"] in {"postgresql", "mysql"}:
        try:
            registry = build_source_connector_registry(ROOT, source=source)
            scanned = registry.scan(source["type"], source["id"], str(source.get("connectionEnv", "")))
            tables = [
                {
                    "name": asset.name,
                    "kind": asset.kind,
                    "path": asset.locator,
                    "schema": (asset.metadata or {}).get("schema"),
                    "columns": (asset.metadata or {}).get("columns", []),
                    "assetId": asset.asset_id,
                }
                for asset in scanned.assets
            ]
            result.update(status=scanned.status, assetCount=len(tables), assets=tables[:30],
                details={"tables": tables, "connector": "PostgreSQLSchemaConnector" if source["type"] == "postgresql" else "MySQLSchemaConnector",
                         "mode": "read-only information_schema metadata", "warnings": list(scanned.warnings)},
                message="Database schema metadata read in read-only mode; business rows were not queried")
            return result
        except (SourceConnectorError, OSError, ValueError) as exc:
            result.update(status="error", message=f"Database schema scan failed: {type(exc).__name__}")
            return result

