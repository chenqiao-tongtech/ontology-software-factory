"""Opt-in live LLM ontology discovery for explicitly selected local source directories."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .llm_provider import OpenAIResponsesProvider
from .observability import JsonlUsageLedger
from .ontology_discovery import (
    OntologyDiscoveryError,
    OntologyDiscoveryPipeline,
    SourceMaterial,
    approve_candidate,
    candidate_digest,
    evaluate_candidate,
    save_candidate,
)

ALLOWED_SOURCE_TYPES = {"repository", "documents"}
ALLOWED_SUFFIXES = {".md", ".rst", ".txt", ".sql", ".json", ".yaml", ".yml", ".toml", ".py", ".proto", ".graphql", ".xml", ".html", ".js", ".ts", ".tsx", ".jsx", ".mmd"}
SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", ".idea", ".vscode", ".local-runs", "dist", "build"}


def collect_local_source_materials(
    source_configs: list[dict[str, Any]],
    source_ids: list[str],
    *,
    root: str | Path,
    max_files_per_source: int = 25,
    max_source_chars: int = 18_000,
    max_total_chars: int = 48_000,
) -> tuple[list[SourceMaterial], dict[str, dict[str, Any]]]:
    """Read only explicitly selected local repository/document directories.

    File boundaries and relative locators are embedded in the material so model citations
    can be checked against the exact submitted text. No source body is returned to callers.
    """
    if not isinstance(source_ids, list) or not source_ids or len(source_ids) > 10:
        raise OntologyDiscoveryError("select between 1 and 10 local source IDs")
    if len(set(source_ids)) != len(source_ids):
        raise OntologyDiscoveryError("source IDs must be unique")
    config_by_id = {str(item.get("id")): item for item in source_configs if isinstance(item, dict)}
    root_path = Path(root).resolve()
    materials: list[SourceMaterial] = []
    asset_index: dict[str, dict[str, Any]] = {}
    total_chars = 0
    for source_id in source_ids:
        source = config_by_id.get(source_id)
        if not source or not source.get("enabled", True):
            raise OntologyDiscoveryError(f"source '{source_id}' is missing or disabled")
        if source.get("type") not in ALLOWED_SOURCE_TYPES:
            raise OntologyDiscoveryError("live LLM discovery currently accepts only local repository/document directories")
        raw_path = Path(str(source.get("path", ""))).expanduser()
        base = (root_path / raw_path).resolve() if not raw_path.is_absolute() else raw_path.resolve()
        if raw_path.is_symlink() or not base.is_dir():
            raise OntologyDiscoveryError(f"source '{source_id}' is not a readable local directory")
        files: list[Path] = []
        for current, dirs, names in os.walk(base, followlinks=False):
            dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not d.startswith("."))
            for name in sorted(names):
                path = Path(current) / name
                if path.is_symlink() or name.startswith(".") or path.suffix.lower() not in ALLOWED_SUFFIXES:
                    continue
                try:
                    if path.stat().st_size > 1_500_000:
                        continue
                except OSError:
                    continue
                files.append(path)
        if not files:
            raise OntologyDiscoveryError(f"source '{source_id}' contains no supported text files")
        if len(files) > max_files_per_source:
            raise OntologyDiscoveryError(
                f"source '{source_id}' contains {len(files)} supported files; narrow the selected directory to at most {max_files_per_source}"
            )
        sections: list[str] = []
        source_chars = 0
        for path in files:
            try:
                raw_content = path.read_bytes()
                text = raw_content.decode("utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                raise OntologyDiscoveryError(f"source file cannot be read as UTF-8 ({type(exc).__name__})") from exc
            relative = path.relative_to(base).as_posix()
            section = f"\n\n===== SOURCE FILE: {relative} =====\n{text}"
            source_chars += len(section)
            if source_chars > max_source_chars:
                raise OntologyDiscoveryError(
                    f"source '{source_id}' exceeds {max_source_chars} characters; narrow the directory or split discovery batches"
                )
            sections.append(section)
            import hashlib
            asset_index[source_id + "::" + relative] = {
                "sourceId": source_id,
                "path": relative,
                "sha256": hashlib.sha256(raw_content).hexdigest(),
                "bytes": len(raw_content),
            }
        total_chars += source_chars
        if total_chars > max_total_chars:
            raise OntologyDiscoveryError(f"selected sources exceed {max_total_chars} total characters")
        materials.append(SourceMaterial(
            source_id=source_id,
            source_type=str(source.get("type")),
            locator=f"source:{source_id}",
            content="".join(sections),
        ))
    return materials, asset_index


def create_live_provider(environ: dict[str, str] | None = None, usage_path: str | Path | None = None):
    env = os.environ if environ is None else environ
    if env.get("FACTORY_ENABLE_LLM_ONTOLOGY_DISCOVERY") != "1":
        raise OntologyDiscoveryError("live LLM discovery is disabled; set FACTORY_ENABLE_LLM_ONTOLOGY_DISCOVERY=1")
    if not env.get("OPENAI_API_KEY"):
        raise OntologyDiscoveryError("OPENAI_API_KEY is required for live LLM discovery")
    ledger = JsonlUsageLedger(usage_path or Path(".local-runs/ontology-candidates/llm-usage.jsonl"))
    providers: dict[str, Any] = {"default": OpenAIResponsesProvider(usage_sink=ledger)}
    for stage, variable in {
        "term-discovery": "ONTOLOGY_TERM_MODEL",
        "relation-discovery": "ONTOLOGY_RELATION_MODEL",
        "constraint-and-competency-questions": "ONTOLOGY_CONSTRAINT_MODEL",
        "independent-critic": "ONTOLOGY_CRITIC_MODEL",
    }.items():
        model = env.get(variable)
        if model:
            providers[stage] = OpenAIResponsesProvider(model=model, usage_sink=ledger)
    return providers


def run_live_ontology_discovery(
    source_configs: list[dict[str, Any]],
    source_ids: list[str],
    *,
    domain: str,
    root: str | Path,
    output_root: str | Path,
    usage_path: str | Path,
    environ: dict[str, str] | None = None,
    provider: Any | None = None,
    benchmark_path: str | Path | None = None,
) -> dict[str, Any]:
    env = os.environ if environ is None else environ
    materials, asset_index = collect_local_source_materials(source_configs, source_ids, root=root)
    selected_provider = provider or create_live_provider(env, usage_path)
    pipeline = OntologyDiscoveryPipeline(selected_provider)
    candidate = pipeline.discover(domain=domain, sources=materials, run_id="portal-llm-discovery")
    output = Path(output_root).resolve()
    target = output / f"{candidate['candidateId']}.json"
    if target.exists():
        existing = json.loads(target.read_text(encoding="utf-8"))
        if candidate_digest(existing) != candidate_digest(candidate):
            raise OntologyDiscoveryError(
                "a candidate with the same source digest already exists but has a different model result; preserve the old artifact and use a new source revision"
            )
        candidate = existing
    else:
        save_candidate(candidate, output)
    evaluation = None
    if benchmark_path and Path(benchmark_path).is_file():
        benchmark = json.loads(Path(benchmark_path).read_text(encoding="utf-8"))
        evaluation = evaluate_candidate(candidate, benchmark)
    return {
        "candidate": candidate,
        "artifactPath": str(target),
        "assetIndex": asset_index,
        "evaluation": evaluation,
    }


def to_portal_candidate(
    result: dict[str, Any],
    source_configs: list[dict[str, Any]],
    source_scans: list[dict[str, Any]],
) -> dict[str, Any]:
    candidate = result["candidate"]
    source_map = {str(item.get("id")): item for item in source_configs}
    scan_map = {str(item.get("id")): item for item in source_scans}
    asset_index = result.get("assetIndex", {})
    terms = []
    for term in candidate.get("terms", []):
        evidence_items = []
        for ref in term.get("sourceRefs", []):
            source_id = str(ref.get("sourceId", ""))
            source = source_map.get(source_id, {})
            locator = str(ref.get("locator", ""))
            asset_locator = locator.split("#", 1)[0]
            indexed = asset_index.get(source_id + "::" + asset_locator, {})
            scan = scan_map.get(source_id, {})
            asset = next((item for item in scan.get("assets", []) if item.get("path") == asset_locator), {})
            evidence_items.append({
                "sourceId": source_id,
                "sourceName": source.get("name", source_id),
                "sourceType": source.get("type"),
                "path": asset_locator,
                "locator": locator,
                "lineAnchor": locator.split("#", 1)[1] if "#" in locator else None,
                "kind": term.get("kind"),
                "assetId": asset.get("assetId"),
                "contentSha256": indexed.get("sha256") or asset.get("sha256"),
                "sourceRevision": asset.get("sourceRevision") or scan.get("details", {}).get("sourceRevision"),
                "scannedAt": scan.get("lastSyncAt") or candidate.get("createdAt"),
                "quote": str(ref.get("quote", ""))[:500],
                "verified": bool(ref.get("verified")),
                "browseUrl": asset.get("browseUrl"),
            })
        terms.append({
            "label": term.get("name"),
            "kind": term.get("kind"),
            "definition": term.get("definition"),
            "aliases": term.get("aliases", []),
            "confidence": term.get("confidence"),
            "evidence": evidence_items,
        })
    return {
        "candidateId": candidate["candidateId"],
        "createdAt": candidate.get("createdAt"),
        "engine": "llm-structured-discovery",
        "sourceMode": "explicit-local-directory-content-submitted-to-configured-LLM",
        "formalOntologyVersion": None,
        "status": "needs-review",
        "terms": terms,
        "relationsCount": len(candidate.get("relations", [])),
        "constraintsCount": len(candidate.get("constraints", [])),
        "criticFindings": candidate.get("criticFindings", []),
        "validation": candidate.get("validation", {}),
        "candidateDigest": candidate.get("candidateDigest"),
        "artifactPath": result.get("artifactPath"),
        "evaluation": result.get("evaluation"),
        "sourceSummary": [{
            "id": source_id,
            "name": source_map.get(source_id, {}).get("name", source_id),
            "type": source_map.get(source_id, {}).get("type"),
            "status": scan_map.get(source_id, {}).get("status", "not-scanned"),
            "assetCount": scan_map.get(source_id, {}).get("assetCount", 0),
            "fixture": False,
        } for source_id in source_map if source_id in {x.get("sourceId") for x in candidate.get("sourceManifest", [])}],
        "notice": "真实 LLM 结构化发现结果；来源正文已发送到配置的模型服务。候选经本地结构/证据校验与 Critic 审查，但仍必须由人类复核，不能自动进入正式本体。",
        "requiresHumanApproval": True,
    }


def approve_llm_candidate_artifact(
    candidate_id: str,
    *,
    candidate_root: str | Path,
    approved_root: str | Path,
    reviewer_id: str,
    approval_ref: str,
    expected_digest: str,
) -> dict[str, Any]:
    """Create a digest-bound approved candidate artifact after human review."""
    import re
    if not re.fullmatch(r"ocand-[a-f0-9]{16}", str(candidate_id)):
        raise OntologyDiscoveryError("candidate ID format is invalid")
    source_root = Path(candidate_root).resolve()
    target = (source_root / f"{candidate_id}.json").resolve()
    if target.parent != source_root or not target.is_file():
        raise OntologyDiscoveryError("candidate artifact is missing")
    try:
        candidate = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise OntologyDiscoveryError("candidate artifact is unreadable") from exc
    actual_digest = candidate_digest(candidate)
    if not expected_digest or actual_digest != expected_digest:
        raise OntologyDiscoveryError("candidate artifact digest mismatch")
    if any(item.get("severity") == "blocker" for item in candidate.get("criticFindings", [])):
        raise OntologyDiscoveryError("candidate has blocker-level Critic findings")
    approved = approve_candidate(
        candidate,
        reviewer_id=reviewer_id,
        approval_ref=approval_ref,
        expected_digest=expected_digest,
    )
    approved_path = save_candidate(approved, approved_root)
    return {
        "candidate": approved,
        "candidateDigest": actual_digest,
        "artifactPath": str(approved_path),
    }
