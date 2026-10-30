#!/usr/bin/env python3
"""Make one real Responses API request. Requires OPENAI_API_KEY and network access."""
import argparse
import logging
import os
import sys

from ontology_software_factory.llm_provider import LLMProviderError, LLMRequest, OpenAIResponsesProvider


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompt", default="Reply with exactly: software-factory-llm-connected")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if not os.getenv("OPENAI_API_KEY"):
        print("ERROR: set OPENAI_API_KEY in your shell environment first.", file=sys.stderr)
        return 2
    try:
        provider = OpenAIResponsesProvider()
        result = provider.generate(LLMRequest(
            instructions="You are an integration-check agent. Follow the user's instruction exactly.",
            input=args.prompt, max_output_tokens=80, metadata={"purpose": "connection-check"},
        ))
    except LLMProviderError as exc:
        print(f"LLM connection check failed: {exc}", file=sys.stderr)
        return 1
    print(f"provider={result.provider} model={result.model} response_id={result.response_id}")
    print(f"latency_ms={result.latency_ms} usage={result.usage} attempts={result.attempt_count}")
    print(result.output_text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
