# Portal LLM-Assisted Ontology Discovery

## What is implemented

The Factory Portal has two deliberately distinct discovery paths:

- **规则发现**: deterministic local extraction from source metadata/symbols; no model API call.
- **LLM 深度发现**: four-stage structured pipeline (terms, relations, constraints/competency questions, independent Critic), with local schema validation and quote-level provenance verification.

The live LLM path is disabled unless the operator explicitly sets:

```bash
export FACTORY_ENABLE_LLM_ONTOLOGY_DISCOVERY=1
export OPENAI_API_KEY='...'
export OPENAI_MODEL='a model available to this account'
python scripts/run_factory_portal.py
```

Optional per-stage model overrides:
- `ONTOLOGY_TERM_MODEL`
- `ONTOLOGY_RELATION_MODEL`
- `ONTOLOGY_CONSTRAINT_MODEL`
- `ONTOLOGY_CRITIC_MODEL`

Usage metadata is written to `.local-runs/ontology-candidates/llm-usage.jsonl`; prompts and model response bodies are not written to the usage ledger.

## Source selection and data handling

The UI accepts only explicitly selected local `repository` or `documents` directories. It does not download remote Git file bodies and does not query database business rows. Each selected source is read as UTF-8 text, with file boundaries and relative paths included so the model can cite locators.

Limits:
- 1–10 selected sources;
- at most 25 supported text files per source;
- 18,000 characters per source;
- 48,000 characters total;
- oversized/non-UTF-8/hidden/symlink files are excluded or rejected according to the collector's safety checks.

The pipeline blocks common private-key/API-key patterns before sending material. This is a basic safeguard, not enterprise DLP. Review source scope and data-processing terms before enabling the feature. The request is synchronous in this local Portal; production deployments should dispatch it through the persistent Worker queue with tenant-scoped source authorization and timeout/budget controls.

## Candidate review and approval

LLM output is stored as a candidate artifact under `.local-runs/ontology-candidates/<candidate-id>.json`. The Portal shows terms, verified source excerpts, relation/constraint counts, validation and Critic findings. The **查看结构化结果** action retrieves the candidate JSON without source document bodies.

Approval requires:
- a human reviewer identity;
- an explicit approval ticket/reference;
- the exact candidate digest displayed by the Portal;
- successful candidate validation;
- no blocker-level Critic finding.

The approved snapshot is written to `.local-runs/ontology-approved-candidates/` and the governance event records the digest and approval reference. This is an approved candidate artifact, **not** a mutation of `ontology/software-factory-ontology.json`. Formal ontology promotion still requires the existing snapshot, compatibility, approval and release-governance workflow.

## Reproducibility and conflicts

Candidate IDs are derived from the domain and source material. If the same source digest produces a different model result while an artifact with that candidate ID already exists, the Portal refuses to overwrite it. Preserve the existing artifact and change/revise the source batch before generating another candidate. This avoids silently replacing reviewed evidence.

## Validation

Offline tests use a deterministic fixture provider and do not make network calls. They verify source selection, file hashing, quote provenance, candidate artifact persistence and feature-flag behavior. A successful CI run does not prove that the configured model account, model ID, network route or data-processing region is available; operators must run a controlled live test with non-sensitive material.
