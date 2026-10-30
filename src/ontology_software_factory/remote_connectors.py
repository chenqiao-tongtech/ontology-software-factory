"""Remote GitHub/GitLab repository metadata connectors.

Only fixed provider hosts are contacted. The connector inventories repository paths and
revision metadata; it never downloads file bodies or returns credentials.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from urllib.parse import quote, urlparse
from typing import Callable

from .source_connectors import SourceAsset, SourceConnectorError, SourceScanResult, _asset_id

TEXT_SUFFIXES = {
    ".md", ".mdx", ".rst", ".txt", ".py", ".pyi", ".js", ".jsx", ".ts", ".tsx",
    ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".sql", ".xml", ".xsd",
    ".ttl", ".owl", ".properties", ".conf", ".sh", ".go", ".java", ".kt", ".rs",
    ".html", ".mmd", ".proto", ".graphql",
}
EXCLUDED = {".git", ".hg", ".svn", ".venv", "venv", "node_modules", "__pycache__", "dist", "build", "target"}


class RemoteRepositoryConnector:
    """Read-only metadata adapter for github.com or gitlab.com."""

    def __init__(self, provider: str, fetch_json: Callable, *, token_env: str | None = None, max_assets: int = 600):
        if provider not in {"github", "gitlab"}:
            raise ValueError("provider must be github or gitlab")
        self.source_type = provider
        self.provider = provider
        self.fetch_json = fetch_json
        self.max_assets = max_assets
        self.token_env = token_env

    def scan(self, source_id: str, location: str | Path) -> SourceScanResult:
        parsed = urlparse(str(location))
        expected_host = "github.com" if self.provider == "github" else "gitlab.com"
        if parsed.scheme != "https" or parsed.hostname != expected_host or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise SourceConnectorError(f"{self.provider} source must use credential-free HTTPS on {expected_host}")
        segments = [part for part in parsed.path.strip("/").split("/") if part]
        if (self.provider == "github" and len(segments) != 2) or (self.provider == "gitlab" and len(segments) < 2):
            raise SourceConnectorError("repository URL path is invalid")
        token_name = "GITHUB_TOKEN" if self.provider == "github" else "GITLAB_TOKEN"
        token = os.getenv(token_name)
        if self.provider == "github":
            owner, repository = segments
            repository = repository.removesuffix(".git")
            api_root = f"https://api.github.com/repos/{quote(owner, safe='')}/{quote(repository, safe='')}"
            headers = {"Accept": "application/vnd.github+json", "User-Agent": "ontology-software-factory", "X-GitHub-Api-Version": "2022-11-28"}
            if token:
                headers["Authorization"] = f"Bearer {token}"
            status, info = self.fetch_json(api_root, headers)
            if status != 200 or not isinstance(info, dict):
                raise SourceConnectorError(self._http_error(status, bool(token)))
            branch = info.get("default_branch") or "main"
            tree_status, tree = self.fetch_json(f"{api_root}/git/trees/{quote(branch, safe='')}?recursive=1", headers)
            if tree_status != 200 or not isinstance(tree, dict):
                raise SourceConnectorError(f"github tree API returned HTTP {tree_status}")
            entries = tree.get("tree", [])
            revision = tree.get("sha")
            visibility = info.get("visibility", "unknown")
            updated = info.get("pushed_at")
            truncated = bool(tree.get("truncated"))
        else:
            project = "/".join(segments).removesuffix(".git")
            api_root = f"https://gitlab.com/api/v4/projects/{quote(project, safe='')}"
            headers = {"Accept": "application/json", "User-Agent": "ontology-software-factory"}
            if token:
                headers["PRIVATE-TOKEN"] = token
            status, info = self.fetch_json(api_root, headers)
            if status != 200 or not isinstance(info, dict):
                raise SourceConnectorError(self._http_error(status, bool(token)))
            branch = info.get("default_branch") or "main"
            entries = []
            for page in range(1, 7):
                tree_status, listing = self.fetch_json(
                    f"{api_root}/repository/tree?recursive=true&per_page=100&page={page}&ref={quote(branch, safe='')}", headers
                )
                if tree_status != 200 or not isinstance(listing, list):
                    raise SourceConnectorError(f"gitlab tree API returned HTTP {tree_status}")
                entries.extend(listing)
                if len(listing) < 100:
                    break
            revision = info.get("last_commit_id")
            visibility = info.get("visibility", "unknown")
            updated = info.get("last_activity_at")
            truncated = len(entries) >= 600
        assets = []
        for item in entries:
            path = str(item.get("path", ""))
            parts = path.split("/")
            if item.get("type") not in {"blob", "file"} or Path(path).suffix.casefold() not in TEXT_SUFFIXES:
                continue
            if any(part in EXCLUDED or part.startswith(".") for part in parts):
                continue
            assets.append(SourceAsset(
                asset_id=_asset_id(source_id, path, "remote-file"),
                source_id=source_id,
                kind="file",
                name=Path(path).name,
                locator=path,
                size_bytes=item.get("size") if isinstance(item.get("size"), int) else None,
                metadata={"suffix": Path(path).suffix.casefold(), "provider": self.provider, "sourceRevision": revision, "defaultBranch": branch},
            ))
            if len(assets) >= self.max_assets:
                truncated = True
                break
        warnings = ("remote tree was truncated or reached the configured asset limit",) if truncated else ()
        return SourceScanResult(source_id, self.provider, "partial" if truncated else "connected", tuple(assets), warnings)

    @staticmethod
    def _http_error(status: int, token_present: bool) -> str:
        if status in {401, 403, 404}:
            return "remote authentication or repository visibility check failed"
        if status == 429:
            return "remote provider rate limit reached"
        return f"remote provider returned HTTP {status}"
