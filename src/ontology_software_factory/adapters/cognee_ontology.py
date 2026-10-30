"""Optional Cognee bridge for reviewed ontology candidates.

The adapter produces a schema-shaped graph specification and can optionally call an
installed Cognee client. Draft candidates are never admitted to a production dataset.
"""
from __future__ import annotations

import json
import re
from typing import Any


class CogneeOntologyError(RuntimeError):
    pass


def candidate_to_graph_document(candidate: dict[str, Any]) -> str:
    """Serialize an ontology candidate as a compact, provenance-carrying document for Cognee."""
    if candidate.get("status") not in {"approved", "review_required", "draft"}:
        raise CogneeOntologyError("unsupported candidate status")
    terms = [{
        "termId": term["termId"], "name": term["name"], "kind": term["kind"],
        "definition": term["definition"], "aliases": term.get("aliases", []),
        "sourceRefs": term.get("sourceRefs", []),
    } for term in candidate.get("terms", [])]
    relations = [{
        "relationId": relation["relationId"], "subjectTermId": relation.get("subjectTermId"),
        "subjectName": relation.get("subjectName"), "predicate": relation["predicate"],
        "objectTermId": relation.get("objectTermId"), "objectName": relation.get("objectName"),
        "relationKind": relation["relationKind"], "definition": relation["definition"],
        "sourceRefs": relation.get("sourceRefs", []),
    } for relation in candidate.get("relations", [])]
    return json.dumps({
        "candidateId": candidate.get("candidateId"),
        "candidateDigest": candidate.get("candidateDigest"),
        "candidateStatus": candidate.get("status"),
        "terms": terms,
        "relations": relations,
        "constraints": candidate.get("constraints", []),
        "sourceManifest": candidate.get("sourceManifest", []),
        "provenanceCoverage": candidate.get("validation", {}).get("provenanceCoverage", 0.0),
    }, ensure_ascii=False, sort_keys=True)


def build_cognee_graph_schema() -> dict[str, Any]:
    """Return an explicit custom graph schema compatible with Cognee's schema-oriented API.

    Projects using Cognee's Python API can generate DataPoint-based Pydantic classes from
    this spec, pass them as graph_model= to cognify(), and keep the candidate in a review
    dataset. We avoid importing Cognee in the core package because it is a large optional dep.
    """
    return {
        "version": "1.0.0",
        "nodeTypes": [
            {"name": "OntologyTerm", "identityFields": ["termId"], "indexFields": ["name", "definition"],
             "properties": {"termId": "string", "name": "string", "kind": "string", "definition": "string", "candidateId": "string", "candidateDigest": "string"}},
            {"name": "OntologyConstraint", "identityFields": ["constraintId"], "indexFields": ["name", "description"],
             "properties": {"constraintId": "string", "name": "string", "description": "string", "expression": "string", "candidateId": "string"}},
        ],
        "edgeTypes": [
            {"name": "OntologyRelation", "sourceType": "OntologyTerm", "targetType": "OntologyTerm",
             "properties": {"relationId": "string", "predicate": "string", "relationKind": "string", "definition": "string", "candidateId": "string"}},
        ],
        "requiredProvenance": ["candidateId", "candidateDigest", "sourceRefs"],
        "defaultDatasetPattern": "ontology-candidate-review-{candidateId}",
        "productionDatasetAllowedForDraft": False,
    }


async def stage_candidate_in_cognee(*, cognee_client: Any, candidate: dict[str, Any],
                                    graph_model: Any, dataset_name: str,
                                    approval_ref: str | None = None) -> dict[str, Any]:
    """Stage candidates in an isolated review dataset; requires approval for approved graph.

    Drafts are allowed only in dataset names beginning with ``ontology-candidate-review-``.
    Promotion into any production dataset is intentionally not implemented here.
    """
    if not dataset_name or not re.fullmatch(r"[a-zA-Z0-9_-]{3,100}", dataset_name):
        raise CogneeOntologyError("dataset_name format is invalid")
    status = candidate.get("status")
    if not dataset_name.startswith("ontology-candidate-review-"):
        raise CogneeOntologyError("this adapter only writes isolated ontology-candidate-review datasets; promotion is out of scope")
    if status == "approved" and not approval_ref:
        raise CogneeOntologyError("approved candidate staging requires approval_ref")
    document = candidate_to_graph_document(candidate)
    try:
        await cognee_client.add(document, dataset_name=dataset_name)
        await cognee_client.cognify(graph_model=graph_model, dataset_name=dataset_name)
    except Exception as exc:
        raise CogneeOntologyError(f"Cognee staging failed ({type(exc).__name__})") from exc
    return {"candidateId": candidate.get("candidateId"), "datasetName": dataset_name,
            "stageStatus": "staged", "approvalRef": approval_ref,
            "productionPromotion": False}
