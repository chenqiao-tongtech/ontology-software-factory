#!/usr/bin/env python3
"""Unified local portal for the ontology-driven software factory.

Binds to loopback by default. It is a development/reference portal, not an authenticated
multi-user production service. Mutating APIs are intended for the local operator only.
"""
from __future__ import annotations

import argparse
import base64
import json
import hashlib
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
from ontology_software_factory.remote_connectors import RemoteRepositoryConnector
from ontology_software_factory.database_connectors import PostgreSQLSchemaConnector, MySQLSchemaConnector

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
        state = {"schemaVersion": "1.0.0", "ontologyCandidates": [], "ontologyChanges": [], "agentRuns": [], "qualityRuns": [], "portalEvents": [], "releaseApprovals": [], "sourceSyncHistory": {}}
        dump(STATE_PATH, state)
    # Additive state migration: preserve existing local portal data.
    state.setdefault("sourceSyncHistory", {})
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


def remote_asset_browse_url(source: dict, path: str, branch: str | None) -> str | None:
    """Build a provider-host-allowlisted browser link; never use credentials or arbitrary hosts."""
    parsed = urlparse(str(source.get("url", "")))
    provider = source.get("type")
    expected_host = "github.com" if provider == "github" else "gitlab.com" if provider == "gitlab" else None
    if parsed.scheme != "https" or parsed.hostname != expected_host or parsed.username or parsed.password:
        return None
    segments = [part for part in parsed.path.strip("/").split("/") if part]
    if provider == "github" and len(segments) == 2:
        owner, project = segments
        if project.endswith(".git"): project = project[:-4]
        return f"https://github.com/{owner}/{project}/blob/{quote(str(branch or 'main'), safe='/')}/{quote(path, safe='/')}"
    if provider == "gitlab" and len(segments) >= 2:
        project = "/".join(segments)
        if project.endswith(".git"): project = project[:-4]
        return f"https://gitlab.com/{project}/-/blob/{quote(str(branch or 'main'), safe='/')}/{quote(path, safe='/')}"
    return None


def scan_remote_repository(source: dict, result: dict) -> dict:
    """Use the common connector registry for GitHub and GitLab metadata scans."""
    try:
        registry = build_source_connector_registry(ROOT, remote_fetcher=_remote_json, source=source)
        scanned = registry.scan(source["type"], source["id"], source.get("url", ""))
        first_meta = scanned.assets[0].metadata if scanned.assets else {}
        branch = (first_meta or {}).get("defaultBranch")
        assets = [{"path": asset.locator, "kind": (asset.metadata or {}).get("suffix", "").lstrip("."),
                   "bytes": asset.size_bytes, "assetId": asset.asset_id,
                   "sourceRevision": (asset.metadata or {}).get("sourceRevision"),
                   "browseUrl": remote_asset_browse_url(source, asset.locator, (asset.metadata or {}).get("defaultBranch"))}
                  for asset in scanned.assets[:50]]
        token_env = str(source.get("tokenEnv") or ("GITHUB_TOKEN" if source["type"] == "github" else "GITLAB_TOKEN"))
        result.update(status=scanned.status, assetCount=len(scanned.assets), assets=assets,
            details={"provider": source["type"], "connector": "RemoteRepositoryConnector",
                     "defaultBranch": (first_meta or {}).get("defaultBranch"),
                     "sourceRevision": (first_meta or {}).get("sourceRevision"),
                     "tokenConfigured": bool(os.getenv(token_env)), "warnings": list(scanned.warnings),
                     "mode": "repository/file metadata only; no file bodies downloaded"},
            message="Remote repository metadata fetched through SourceConnector registry")
    except SourceConnectorError as exc:
        message = str(exc)
        status = "invalid-url" if "HTTPS" in message or "path is invalid" in message else "unavailable"
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
            token_env = str((source or {}).get("tokenEnv") or token_default) if (source or {}).get("type") == provider else token_default
            registry.register(RemoteRepositoryConnector(provider, remote_fetcher, token_env=token_env, max_assets=600))
    if source:
        allowed_hosts = source.get("allowedHosts", [])
        if source.get("type") == "postgresql" and allowed_hosts:
            registry.register(PostgreSQLSchemaConnector(allowed_hosts=allowed_hosts))
        if source.get("type") == "mysql" and allowed_hosts:
            registry.register(MySQLSchemaConnector(allowed_hosts=allowed_hosts))
    return registry


def scan_source(source: dict, *, allow_remote: bool = False) -> dict:
    path_label = source.get("url", source.get("path", source.get("connectionEnv", "")))
    result = {"id": source["id"], "name": source["name"], "type": source["type"], "pathLabel": str(path_label), "enabled": bool(source.get("enabled", True)), "fixture": bool(source.get("fixture")), "lastSyncAt": now_iso(), "status": "error", "assetCount": 0, "assets": [], "details": {}}
    if source.get("type") in {"github", "gitlab", "postgresql", "mysql"}:
        if not allow_remote:
            result.update(status="not-synced", message="Remote repository/database is not queried by background refresh; use explicit Sync to fetch metadata")
            return result
        if not source.get("enabled", True):
            result.update(status="disabled", message="Source disabled")
            return result
        return scan_remote_repository(source, result)
    base = source_path(source)
    if not source.get("enabled", True):
        result.update(status="disabled", message="Source disabled")
        return result
    if source["type"] == "sqlite":
        try:
            scanned = build_source_connector_registry(base.parent).scan("sqlite", source["id"], base)
            tables = [
                {
                    "name": asset.name,
                    "assetId": asset.asset_id,
                    "path": asset.locator,
                    "kind": asset.kind,
                    "columns": [
                        {
                            "name": column["name"],
                            "type": column.get("type", ""),
                            "nullable": not column.get("notNull", False),
                            "primaryKey": bool(column.get("primaryKeyPosition", 0)),
                        }
                        for column in (asset.metadata or {}).get("columns", [])
                    ],
                    "definition": (asset.metadata or {}).get("definition"),
                }
                for asset in scanned.assets
            ]
            result.update(
                status="connected",
                assetCount=len(tables),
                assets=tables[:20],
                details={
                    "tables": tables,
                    "mode": "read-only schema metadata",
                    "connector": "SQLiteSchemaConnector",
                },
                message="SQLite schema metadata read in read-only mode; table rows were not queried",
            )
            return result
        except (SourceConnectorError, OSError, ValueError) as exc:
            result["message"] = f"SQLite metadata read failed: {type(exc).__name__}"
            return result
    if source["type"] in {"postgresql", "mysql"}:
        try:
            registry = build_source_connector_registry(ROOT, source=source)
            scanned = registry.scan(source["type"], source["id"], str(source.get("connectionEnv", "")))
            tables = [{"name": asset.name, "kind": asset.kind, "path": asset.locator,
                       "schema": (asset.metadata or {}).get("schema"),
                       "columns": (asset.metadata or {}).get("columns", []), "assetId": asset.asset_id}
                      for asset in scanned.assets]
            result.update(status=scanned.status, assetCount=len(tables), assets=tables[:30],
                details={"tables": tables, "connector": "PostgreSQLSchemaConnector" if source["type"] == "postgresql" else "MySQLSchemaConnector",
                         "mode": "read-only information_schema metadata", "warnings": list(scanned.warnings)},
                message="Database schema metadata read in read-only mode; business rows were not queried")
            return result
        except (SourceConnectorError, OSError, ValueError) as exc:
            result.update(status="error", message=f"Database schema scan failed: {type(exc).__name__}")
            return result
    if source["type"] not in {"repository", "documents"}:
        result["message"] = f"Unsupported local source type: {source['type']}"
        return result
    try:
        scanned = build_source_connector_registry(base.parent).scan(source["type"], source["id"], base)
        assets = [
            {
                "path": asset.locator,
                "kind": (asset.metadata or {}).get("suffix", "").lstrip("."),
                "bytes": asset.size_bytes,
                "sha256": asset.content_sha256,
                "assetId": asset.asset_id,
            }
            for asset in scanned.assets[:30]
        ]
        result.update(
            status="connected",
            assetCount=len(scanned.assets),
            assets=assets,
            details={
                "git": git_metadata(base) if source["type"] == "repository" else None,
                "scannedExtensions": sorted({(asset.metadata or {}).get("suffix", "") for asset in scanned.assets}),
                "connector": "LocalDirectoryConnector",
                "scanStatus": scanned.status,
                "warnings": list(scanned.warnings),
                "truncatedAt": 600 if scanned.status == "partial" else None,
            },
            message="Read-only local metadata scan completed through SourceConnector",
        )
        return result
    except (SourceConnectorError, OSError, ValueError) as exc:
        result["message"] = f"Local source scan failed: {type(exc).__name__}"
        return result


def _source_error_class(result: dict) -> str | None:
    status = result.get("status")
    if status in {"connected", "partial"}: return None
    if status == "disabled": return "disabled"
    if status == "not-synced": return "not-synced"
    if status == "invalid-url": return "configuration"
    message = str(result.get("message", "")).lower()
    if "timeout" in message or "timed out" in message: return "timeout"
    if "tls" in message or "ssl" in message or "certificate" in message: return "tls-or-certificate"
    if "host" in message or "allow" in message: return "host-policy"
    if status == "unavailable": return "provider-unavailable"
    return "connector-error"


def source_scan_results(*, force: bool = False, allow_remote: bool = False) -> list[dict]:
    """Return recent scan metadata. Remote HTTP requests run only after explicit sync/discovery actions."""
    state = state_read()
    cache = state.get("sourceScans", {})
    histories = state.get("sourceSyncHistory", {})
    out = []
    updated_cache = dict(cache)
    updated_histories = dict(histories)
    for source in source_configs():
        cached = cache.get(source["id"])
        cache_fresh = False
        if cached and not force:
            try:
                parsed = datetime.fromisoformat(cached.get("lastSyncAt", "").replace("Z", "+00:00"))
                cache_fresh = (datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)).total_seconds() < 90
            except (ValueError, TypeError):
                cache_fresh = False
        if cache_fresh:
            result = dict(cached)
        elif source.get("type") in {"github", "gitlab", "postgresql", "mysql"} and not allow_remote:
            result = cached or {"id": source["id"], "name": source["name"], "type": source["type"], "pathLabel": source.get("url", source.get("connectionEnv", "")), "enabled": source.get("enabled", True), "fixture": False, "lastSyncAt": None, "status": "not-synced", "assetCount": 0, "assets": [], "details": {}, "message": "Remote repository/database is not queried by background refresh; use explicit Sync to fetch metadata"}
        else:
            started = time.monotonic()
            result = scan_source(source, allow_remote=allow_remote)
            duration_ms = round((time.monotonic() - started) * 1000, 1)
            result["scanDurationMs"] = duration_ms
            history = list(histories.get(source["id"], []))
            history.append({
                "syncId": "sync-" + uuid.uuid4().hex[:10],
                "sourceId": source["id"],
                "at": result.get("lastSyncAt") or now_iso(),
                "durationMs": duration_ms,
                "status": result.get("status", "unknown"),
                "assetCount": int(result.get("assetCount", 0) or 0),
                "errorClass": _source_error_class(result),
            })
            updated_histories[source["id"]] = history[-20:]
            result["syncHistory"] = updated_histories[source["id"]][-5:]
            updated_cache[source["id"]] = result
        result.setdefault("syncHistory", updated_histories.get(source["id"], [])[-5:])
        if result.get("syncHistory"):
            latest = result["syncHistory"][-1]
            result.setdefault("lastSyncDurationMs", latest.get("durationMs"))
            result.setdefault("lastErrorClass", latest.get("errorClass"))
        out.append(result)
    if updated_cache != cache or updated_histories != histories:
        def save(st):
            st["sourceScans"] = updated_cache
            st["sourceSyncHistory"] = updated_histories
        state_update(save)
    return out


def load_ontology() -> dict:
    data = load_json(FORMAL_ONTOLOGY, {})
    classes = []
    for item in data.get("classes", []):
        classes.append({"id": item["name"], "name": item["name"], "description": item.get("description", ""), "type": "core"})
    for item in data.get("operationalExtensions", {}).get("classes", []):
        classes.append({"id": item["name"], "name": item["name"], "description": item.get("description", ""), "type": "operational"})
    edges = []
    for rel in data.get("relations", []):
        targets = rel.get("target", [])
        if isinstance(targets, str):
            targets = [targets]
        for target in targets:
            edges.append({"id": f'{rel.get("name")}:{target}', "name": rel.get("name"), "source": rel.get("source"), "target": target, "field": rel.get("field"), "cardinality": rel.get("cardinality"), "validation": rel.get("validation")})
    for rel in data.get("operationalExtensions", {}).get("relations", []):
        targets = rel.get("target", [])
        if isinstance(targets, str): targets = [targets]
        for target in targets:
            edges.append({"id": f'{rel.get("name")}:{target}', "name": rel.get("name"), "source": rel.get("source"), "target": target, "field": rel.get("field"), "cardinality": rel.get("cardinality"), "validation": rel.get("validation")})
    return {"ontologyId": data.get("ontologyId", "software-factory-core"), "ontologyVersion": data.get("ontologyVersion", "unknown"), "title": data.get("title", "Software Factory Ontology"), "schemaVersion": data.get("schemaVersion"), "classes": classes, "relations": edges, "formalPath": "ontology/software-factory-ontology.json", "warning": "正式本体来自当前仓库文件；候选审批不会自动改写该文件。"}


def state_read() -> dict:
    return ensure_state()


def state_update(mutator):
    with STATE_LOCK:
        state = ensure_state()
        mutator(state)
        dump(STATE_PATH, state)
        return state


def record_event(event_type: str, summary: str, payload: dict | None = None, *, actor: str = "local-operator") -> dict:
    event = {"eventId": f"evt-{uuid.uuid4().hex[:12]}", "at": now_iso(), "type": event_type, "actor": actor, "summary": summary, "payload": payload or {}}
    def change(state):
        state.setdefault("portalEvents", []).append(event)
        state["portalEvents"] = state["portalEvents"][-1500:]
    state_update(change)
    return event


def safe_extract_source_terms(scan: dict) -> list[dict]:
    """Extract a small, deterministic candidate term set; no document bodies are returned to UI."""
    terms: dict[str, dict] = {}
    source_cfg = next((s for s in source_configs() if s["id"] == scan["id"]), {"path": "."})
    scan_details = scan.get("details", {}) if isinstance(scan.get("details"), dict) else {}
    def evidence_record(path: str, kind: str, asset: dict) -> dict:
        return {
            "sourceId": scan["id"],
            "sourceName": source_cfg.get("name"),
            "sourceType": source_cfg.get("type"),
            "provider": scan_details.get("provider"),
            "path": path,
            "kind": kind,
            "assetId": asset.get("assetId"),
            "contentSha256": asset.get("sha256"),
            "sourceRevision": asset.get("sourceRevision") or scan_details.get("sourceRevision"),
            "assetFingerprint": hashlib.sha256(json.dumps({
                "path": path, "kind": kind, "name": asset.get("name"),
                "schema": asset.get("schema"), "columns": asset.get("columns", []),
            }, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()
                if source_cfg.get("type") in {"sqlite", "postgresql", "mysql"} else None,
            "scannedAt": scan.get("lastSyncAt"),
            "browseUrl": asset.get("browseUrl") or (
                remote_asset_browse_url(source_cfg, path, scan_details.get("defaultBranch"))
                if source_cfg.get("type") in {"github", "gitlab"} else None
            ),
        }
    for asset in scan.get("assets", []):
        if source_cfg.get("type") in {"sqlite", "postgresql", "mysql"}:
            table_name = str(asset.get("name", "")).strip()
            if table_name:
                labels = [(table_name, "sql-table")]
                labels.extend(
                    (str(column.get("name", "")).strip(), "sql-column")
                    for column in asset.get("columns", [])
                    if isinstance(column, dict)
                )
                for label, kind in labels:
                    if len(label) < 3 or len(label) > 90:
                        continue
                    key = label.lower()
                    evidence = evidence_record(asset.get("path", f"sqlite:{table_name}"), kind, asset)
                    if key in terms:
                        if evidence not in terms[key]["evidence"]:
                            terms[key]["evidence"].append(evidence)
                    else:
                        terms[key] = {
                            "termId": "term-" + re.sub(r"[^a-z0-9]+", "-", key).strip("-")[:50] + "-" + uuid.uuid5(uuid.NAMESPACE_URL, key).hex[:6],
                            "label": label,
                            "kind": kind,
                            "evidence": [evidence],
                            "proposedType": "CandidateConcept",
                            "confidence": 0.5,
                            "status": "candidate",
                        }
            continue
        rel = asset.get("path", "")
        if source_cfg.get("type") in {"github", "gitlab"}:
            stem = Path(rel).stem
            for label in re.split(r"[_-]+|(?<=[a-z])(?=[A-Z])", stem):
                label = label.strip()
                if len(label) >= 3 and label.lower() not in {"index", "main", "init", "test", "spec", "readme"}:
                    key = label.lower()
                    evidence = evidence_record(rel, "remote-file-path", asset)
                    if key in terms:
                        if evidence not in terms[key]["evidence"]: terms[key]["evidence"].append(evidence)
                    else:
                        terms[key] = {"termId": "term-" + re.sub(r"[^a-z0-9]+", "-", key).strip("-")[:50] + "-" + uuid.uuid5(uuid.NAMESPACE_URL, key).hex[:6], "label": label, "kind": "remote-file-path", "evidence": [evidence], "proposedType": "CandidateConcept", "confidence": 0.35, "status": "candidate"}
            continue
        p = source_path(source_cfg) / rel
        suffix = p.suffix.lower()
        found: list[tuple[str, str]] = []
        try:
            if suffix not in {".py", ".md", ".rst", ".json", ".sql", ".yaml", ".yml", ".toml"} or not p.is_file() or p.stat().st_size > 400_000:
                continue
            text = p.read_text(encoding="utf-8", errors="ignore")[:250_000]
            if suffix in {".md", ".rst"}:
                found = [(m.group(1).strip(), "heading") for m in re.finditer(r"(?m)^#{1,4}\s+(.{3,90})$", text)]
            elif suffix == ".py":
                found = [(m.group(1), "python-symbol") for m in re.finditer(r"(?m)^\s*(?:class|def|async def)\s+([A-Za-z][A-Za-z0-9_]{2,60})", text)]
            elif suffix == ".sql":
                found = [(m.group(1), "sql-symbol") for m in re.finditer(r"(?i)\b(?:CREATE\s+TABLE|CREATE\s+VIEW)\s+(?:IF\s+NOT\s+EXISTS\s+)?[\"`]?([A-Za-z_][\w]*)", text)]
            elif suffix == ".json":
                found = [(m.group(1), "json-key") for m in re.finditer(r'"([A-Za-z][A-Za-z0-9_-]{2,50})"\s*:', text)]
            for label, kind in found:
                label = re.sub(r"\s+", " ", label).strip(" .:-")
                if len(label) < 3 or len(label) > 90 or label.lower() in {"true", "false", "null", "required", "properties", "description", "example"}:
                    continue
                key = label.lower()
                existing = terms.get(key)
                evidence = evidence_record(rel, kind, asset)
                if existing:
                    if evidence not in existing["evidence"]: existing["evidence"].append(evidence)
                else:
                    terms[key] = {"termId": "term-" + re.sub(r"[^a-z0-9]+", "-", key).strip("-")[:50] + "-" + uuid.uuid5(uuid.NAMESPACE_URL, key).hex[:6], "label": label, "kind": kind, "evidence": [evidence], "proposedType": "CandidateConcept", "confidence": 0.55, "status": "candidate"}
        except OSError:
            continue
    return sorted(terms.values(), key=lambda x: (-len(x["evidence"]), x["label"].lower()))[:160]


def assess_evidence_validity(evidence: dict, source_map: dict, scan_map: dict) -> dict:
    """Compare a stored evidence locator with the latest available source inventory."""
    source_id = str(evidence.get("sourceId", ""))
    source = source_map.get(source_id)
    if not source:
        return {"status": "source-removed", "reason": "Source is no longer registered"}
    scan = scan_map.get(source_id)
    if not scan or scan.get("status") == "not-synced":
        return {"status": "not-yet-checked", "reason": "No current source scan is available"}
    scan_status = scan.get("status")
    if scan_status not in {"connected", "partial"}:
        return {"status": "source-unavailable", "reason": str(scan.get("message") or scan_status)}
    path = evidence.get("path")
    asset = next((item for item in scan.get("assets", []) if item.get("path") == path), None)
    if asset is None and evidence.get("assetId"):
        asset = next((item for item in scan.get("assets", []) if item.get("assetId") == evidence.get("assetId")), None)
    if asset is None:
        if scan_status == "partial":
            return {"status": "inconclusive-partial-scan", "reason": "The latest inventory is truncated; absence is not proof of deletion"}
        return {"status": "asset-missing", "reason": "The source scan completed but this asset was not found"}
    old_hash = evidence.get("contentSha256")
    new_hash = asset.get("sha256")
    if old_hash:
        if not new_hash:
            return {"status": "unverifiable", "reason": "Current scan did not provide a content hash"}
        if old_hash != new_hash:
            return {"status": "content-changed", "reason": "The local source content hash changed"}
        return {"status": "current", "reason": "The local source content hash matches"}
    old_fingerprint = evidence.get("assetFingerprint")
    if old_fingerprint:
        current_fingerprint = hashlib.sha256(json.dumps({
            "path": path, "kind": evidence.get("kind"), "name": asset.get("name"),
            "schema": asset.get("schema"), "columns": asset.get("columns", []),
        }, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()
        if old_fingerprint != current_fingerprint:
            return {"status": "schema-changed", "reason": "The table or column metadata changed"}
        return {"status": "current", "reason": "The schema metadata fingerprint matches"}
    if source.get("type") in {"github", "gitlab"}:
        old_revision = evidence.get("sourceRevision")
        current_revision = scan.get("details", {}).get("sourceRevision")
        if old_revision and current_revision and old_revision != current_revision:
            return {"status": "revision-changed-review", "reason": "Repository tree revision changed; file-level content is not fetched"}
        if old_revision and current_revision:
            return {"status": "current", "reason": "Repository tree revision matches"}
        return {"status": "unverifiable", "reason": "The provider did not expose a comparable revision"}
    return {"status": "present-unverified", "reason": "The asset locator exists, but no comparable fingerprint is available"}


def annotate_candidate_evidence(candidate: dict, source_map: dict, scan_map: dict) -> dict:
    """Return a UI-safe candidate copy with dynamic evidence validity annotations."""
    result = json.loads(json.dumps(candidate))
    counts = {}
    for term in result.get("terms", []):
        for evidence in term.get("evidence", []):
            validity = assess_evidence_validity(evidence, source_map, scan_map)
            evidence["validity"] = validity
            counts[validity["status"]] = counts.get(validity["status"], 0) + 1
    result["evidenceValidity"] = counts
    result["evidenceCheckedAt"] = now_iso()
    result["affectedTermCount"] = sum(
        1 for term in result.get("terms", [])
        if any((e.get("validity") or {}).get("status") not in {"current", "present-unverified"}
               for e in term.get("evidence", []))
    )
    return result


def discover_candidates() -> dict:
    scans = source_scan_results(force=True, allow_remote=True)
    terms = []
    for scan in scans:
        terms.extend(safe_extract_source_terms(scan))
    ontology = load_ontology()
    formal_names = {x["name"].lower() for x in ontology["classes"]}
    unique = {}
    for term in terms:
        key = re.sub(r"[_-]+", " ", term["label"]).lower()
        if key not in formal_names:
            unique.setdefault(term["label"].lower(), term)
    candidate = {"candidateId": "ocand-" + uuid.uuid4().hex[:12], "createdAt": now_iso(), "engine": "local-rule-based-extraction", "sourceMode": "local-read-only-metadata-and-symbols", "formalOntologyVersion": ontology["ontologyVersion"], "status": "needs-review", "terms": list(unique.values()), "sourceSummary": [{"id": x["id"], "name": x["name"], "type": x["type"], "status": x["status"], "assetCount": x["assetCount"], "fixture": x.get("fixture", False)} for x in scans], "notice": "本候选由本地规则抽取生成，不是 LLM 结果；它不会自动合并到正式本体。请先核实来源和语义。"}
    def change(state):
        state.setdefault("ontologyCandidates", []).insert(0, candidate)
        state["ontologyCandidates"] = state["ontologyCandidates"][:30]
    state_update(change)
    record_event("ontology.candidate.created", f"本体候选 {candidate['candidateId']} 已生成", {"candidateId": candidate["candidateId"], "termCount": len(candidate["terms"])})
    return candidate


def roles_and_stages() -> tuple[list[dict], list[dict]]:
    team = load_json(ROOT / "agents/teams/software-factory-mvp.json", {})
    wf = load_json(ROOT / "workflows/definitions/agent-proposal-v1.json", {})
    roles = team.get("registeredRoles", [])
    stages = wf.get("steps", [])
    return roles, stages


def create_agent_run(title: str = "软件需求到交付候选 · 离线演示") -> dict:
    agents = [
        ("requirement-analyst", "需求分析", "整理目标、范围与验收条件"),
        ("solution-architect", "架构设计", "选择组件并提出架构候选"),
        ("implementation-agent", "实现提案", "生成受控的实现/配置候选"),
        ("test-agent", "测试验证", "检查验收条件并关联测试证据"),
        ("security-reviewer", "安全审查", "检查风险、权限边界和扫描证据")
    ]
    run_id = "agent-run-" + uuid.uuid4().hex[:10]
    steps = [{"id": aid, "name": name, "description": desc, "status": "queued", "startedAt": None, "finishedAt": None, "outputSummary": None, "evidence": []} for aid, name, desc in agents]
    steps[0]["status"] = "running"
    steps[0]["startedAt"] = now_iso()
    run = {"runId": run_id, "title": title[:160], "createdAt": now_iso(), "updatedAt": now_iso(), "status": "running", "runtimeMode": "deterministic-fixture", "currentStep": 0, "steps": steps, "revision": 1, "note": "离线编排演示：状态和输出摘要由确定性演示处理器生成，不调用真实 LLM。"}
    def change(state):
        state.setdefault("agentRuns", []).insert(0, run)
        state["agentRuns"] = state["agentRuns"][:50]
    state_update(change)
    record_event("agent.run.created", f"多智能体离线演示已启动：{run_id}", {"runId": run_id, "runtimeMode": run["runtimeMode"]})
    return run


def advance_agent_run(run_id: str) -> dict:
    result = {"run": None}
    def change(state):
        run = next((r for r in state.get("agentRuns", []) if r["runId"] == run_id), None)
        if run is None: raise KeyError("Agent run not found")
        if run["status"] not in {"running", "waiting_approval"}: raise ValueError("Agent run is not advanceable")
        idx = int(run.get("currentStep", 0))
        if idx >= len(run["steps"]): raise ValueError("No current step")
        step = run["steps"][idx]
        if step["status"] == "running":
            step["status"] = "succeeded"
            step["finishedAt"] = now_iso()
            step["outputSummary"] = f"{step['name']} 完成：已生成结构化演示产物并记录状态事件。"
            step["evidence"] = [{"kind": "step-summary", "uri": f"portal://{run_id}/{step['id']}", "verified": True}]
            if idx + 1 < len(run["steps"]):
                run["currentStep"] = idx + 1
                next_step = run["steps"][idx + 1]
                next_step["status"] = "running"
                next_step["startedAt"] = now_iso()
            else:
                run["status"] = "waiting_approval"
        run["updatedAt"] = now_iso()
        run["revision"] += 1
        result["run"] = run
    state_update(change)
    run = result["run"]
    record_event("agent.step.advanced", f"多智能体运行更新：{run_id} → {run['status']}", {"runId": run_id, "currentStep": run.get("currentStep")})
    return run


def decide_agent_run(run_id: str, approve: bool, approver: str, reason: str) -> dict:
    if not approver.strip() or not reason.strip(): raise ValueError("审批人和原因不能为空")
    result = {"run": None}
    def change(state):
        run = next((r for r in state.get("agentRuns", []) if r["runId"] == run_id), None)
        if run is None: raise KeyError("Agent run not found")
        if run["status"] != "waiting_approval": raise ValueError("Run is not waiting for approval")
        run["status"] = "succeeded" if approve else "rejected"
        run["approval"] = {"approved": approve, "approver": approver.strip()[:100], "reason": reason.strip()[:500], "at": now_iso()}
        run["updatedAt"] = now_iso(); run["revision"] += 1
        result["run"] = run
    state_update(change)
    record_event("agent.run.approved" if approve else "agent.run.rejected", f"{run_id} 已{'批准' if approve else '驳回'}", {"runId": run_id, "approver": approver.strip()})
    return result["run"]


VALIDATOR_SCRIPTS = [
    "validate_architecture_baseline.py", "check_mvp_scope.py", "validate_domain_model.py", "validate_asset_catalog.py",
    "validate_agent_contracts.py", "validate_multi_agent_architecture.py", "validate_workflow_definition.py",
    "validate_agent_workflow_definition.py", "validate_ontology_discovery_config.py", "validate_ontology_discovery_workflow.py"
]


def available_scanners() -> list[dict]:
    return [{"id": name, "installed": shutil.which(name) is not None, "path": shutil.which(name), "scope": scope} for name, scope in [
        ("semgrep", "代码静态分析"), ("gitleaks", "密钥泄漏扫描"), ("trivy", "依赖/镜像/配置扫描")]]


def scanner_report_status(name: str, report: object) -> tuple[str, int]:
    """Return clean/findings/incomplete from a scanner's machine-readable report."""
    if name == "semgrep":
        if not isinstance(report, dict) or not isinstance(report.get("results"), list):
            return "incomplete", 0
        if report.get("errors"):
            return "incomplete", 0
        return ("findings" if report["results"] else "clean", len(report["results"]))
    if name == "gitleaks":
        if not isinstance(report, list):
            return "incomplete", 0
        return ("findings" if report else "clean", len(report))
    if name == "trivy":
        if not isinstance(report, dict) or not isinstance(report.get("Results"), list):
            return "incomplete", 0
        count = 0
        for result in report["Results"]:
            if not isinstance(result, dict):
                return "incomplete", 0
            for key in ("Vulnerabilities", "Misconfigurations", "Secrets"):
                entries = result.get(key) or []
                if not isinstance(entries, list):
                    return "incomplete", 0
                count += len(entries)
        return ("findings" if count else "clean", count)
    return "incomplete", 0


def run_quality(checks: list[str]) -> dict:
    run_id = "quality-" + uuid.uuid4().hex[:10]
    results = []
    for check in checks:
        if check == "validate":
            for script in VALIDATOR_SCRIPTS:
                start = time.monotonic()
                try:
                    proc = subprocess.run([sys.executable, str(ROOT / "scripts" / script)], cwd=ROOT, capture_output=True, text=True, timeout=45)
                    results.append({"id": script, "kind": "local-validation", "status": "passed" if proc.returncode == 0 else "failed", "exitCode": proc.returncode, "durationSeconds": round(time.monotonic()-start, 3), "summary": ((proc.stdout or proc.stderr).strip()[-1800:])})
                except subprocess.TimeoutExpired:
                    results.append({"id": script, "kind": "local-validation", "status": "timeout", "exitCode": None, "durationSeconds": round(time.monotonic()-start, 3), "summary": "Validator timed out"})
        elif check == "tests":
            start = time.monotonic()
            try:
                proc = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"], cwd=ROOT, capture_output=True, text=True, timeout=300)
                output = (proc.stdout + "\n" + proc.stderr).strip()
                tail = output[-5000:]
                match = re.search(r"Ran (\d+) tests? in ([\d.]+)s", output)
                results.append({"id": "unittest-suite", "kind": "tests", "status": "passed" if proc.returncode == 0 else "failed", "exitCode": proc.returncode, "durationSeconds": round(time.monotonic()-start, 3), "testCount": int(match.group(1)) if match else None, "summary": tail})
            except subprocess.TimeoutExpired:
                results.append({"id": "unittest-suite", "kind": "tests", "status": "timeout", "exitCode": None, "durationSeconds": round(time.monotonic()-start, 3), "summary": "Tests timed out after 300 seconds"})
        elif check.startswith("scanner:"):
            name = check.split(":", 1)[1]
            if name not in {"semgrep", "gitleaks", "trivy"}:
                results.append({"id": name, "kind": "security-scan", "status": "rejected", "summary": "Unknown scanner"}); continue
            binary = shutil.which(name)
            if not binary:
                results.append({"id": name, "kind": "security-scan", "status": "not-installed", "summary": f"{name} 未安装；未执行扫描，不能将此状态视为通过。"}); continue
            report_dir = STATE_DIR / "scans" / run_id
            report_dir.mkdir(parents=True, exist_ok=True)
            report_path = report_dir / f"{name}.json"
            if name == "semgrep": command = [binary, "scan", "--config", "p/default", "--json", "--output", str(report_path), str(ROOT)]
            elif name == "trivy": command = [binary, "fs", "--format", "json", "--output", str(report_path), "--scanners", "vuln,misconfig,secret", "--skip-dirs", ".git,.venv,node_modules,.local-runs,deliverables", str(ROOT)]
            else: command = [binary, "detect", "--source", str(ROOT), "--no-git", "--report-format", "json", "--report-path", str(report_path)]
            start = time.monotonic()
            try:
                proc = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=180)
                # Keep a bounded console excerpt; scanner output may contain source snippets.
                summary = (proc.stderr or proc.stdout or "").strip()[-1200:]
                report_state, finding_count = ("incomplete", 0)
                if report_path.is_file():
                    try:
                        parsed_report = json.loads(report_path.read_text(encoding="utf-8"))
                        report_state, finding_count = scanner_report_status(name, parsed_report)
                    except (OSError, json.JSONDecodeError):
                        report_state = "incomplete"
                if proc.returncode != 0:
                    scan_status = "findings" if report_state == "findings" else "findings-or-error"
                elif report_state == "findings":
                    scan_status = "findings"
                elif report_state == "clean":
                    scan_status = "completed"
                else:
                    scan_status = "incomplete"
                try:
                    report_path_label = str(report_path.relative_to(ROOT)) if report_path.exists() else None
                except ValueError:
                    # Tests and custom deployments may place the state directory outside the repo.
                    report_path_label = None
                results.append({"id": name, "kind": "security-scan", "status": scan_status, "exitCode": proc.returncode, "durationSeconds": round(time.monotonic()-start, 3), "reportPath": report_path_label, "reportPresent": report_path.exists(), "reportParsed": report_state != "incomplete", "findingCount": finding_count, "summary": summary or "Scanner completed; machine-readable report was evaluated."})
            except subprocess.TimeoutExpired:
                results.append({"id": name, "kind": "security-scan", "status": "timeout", "exitCode": None, "durationSeconds": round(time.monotonic()-start, 3), "summary": "Scanner timed out"})
    passed = sum(1 for r in results if r["status"] == "passed")
    failed = sum(1 for r in results if r["status"] in {"failed", "timeout", "findings-or-error", "findings"})
    incomplete = sum(1 for r in results if r["status"] in {"not-installed", "incomplete", "rejected"})
    overall_status = "failed" if failed else ("incomplete" if incomplete or not results else "passed")
    report = {"runId": run_id, "createdAt": now_iso(), "status": overall_status, "passed": passed, "failedOrNeedsReview": failed, "incomplete": incomplete, "results": results, "scanners": available_scanners(), "note": "Security scans pass only when the report is present, parseable, and contains zero findings; missing or malformed reports block release."}
    def change(state):
        state.setdefault("qualityRuns", []).insert(0, report)
        state["qualityRuns"] = state["qualityRuns"][:30]
    state_update(change)
    record_event("quality.run.completed", f"质量运行 {run_id} 状态：{report['status']}", {"runId": run_id, "status": report["status"], "resultCount": len(results)})
    return report


def list_releases() -> list[dict]:
    base = ROOT / "deliverables"
    items = []
    if not base.is_dir(): return items
    for record_path in sorted(base.glob("*.release-record.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:50]:
        record = load_json(record_path, {})
        manifest = load_json(Path(record.get("manifestPath", "")), {}) if record.get("manifestPath") else {}
        items.append({**record, "createdAt": manifest.get("createdAt"), "bundleType": manifest.get("bundleType", "unknown"), "tenantId": manifest.get("tenantId"), "targetProfile": manifest.get("targetProfile"), "fileCount": len(manifest.get("files", [])), "manifest": manifest})
    return items


def create_release_candidate() -> dict:
    run_id = "portal-delivery-" + datetime.now().strftime("%Y%m%d%H%M%S") + "-" + uuid.uuid4().hex[:4]
    command = [sys.executable, str(ROOT / "scripts" / "run_e2e_delivery.py"), "--request", "examples/requests/kafka-development.json", "--runs-root", ".local-runs", "--deliverables", "deliverables", "--run-id", run_id]
    try:
        proc = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=150)
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError("端到端交付流水线运行超时") from exc
    output = (proc.stdout or "").strip()
    try: result = json.loads(output)
    except json.JSONDecodeError:
        raise RuntimeError("交付流水线没有返回有效 JSON：" + (proc.stderr or output)[-1000:])
    record = {"runId": run_id, "processExitCode": proc.returncode, "pipeline": result, "createdAt": now_iso()}
    record_event("release.candidate.created" if result.get("release") else "release.candidate.blocked", f"发布候选 {run_id} 状态：{result.get('status')}", {"runId": run_id, "status": result.get("status"), "releaseId": (result.get("release") or {}).get("releaseId")})
    return record


def get_overview() -> dict:
    state = state_read()
    sources = source_scan_results()
    runs = state.get("agentRuns", [])
    quality = state.get("qualityRuns", [])
    releases = list_releases()
    return {"generatedAt": now_iso(), "mode": "local-reference-portal", "sources": {"total": len(sources), "connected": sum(1 for s in sources if s["status"] == "connected"), "items": sources}, "ontology": {"classes": len(load_ontology()["classes"]), "relations": len(load_ontology()["relations"]), "candidates": len(state.get("ontologyCandidates", [])), "pendingChanges": sum(1 for c in state.get("ontologyChanges", []) if c.get("status") == "pending")}, "agents": {"runs": len(runs), "active": sum(1 for r in runs if r.get("status") in {"running", "waiting_approval"}), "latest": runs[:5]}, "quality": {"runs": len(quality), "latest": quality[0] if quality else None, "scanners": available_scanners()}, "releases": {"count": len(releases), "candidates": sum(1 for r in releases if r.get("status") == "candidate"), "items": releases[:5]}, "events": state.get("portalEvents", [])[-12:], "limitations": ["本地单用户参考门户；默认无身份认证", "本体发现使用本地确定性符号/标题抽取，不等同于 LLM 本体学习", "多智能体演示默认 deterministic fixture runtime；真实 LLM 入口仍在既有 Agent Runtime 控制台", "正式发布仅生成配置交付候选，实际部署不执行"]}


class PortalHandler(BaseHTTPRequestHandler):
    server_version = "SoftwareFactoryPortal/0.1"
    static_file = APP

    def log_message(self, fmt, *args):
        # Keep local console logs minimal and avoid logging request bodies.
        super().log_message(fmt, *args)

    def _send_json(self, status: int, value) -> None:
        body = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length < 1 or length > 80_000: raise ValueError("Request body is empty or too large")
        data = json.loads(self.rfile.read(length).decode("utf-8"))
        if not isinstance(data, dict): raise ValueError("Request body must be a JSON object")
        return data

    def _same_origin(self) -> bool:
        origin = self.headers.get("Origin")
        if not origin: return True
        host = self.headers.get("Host", "")
        return origin in {f"http://{host}", f"https://{host}"}

    def do_GET(self):  # noqa: N802
        path = urlparse(self.path).path
        if path in {"/", "/index.html"}:
            data = self.static_file.read_bytes()
            self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8"); self.send_header("Content-Length", str(len(data))); self.send_header("Cache-Control", "no-store"); self.end_headers(); self.wfile.write(data); return
        if path == "/api/health": return self._send_json(200, {"status": "ok", "mode": "local-reference-portal", "timestamp": now_iso()})
        if path == "/api/overview": return self._send_json(200, get_overview())
        if path == "/api/sources": return self._send_json(200, {"sources": source_scan_results()})
        if path == "/api/ontology":
            state = state_read()
            sources = source_configs()
            scans = source_scan_results()
            source_map = {item["id"]: item for item in sources}
            scan_map = {item["id"]: item for item in scans}
            candidates = [annotate_candidate_evidence(item, source_map, scan_map)
                          for item in state.get("ontologyCandidates", [])]
            return self._send_json(200, {"formal": load_ontology(), "candidates": candidates, "changes": state.get("ontologyChanges", [])})
        if path == "/api/agents": return self._send_json(200, {"runs": state_read().get("agentRuns", []), "roles": roles_and_stages()[0], "realRuntimeUrl": "http://127.0.0.1:8769"})
        if path == "/api/quality": return self._send_json(200, {"runs": state_read().get("qualityRuns", []), "scanners": available_scanners(), "policy": load_json(ROOT / "policies/quality/quality-gate-policy.json", {})})
        if path == "/api/releases": return self._send_json(200, {"releases": list_releases(), "approvals": state_read().get("releaseApprovals", [])})
        if path == "/api/events": return self._send_json(200, {"events": state_read().get("portalEvents", [])[-200:]})
        return self._send_json(404, {"error": "Not found"})

    def do_POST(self):  # noqa: N802
        path = urlparse(self.path).path
        if not self._same_origin(): return self._send_json(403, {"error": "Cross-origin request rejected"})
        try:
            body = self._body()
            if path == "/api/sources":
                source_type = body.get("type")
                if source_type not in {"repository", "documents", "sqlite", "github", "gitlab", "postgresql", "mysql"}: raise ValueError("unsupported source type")
                name = str(body.get("name", "")).strip(); raw_path = str(body.get("path", "")).strip()
                if not name: raise ValueError("name is required")
                if len(name) > 100 or len(raw_path) > 1000: raise ValueError("name or path too long")
                if source_type in {"postgresql", "mysql"}:
                    connection_env = str(body.get("connectionEnv", raw_path)).strip()
                    if not re.fullmatch(r"[A-Z_][A-Z0-9_]{0,127}", connection_env):
                        raise ValueError("connectionEnv must be an environment variable name, never a DSN value")
                    raw_hosts = body.get("allowedHosts", "")
                    allowed_hosts = [x.strip().lower().rstrip(".") for x in (raw_hosts if isinstance(raw_hosts, list) else str(raw_hosts).split(",")) if str(x).strip()]
                    if not allowed_hosts or any(not re.fullmatch(r"[A-Za-z0-9.-]{1,253}", host) for host in allowed_hosts):
                        raise ValueError("allowedHosts must contain one or more DNS hostnames")
                    source_path_label = "$" + "{" + connection_env + "} · " + ", ".join(allowed_hosts)
                    resolved = None
                elif source_type in {"github", "gitlab"}:
                    parsed = urlparse(raw_path)
                    valid_host = parsed.hostname in ({"github.com", "www.github.com"} if source_type == "github" else {"gitlab.com"})
                    if parsed.scheme != "https" or not valid_host or parsed.username or parsed.password or parsed.query or parsed.fragment:
                        raise ValueError("远端数据源必须是无凭据、无查询参数的 HTTPS GitHub.com/GitLab.com 仓库 URL")
                    segments = [x for x in parsed.path.strip("/").split("/") if x]
                    if (source_type == "github" and len(segments) != 2) or (source_type == "gitlab" and len(segments) < 2):
                        raise ValueError("仓库 URL 路径格式不正确")
                    source_path_label = raw_path
                    resolved = None
                else:
                    candidate_path = Path(raw_path).expanduser()
                    resolved = (ROOT / candidate_path).resolve() if not candidate_path.is_absolute() else candidate_path.resolve()
                    source_path_label = str(resolved)
                if source_type == "sqlite":
                    if not resolved.is_file() or resolved.suffix.lower() not in {".db", ".sqlite", ".sqlite3"}: raise ValueError("SQLite source must be an existing .db/.sqlite/.sqlite3 file")
                    with sqlite3.connect(resolved.as_uri() + "?mode=ro", uri=True, timeout=2) as db: db.execute("PRAGMA query_only=ON"); db.execute("SELECT name FROM sqlite_master LIMIT 1").fetchall()
                elif source_type in {"repository", "documents"}:
                    if not resolved.is_dir(): raise ValueError("Source path must be an existing directory")
                sources = source_configs(); source_id = "source-" + uuid.uuid4().hex[:10]
                source = {"id": source_id, "name": name, "type": source_type, "description": str(body.get("description", "由本地门户添加的只读数据源"))[:300], "enabled": True, "fixture": False}
                if source_type in {"github", "gitlab"}: source["url"] = source_path_label
                elif source_type in {"postgresql", "mysql"}:
                    source["connectionEnv"] = connection_env
                    source["allowedHosts"] = allowed_hosts
                else: source["path"] = source_path_label
                source["tokenEnv"] = "GITHUB_TOKEN" if source_type == "github" else "GITLAB_TOKEN" if source_type == "gitlab" else None
                if source.get("tokenEnv") is None: source.pop("tokenEnv", None)
                sources.append(source); save_sources(sources)
                scan = scan_source(source, allow_remote=True)
                def cache_scan(st): st.setdefault("sourceScans", {})[source_id] = scan
                state_update(cache_scan)
                record_event("source.created", f"新增只读数据源：{name}", {"sourceId": source_id, "type": source_type})
                return self._send_json(201, {"source": scan})
            if path == "/api/sources/sync":
                sources = source_scan_results(force=True, allow_remote=True)
                record_event("source.sync.completed", f"数据源同步完成：{sum(s['status']=='connected' for s in sources)}/{len(sources)} 可连接", {"count": len(sources)})
                return self._send_json(200, {"sources": sources, "completedAt": now_iso()})
            if path == "/api/ontology/discover": return self._send_json(201, {"candidate": discover_candidates()})
            if path == "/api/ontology/changes":
                cid = str(body.get("candidateId", "")); decision = str(body.get("decision", "")); actor = str(body.get("actor", "")).strip(); notes = str(body.get("notes", "")).strip()
                if decision not in {"approve", "reject"}: raise ValueError("decision must be approve or reject")
                if not actor or not notes: raise ValueError("actor and notes are required")
                state = state_read(); candidate = next((c for c in state.get("ontologyCandidates", []) if c["candidateId"] == cid), None)
                if not candidate: raise KeyError("candidate not found")
                change = {"changeId": "ochg-" + uuid.uuid4().hex[:10], "candidateId": cid, "decision": decision, "status": "approved-proposal" if decision == "approve" else "rejected", "actor": actor[:100], "notes": notes[:1000], "createdAt": now_iso(), "termCount": len(candidate.get("terms", [])), "formalOntologyChanged": False, "note": "审批只记录治理决策，不会自动修改正式本体文件。"}
                def mutate(st): st.setdefault("ontologyChanges", []).insert(0, change)
                state_update(mutate); record_event("ontology.change." + decision, f"本体变更提案 {change['changeId']} 已{'批准' if decision=='approve' else '驳回'}", {"candidateId": cid, "changeId": change["changeId"]}, actor=actor)
                return self._send_json(201, {"change": change})
            if path == "/api/agents/start-demo": return self._send_json(201, {"run": create_agent_run(str(body.get("title", "软件需求到交付候选 · 离线演示")))})
            m = re.fullmatch(r"/api/agents/([^/]+)/advance", path)
            if m: return self._send_json(200, {"run": advance_agent_run(unquote(m.group(1)))})
            m = re.fullmatch(r"/api/agents/([^/]+)/decision", path)
            if m:
                run = decide_agent_run(unquote(m.group(1)), bool(body.get("approve")), str(body.get("approver", "")), str(body.get("reason", "")))
                return self._send_json(200, {"run": run})
            if path == "/api/quality/run":
                checks = body.get("checks", ["validate"])
                if not isinstance(checks, list) or not checks or any(not isinstance(x, str) for x in checks): raise ValueError("checks must be a non-empty list")
                allowed = {"validate", "tests", "scanner:semgrep", "scanner:gitleaks", "scanner:trivy"}
                if any(x not in allowed for x in checks): raise ValueError("unsupported quality check")
                return self._send_json(200, {"report": run_quality(checks)})
            if path == "/api/releases/create-candidate":
                result = create_release_candidate(); return self._send_json(201 if result["pipeline"].get("release") else 200, result)
            if path == "/api/releases/approval":
                rid = str(body.get("releaseId", "")); actor = str(body.get("actor", "")).strip(); reason = str(body.get("reason", "")).strip()
                if not actor or not reason: raise ValueError("actor and reason are required")
                known = any(r.get("releaseId") == rid and r.get("status") == "candidate" for r in list_releases())
                if not known: raise ValueError("candidate release not found")
                approval = {"releaseId": rid, "actor": actor[:100], "reason": reason[:500], "decision": "approved-for-rehearsal-only", "createdAt": now_iso(), "deploymentPerformed": False}
                def mutate(st): st.setdefault("releaseApprovals", []).insert(0, approval)
                state_update(mutate); record_event("release.approved-for-rehearsal", f"候选发布 {rid} 已批准用于本地演练", {"releaseId": rid}, actor=actor)
                return self._send_json(201, {"approval": approval})
            if path == "/api/releases/rehearse":
                from ontology_software_factory.release_manager import rehearse_upgrade
                rid = str(body.get("releaseId", "")); actor = str(body.get("actor", "")).strip(); reason = str(body.get("reason", "")).strip(); target = str(body.get("targetEnvironment", "staging-simulation"))
                approved = next((a for a in state_read().get("releaseApprovals", []) if a.get("releaseId") == rid and a.get("decision") == "approved-for-rehearsal-only"), None)
                if not approved: raise ValueError("需要先完成独立审批")
                if actor == approved["actor"]: raise ValueError("演练执行人必须与审批人分离；请使用不同的 actor")
                if not reason: raise ValueError("rehearsal reason is required")
                record_path = (ROOT / "deliverables" / f"{rid}.release-record.json").resolve()
                if ROOT / "deliverables" not in record_path.parents or not record_path.is_file(): raise KeyError("release record not found")
                result = rehearse_upgrade(ROOT / "deliverables" / ".environment-state.json", record_path, approved_by=approved["actor"], approval_reason=approved["reason"], target_environment=target, simulate_health_failure=bool(body.get("simulateHealthFailure", False)))
                record_event("release.rehearsal.completed", f"发布 {rid} 本地演练结果：{result['outcome']}", {"releaseId": rid, "outcome": result["outcome"], "realDeploymentPerformed": False})
                return self._send_json(200, {"rehearsal": result})
            return self._send_json(404, {"error": "API endpoint not found"})
        except KeyError as exc:
            return self._send_json(404, {"error": str(exc).strip("'")})
        except ValueError as exc:
            return self._send_json(400, {"error": str(exc)})
        except TimeoutError as exc:
            return self._send_json(504, {"error": str(exc)})
        except Exception as exc:
            return self._send_json(500, {"error": f"internal error: {type(exc).__name__}: {exc}"})


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the local unified software factory portal")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8770)
    parser.add_argument("--unsafe-expose", action="store_true", help="allow non-loopback binding; not recommended without auth/network controls")
    args = parser.parse_args()
    if args.host not in {"127.0.0.1", "::1", "localhost"} and not args.unsafe_expose:
        parser.error("refusing non-loopback bind; use 127.0.0.1 or explicitly pass --unsafe-expose after adding auth controls")
    ensure_state()
    server = ThreadingHTTPServer((args.host, args.port), PortalHandler)
    print(f"Software Factory Portal: http://127.0.0.1:{args.port}")
    print("Local reference UI only. No authentication; do not expose to a network without adding access controls.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
