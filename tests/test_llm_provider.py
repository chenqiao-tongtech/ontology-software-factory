import json
import unittest
from types import SimpleNamespace

from ontology_software_factory.llm_provider import (
    FakeLLMProvider, LLMProviderError, LLMRequest, OpenAIResponsesProvider,
)


class FakeResponses:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        item = self.replies.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class RetryError(Exception):
    status_code = 429


class LLMProviderTests(unittest.TestCase):
    def test_fake_provider_is_network_free(self):
        provider = FakeLLMProvider("sample")
        result = provider.generate(LLMRequest("sys", "hello"))
        self.assertEqual(result.output_text, "sample")
        self.assertEqual(len(provider.requests), 1)

    def test_generate_returns_usage_and_attempt(self):
        client = SimpleNamespace(responses=FakeResponses([
            SimpleNamespace(id="resp_1", model="gpt-test", output_text="ok",
                            usage=SimpleNamespace(input_tokens=4, output_tokens=2, total_tokens=6))
        ]))
        provider = OpenAIResponsesProvider(client=client, model="gpt-test", max_retries=0)
        result = provider.generate(LLMRequest("sys", "input", metadata={"task_id": "t1"}))
        self.assertEqual(result.output_text, "ok")
        self.assertEqual(result.usage["total_tokens"], 6)
        self.assertEqual(client.responses.calls[0]["store"], False)

    def test_usage_sink_records_usage_without_prompt_content(self):
        events = []
        client = SimpleNamespace(responses=FakeResponses([
            SimpleNamespace(id="resp_usage", model="gpt-test", output_text="answer text",
                            usage=SimpleNamespace(input_tokens=10, output_tokens=5, total_tokens=15))
        ]))
        provider = OpenAIResponsesProvider(client=client, model="gpt-test", max_retries=0,
                                          usage_sink=events.append)
        provider.generate(LLMRequest("secret system prompt", "private input",
                                     metadata={"run_id": "run-1", "stage_id": "requirement-analyst"}))
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["inputTokens"], 10)
        self.assertEqual(events[0]["stageId"], "requirement-analyst")
        self.assertNotIn("input", events[0])
        self.assertNotIn("output_text", events[0])

    def test_rate_limit_retries_with_bounded_backoff(self):
        delays = []
        client = SimpleNamespace(responses=FakeResponses([
            RetryError("private error detail"),
            SimpleNamespace(id="resp_2", model="m", output_text="ok", usage=None),
        ]))
        provider = OpenAIResponsesProvider(client=client, max_retries=1, sleeper=delays.append,
                                           random_fn=lambda: 0.5)
        result = provider.generate(LLMRequest("sys", "input"))
        self.assertEqual(result.attempt_count, 2)
        self.assertEqual(len(delays), 1)
        self.assertGreater(delays[0], 0)

    def test_non_retryable_error_is_not_retried(self):
        client = SimpleNamespace(responses=FakeResponses([ValueError("bad input"),
            SimpleNamespace(id="unused", model="m", output_text="ok", usage=None)]))
        provider = OpenAIResponsesProvider(client=client, max_retries=2)
        with self.assertRaises(LLMProviderError) as ctx:
            provider.generate(LLMRequest("sys", "input"))
        self.assertEqual(ctx.exception.attempts, 1)
        self.assertEqual(len(client.responses.calls), 1)

    def test_structured_response_is_schema_validated(self):
        schema = {"type": "object", "properties": {"summary": {"type": "string"}},
                  "required": ["summary"], "additionalProperties": False}
        client = SimpleNamespace(responses=FakeResponses([
            SimpleNamespace(id="resp_json", model="m", output_text=json.dumps({"summary": "valid"}), usage=None)
        ]))
        provider = OpenAIResponsesProvider(client=client, max_retries=0)
        payload, result = provider.generate_structured(LLMRequest("sys", "input"),
                                                       schema_name="requirement", schema=schema)
        self.assertEqual(payload["summary"], "valid")
        self.assertEqual(result.response_id, "resp_json")

    def test_invalid_structured_response_fails_closed(self):
        schema = {"type": "object", "properties": {"summary": {"type": "string"}},
                  "required": ["summary"], "additionalProperties": False}
        client = SimpleNamespace(responses=FakeResponses([
            SimpleNamespace(id="resp_bad", model="m", output_text='{"wrong": true}', usage=None)
        ]))
        provider = OpenAIResponsesProvider(client=client, max_retries=0)
        with self.assertRaises(LLMProviderError):
            provider.generate_structured(LLMRequest("sys", "input"), schema_name="req", schema=schema)


if __name__ == "__main__":
    unittest.main()
