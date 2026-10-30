"""Worker adapter for the LLM-assisted ontology discovery pipeline.

The task queue carries source references, not raw confidential document contents. A trusted
source_resolver owns access control and returns only the approved SourceMaterial objects.
Outputs remain review candidates; this adapter never promotes the official ontology.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .ontology_discovery import (
    OntologyDiscoveryError,
    OntologyDiscoveryPipeline,
    SourceMaterial,
    candidate_digest,
    evaluate_candidate,
    save_candidate,
)

SourceResolver = Callable[[dict[str, Any]], SourceMaterial]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def make_ontology_discovery_handler(
    provider: Any,
    *,
    output_root: str | Path,
    source_resolver: SourceResolver,
    benchmark: dict[str, Any] | None = None,
) -> Callable[[dict[str, Any], Any], dict[str, Any]]:
    """Create a handler compatible with ``TaskWorker`` for task type ``ontology.discovery.run``.

    Expected payload::
      {"domain": "...", "sourceRefs": [{"sourceId": "...", "sourceType": "markdown", "locator": "..."}],
       "context": "optional sanitized context"}

    ``source_resolver`` must authorize each source reference and fetch content from trusted
    storage. Do not put raw customer documents or secrets directly into the persistent queue.
    """
    root = Path(output_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    pipeline = OntologyDiscoveryPipeline(provider)

    def handle(payload: dict[str, Any], context: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise OntologyDiscoveryError("task payload must be an object")
        domain = str(payload.get("domain", "")).strip()
        refs = payload.get("sourceRefs")
        if not isinstance(refs, list) or not refs:
            raise OntologyDiscoveryError("sourceRefs must be a non-empty list of authorized references")
        if any(not isinstance(ref, dict) for ref in refs):
            raise OntologyDiscoveryError("each sourceRef must be an object")
        sources: list[SourceMaterial] = []
        seen: set[str] = set()
        for ref in refs:
            if set(ref) - {"sourceId", "sourceType", "locator", "version", "tenantRef"}:
                raise OntologyDiscoveryError("sourceRef contains unsupported fields")
            source_id = str(ref.get("sourceId", "")).strip()
            if not source_id or source_id in seen:
                raise OntologyDiscoveryError("sourceRef IDs must be non-empty and unique")
            seen.add(source_id)
            source = source_resolver(ref)
            if not isinstance(source, SourceMaterial):
                raise OntologyDiscoveryError("source_resolver must return SourceMaterial")
            if source.source_id != source_id:
                raise OntologyDiscoveryError("resolved source ID does not match requested source ID")
            if str(ref.get("sourceType", "")) != source.source_type or str(ref.get("locator", "")) != source.locator:
                raise OntologyDiscoveryError("resolved source type/locator does not match the approved source reference")
            sources.append(source)
        if hasattr(context, "check_deadline"):
            context.check_deadline()
        candidate = pipeline.discover(
            domain=domain,
            sources=sources,
            context=str(payload.get("context", "")),
            run_id=str(getattr(context, "task_id", "ontology-discovery-worker")),
        )
        target = root / f"{candidate['candidateId']}.json"
        if target.exists():
            try:
                existing = json.loads(target.read_text(encoding="utf-8"))
            except Exception as exc:
                raise OntologyDiscoveryError("existing candidate file is unreadable; manual reconciliation required") from exc
            if candidate_digest(existing) != candidate_digest(candidate):
                raise OntologyDiscoveryError("candidate ID exists with a different digest; refusing overwrite")
            candidate = existing
        else:
            save_candidate(candidate, root)
        evaluation = evaluate_candidate(candidate, benchmark) if benchmark is not None else None
        evidence: list[dict[str, Any]] = [{
            "type": "ontology-candidate-json",
            "uri": target.as_uri(),
            "sha256": _sha256_file(target),
            "createdAt": _utc_now(),
            "mediaType": "application/json",
        }]
        evaluation_path = None
        if evaluation is not None:
            evaluation_path = root / f"{candidate['candidateId']}.evaluation.json"
            eval_bytes = json.dumps(evaluation, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
            if evaluation_path.exists() and evaluation_path.read_bytes() != eval_bytes:
                # Evaluation output can include only deterministic metrics today; if this changes,
                # preserve existing runs as immutable rather than overwrite evidence.
                evaluation_path = root / f"{candidate['candidateId']}.evaluation-{hashlib.sha256(eval_bytes).hexdigest()[:8]}.json"
            if not evaluation_path.exists():
                evaluation_path.write_bytes(eval_bytes)
            evidence.append({
                "type": "ontology-evaluation-json",
                "uri": evaluation_path.as_uri(),
                "sha256": _sha256_file(evaluation_path),
                "createdAt": _utc_now(),
                "mediaType": "application/json",
            })
        if hasattr(context, "check_deadline"):
            context.check_deadline()
        return {
            "output": {
                "candidateId": candidate["candidateId"],
                "candidateDigest": candidate["candidateDigest"],
                "status": candidate["status"],
                "locallyValid": bool(candidate["validation"]["locallyValid"]),
                "provenanceCoverage": candidate["validation"]["provenanceCoverage"],
                "evaluationPassed": bool(evaluation and evaluation["passed"]),
                "promotionAllowed": False,
                "productionOntologyMutation": False,
                "candidatePath": str(target),
                "evaluationPath": str(evaluation_path) if evaluation_path else None,
            },
            "evidence": evidence,
        }

    return handle
