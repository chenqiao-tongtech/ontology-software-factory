# Article 15 Multi-Agent Architecture Revision

This additive/replacement patch updates Article 15's overall architecture so bounded multi-agent collaboration is a first-class core capability.

## Main design changes

- S4 is now **Multi-Agent Collaboration and Agent Capabilities**, distinct from S5 deterministic Workflow/Task orchestration.
- Adds a versioned Team Topology (`agents/teams/software-factory-mvp.json`) with specialist roles, parallel independent verification, all-required joining, human approval and a maximum of two revision loops.
- Adds JSON Schemas for Agent Team and Agent Handoff contracts.
- Adds operational ontology extensions: `AgentTeam`, `AgentRole`, `Skill`, `AgentTask`, `AgentHandoff`, `AgentResult`, `ContextReference`, `CoordinationDecision`, and `ReviewDecision`; the eleven software-delivery core classes remain unchanged.
- Adds ADR 0016, multi-agent design document, topology diagram, acceptance checklist, negative tests and CLI validation.
- Updates the architecture baseline, MVP scope, subsystem decomposition, principles, NFRs, roadmap, risks and Article 15.

## Validation

```bash
make validate
python -m unittest discover -s tests -v
```

Last local validation: all 168 unit tests passed; `make validate` passed.

## Important boundary

The team topology, schemas and local validator are implemented and tested. The topology has **not yet been wired into the Agent Runtime dispatch path**; this remains `partial`. This patch does not claim production IAM, container sandboxing, live external tools or fully autonomous multi-agent production execution.

## Merge guidance

Merge or apply at the repository root after committing or backing up current changes. Review `README.md`, `Makefile`, `config/architecture-baseline.json`, `config/mvp-scope.json` and Article 15 for local edits before replacing same-path files. The patch is a path-level delta for the cumulative reference project, not a Git commit or remote push.
