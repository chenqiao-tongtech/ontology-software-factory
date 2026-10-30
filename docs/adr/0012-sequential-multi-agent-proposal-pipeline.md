# ADR 0012: Start with a sequential multi-Agent proposal pipeline

- Status: Accepted for the reference implementation
- Date: 2026-10-27

## Context

Real LLM and Agent Runtime are connected, but a useful vertical slice must pass typed artifacts between specialist roles and produce reviewable outputs without granting unrestricted repository or production powers.

## Decision

Run requirement analysis, architecture, implementation proposal, test strategy and security review sequentially. Validate typed outputs. Write candidate files only below `data/agent-pipeline/runs/<run_id>/proposed_changes/`. Reject unsafe paths, unsupported extensions, duplicate paths, oversized outputs and a small set of secret-like patterns. Hash each proposed file. Never execute, apply, merge or deploy proposals automatically. Unless the security output explicitly blocks, the run ends `needs_human_review`, not `released`.

## Consequences

- End-to-end model-driven flow can be tried early and reviewed deterministically.
- The pipeline remains safe to run against a source checkout because it does not modify source files.
- Pattern-based secret checks are incomplete and are not SAST/DLP.
- Test Agent output is a test plan, not test-execution evidence.
- A production version still needs sandbox execution, CI evidence, state-machine integration and human approval.
