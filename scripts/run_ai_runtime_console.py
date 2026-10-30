#!/usr/bin/env python3
"""Local-only console for checking real LLM access and running the real Agent pipeline.

Bind to loopback unless you have added authentication and network controls yourself.
"""
from __future__ import annotations

import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from ontology_software_factory.llm_provider import LLMProviderError, LLMRequest, OpenAIResponsesProvider  # noqa: E402


class Handler(BaseHTTPRequestHandler):
    server_version = "OntologySoftwareFactoryConsole/0.1"

    def _json(self, status: int, value: dict) -> None:
        body = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/api/status":
            try:
                import agents  # type: ignore[import-not-found]  # noqa: F401
                agent_sdk = True
            except ImportError:
                agent_sdk = False
            self._json(200, {
                "api_key_configured": bool(os.getenv("OPENAI_API_KEY")),
                "model": os.getenv("OPENAI_MODEL", "gpt-6.1-sol"),
                "agent_sdk_installed": agent_sdk,
                "tracing_enabled": os.getenv("AGENT_TRACE_ENABLED", "false").lower() in {"1", "true", "yes"},
                "notice": "Status does not reveal secret values. API calls require credentials and network access.",
            })
            return
        if self.path not in {"/", "/index.html"}:
            self._json(404, {"error": "not_found"})
            return
        content = (ROOT / "apps" / "ai-runtime-console" / "index.html").read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(content)

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        if length < 1 or length > 40_000:
            self._json(413, {"error": "invalid_body_size"})
            return
        try:
            payload = json.loads(self.rfile.read(length))
        except json.JSONDecodeError:
            self._json(400, {"error": "invalid_json"})
            return
        if self.path == "/api/llm/check":
            try:
                provider = OpenAIResponsesProvider()
                response = provider.generate(LLMRequest(
                    instructions="You are a connectivity-check agent. Return the requested phrase only.",
                    input=str(payload.get("prompt", "Reply with exactly: software-factory-connected"))[:1000],
                    max_output_tokens=100,
                    metadata={"purpose": "runtime-console-check"},
                ))
                self._json(200, {"ok": True, "provider": response.provider, "model": response.model,
                                 "response_id": response.response_id, "output_text": response.output_text,
                                 "latency_ms": response.latency_ms, "usage": response.usage,
                                 "attempts": response.attempt_count})
            except LLMProviderError as exc:
                self._json(400, {"ok": False, "error": str(exc), "attempts": exc.attempts})
            return
        if self.path == "/api/pipeline/run":
            requirement = payload.get("requirement")
            if not isinstance(requirement, str) or not requirement.strip():
                self._json(400, {"error": "requirement_required"})
                return
            try:
                from ontology_software_factory.agent_runtime import OpenAIAgentsRuntime
                from ontology_software_factory.software_factory_pipeline import SoftwareFactoryPipeline
                runtime = OpenAIAgentsRuntime(project_root=ROOT)
                pipeline = SoftwareFactoryPipeline(runtime, artifact_root=ROOT / "data" / "agent-pipeline" / "runs")
                result = pipeline.run(requirement)
                self._json(200, {"ok": True, "result": result.as_dict()})
            except Exception as exc:
                # Deliberately return type only; raw exception strings can leak prompts or env details.
                self._json(400, {"ok": False, "error_type": type(exc).__name__,
                                 "message": "Agent run failed. Check sanitized server logs and the run failure artifact."})
            return
        self._json(404, {"error": "not_found"})

    def log_message(self, fmt: str, *args) -> None:
        # HTTP logs exclude request bodies and secrets.
        print("[runtime-console] " + (fmt % args))


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8768)
    args = parser.parse_args()
    if args.host not in {"127.0.0.1", "localhost", "::1"}:
        print("WARNING: non-loopback binding exposes this unauthenticated console. Add auth before use.", file=sys.stderr)
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"AI Runtime Console: http://{args.host}:{args.port}")
    print("Press Ctrl+C to stop. API key is read from the process environment; it is not stored here.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
