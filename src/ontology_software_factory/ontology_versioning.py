"""Immutable, operator-triggered snapshots and structural diffs for the formal ontology."""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def ontology_digest(ontology: dict) -> str:
    return hashlib.sha256(canonical_json(ontology).encode("utf-8")).hexdigest()


def create_snapshot(ontology: dict, *, actor: str, reason: str, created_at: str | None = None) -> dict:
    if not isinstance(ontology, dict):
        raise ValueError("ontology must be an object")
    actor = str(actor).strip()
    reason = str(reason).strip()
    if not actor or not reason:
        raise ValueError("actor and reason are required")
    digest = ontology_digest(ontology)
    return {
        "snapshotId": "ont-" + digest[:16],
        "ontologyId": ontology.get("ontologyId", "unknown"),
        "ontologyVersion": ontology.get("ontologyVersion", "unknown"),
        "schemaVersion": ontology.get("schemaVersion", "unknown"),
        "digest": digest,
        "createdAt": created_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "actor": actor[:100],
        "reason": reason[:1000],
        "ontology": deepcopy(ontology),
    }


def _indexed(items: list[dict], key_fn) -> dict[str, dict]:
    result = {}
    for item in items:
        if isinstance(item, dict):
            key = key_fn(item)
            result[str(key)] = item
    return result


def _diff_items(before: list, after: list, key_fn) -> dict:
    old = _indexed(before, key_fn)
    new = _indexed(after, key_fn)
    added = sorted(set(new) - set(old))
    removed = sorted(set(old) - set(new))
    changed = sorted(key for key in set(old) & set(new) if canonical_json(old[key]) != canonical_json(new[key]))
    return {
        "added": [{"key": key, "value": new[key]} for key in added],
        "removed": [{"key": key, "value": old[key]} for key in removed],
        "changed": [{"key": key, "before": old[key], "after": new[key]} for key in changed],
    }


def _relation_key(item: dict) -> str:
    target = item.get("target", [])
    if isinstance(target, list):
        target = sorted(str(x) for x in target)
    return "|".join((str(item.get("name", "")), str(item.get("source", "")), canonical_json(target)))


def diff_snapshots(before: dict, after: dict) -> dict:
    """Compare two saved snapshots; never mutate either snapshot."""
    left = before.get("ontology", {})
    right = after.get("ontology", {})
    left_ext = left.get("operationalExtensions", {}) if isinstance(left.get("operationalExtensions"), dict) else {}
    right_ext = right.get("operationalExtensions", {}) if isinstance(right.get("operationalExtensions"), dict) else {}
    sections = {
        "coreClasses": _diff_items(left.get("classes", []), right.get("classes", []), lambda x: x.get("name", "")),
        "operationalClasses": _diff_items(left_ext.get("classes", []), right_ext.get("classes", []), lambda x: x.get("name", "")),
        "coreRelations": _diff_items(left.get("relations", []), right.get("relations", []), _relation_key),
        "operationalRelations": _diff_items(left_ext.get("relations", []), right_ext.get("relations", []), _relation_key),
        "controlledVocabularies": _diff_items(
            [{"name": key, "values": value} for key, value in left.get("controlledVocabularies", {}).items()],
            [{"name": key, "values": value} for key, value in right.get("controlledVocabularies", {}).items()],
            lambda x: x["name"],
        ),
        "mvpInvariants": _diff_items(
            [{"rule": value} for value in left.get("mvpInvariants", [])],
            [{"rule": value} for value in right.get("mvpInvariants", [])],
            lambda x: x["rule"],
        ),
    }
    affected_classes: set[str] = set()
    changed_relation_keys = []
    for name in ("coreRelations", "operationalRelations"):
        section = sections[name]
        for entry in section["added"] + section["removed"]:
            relation = entry["value"]
            affected_classes.add(str(relation.get("source", "")))
            targets = relation.get("target", [])
            affected_classes.update(str(x) for x in (targets if isinstance(targets, list) else [targets]))
            changed_relation_keys.append(entry["key"])
        for entry in section["changed"]:
            for relation in (entry["before"], entry["after"]):
                affected_classes.add(str(relation.get("source", "")))
                targets = relation.get("target", [])
                affected_classes.update(str(x) for x in (targets if isinstance(targets, list) else [targets]))
            changed_relation_keys.append(entry["key"])
    for name in ("coreClasses", "operationalClasses"):
        for section_name in ("added", "removed", "changed"):
            for entry in sections[name][section_name]:
                affected_classes.add(str(entry.get("key", "")))
    affected_classes.discard("")
    counts = {
        section: {kind: len(items) for kind, items in value.items()}
        for section, value in sections.items()
    }
    changed = any(any(counts[section].values()) for section in sections)
    return {
        "from": {"snapshotId": before.get("snapshotId"), "ontologyVersion": before.get("ontologyVersion"), "digest": before.get("digest")},
        "to": {"snapshotId": after.get("snapshotId"), "ontologyVersion": after.get("ontologyVersion"), "digest": after.get("digest")},
        "changed": changed,
        "sections": sections,
        "summary": counts,
        "impact": {
            "affectedClasses": sorted(affected_classes),
            "changedRelations": sorted(changed_relation_keys),
            "potentialConsumers": [],
            "consumerImpactNote": "当前版本仅能从本体关系端点推导概念影响；Agent、Skill、Workflow 和契约消费者尚未建立稳定引用索引，因此不报告未经验证的下游消费者。",
            "reviewRequired": changed,
        },
    }


def find_snapshot(snapshots: list[dict], snapshot_id: str) -> dict:
    for item in snapshots:
        if item.get("snapshotId") == snapshot_id:
            return item
    raise KeyError("ontology snapshot not found")
