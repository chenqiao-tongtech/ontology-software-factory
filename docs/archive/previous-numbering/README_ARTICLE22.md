# Article 22 · Real LLM Provider

Adds a provider-neutral `LLMProvider` boundary and a real OpenAI Responses API implementation with bounded retries, structured output validation and sanitized logs.

```bash
# Merge docs/dependency-extras.toml into the existing [project.optional-dependencies] block first.
python -m pip install -e '.[llm]'
export OPENAI_API_KEY='...'
export OPENAI_MODEL='gpt-6.1-sol'  # or a model enabled for your API project
python scripts/check_llm_connection.py
PYTHONPATH=src python -m unittest tests.test_llm_provider -v
```

The connection script makes a real network request. Unit tests inject a fake client and do not prove API connectivity. Keep API keys out of source control.
