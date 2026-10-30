"""Deterministic source asset manifest comparison for safe incremental sync reporting."""
from __future__ import annotations

import hashlib
import json
from typing import Any


def _asset_key(asset: dict[str, Any]) -> str:
    return str(asset.get("assetId") or asset.get("path") or asset.get("name") or "").strip()


def _asset_fingerprint(asset: dict[str, Any]) -> str:
    content_hash = asset.get("sha256") or asset.get("contentSha256")
    if content_hash:
        value = "content:" + str(content_hash)
    elif asset.get("assetFingerprint"):
        value = "schema:" + str(asset["assetFingerprint"])
    else:
        # Remote repository metadata may not include file bodies. Its revision and
        # size are metadata fingerprints, not proof of file-content identity.
        fields = {
            key: asset.get(key)
            for key in ("path", "name", "kind", "bytes", "size", "sourceRevision", "schema", "columns")
            if key in asset
        }
        value = json.dumps(fields, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def compare_asset_manifests(
    previous_assets: list[dict[str, Any]] | None,
    current_assets: list[dict[str, Any]] | None,
    *,
    previous_complete: bool,
    current_complete: bool,
) -> dict[str, Any]:
    """Compare metadata manifests without inferring deletions from truncated scans."""
    previous = previous_assets if isinstance(previous_assets, list) else []
    current = current_assets if isinstance(current_assets, list) else []
    old = {_asset_key(item): _asset_fingerprint(item) for item in previous
           if isinstance(item, dict) and _asset_key(item)}
    new = {_asset_key(item): _asset_fingerprint(item) for item in current
           if isinstance(item, dict) and _asset_key(item)}
    added_keys = sorted(set(new) - set(old))
    changed_keys = sorted(key for key in set(new) & set(old) if new[key] != old[key])
    unchanged_count = sum(1 for key in set(new) & set(old) if new[key] == old[key])
    removed_keys = sorted(set(old) - set(new)) if previous_complete and current_complete else None
    return {
        "baseline": previous_assets is None,
        "previousComplete": bool(previous_complete),
        "currentComplete": bool(current_complete),
        "added": len(new) if previous_assets is None else len(added_keys),
        "changed": len(changed_keys),
        "unchanged": 0 if previous_assets is None else unchanged_count,
        "removed": None if removed_keys is None else len(removed_keys),
        "removedKnown": removed_keys is not None,
        "addedKeys": added_keys[:100],
        "changedKeys": changed_keys[:100],
        "removedKeys": removed_keys[:100] if removed_keys is not None else [],
        "note": (
            "metadata-only comparison; remote revision/size fingerprints are not content hashes"
            if any(not (item.get("sha256") or item.get("contentSha256") or item.get("assetFingerprint"))
                   for item in current if isinstance(item, dict))
            else "content/schema fingerprints compared"
        ),
    }
