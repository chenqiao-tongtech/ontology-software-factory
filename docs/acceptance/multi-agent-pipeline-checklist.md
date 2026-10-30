# Acceptance checklist: multi-Agent pipeline

- [ ] Pipeline order is requirement → architecture → implementation proposal → test strategy → security review.
- [ ] Each stage returns a typed JSON-compatible object.
- [ ] A failed stage stops the chain and writes a sanitized failure artifact.
- [ ] Proposal paths are relative and traversal is blocked.
- [ ] Unsupported suffix, duplicate path, oversized file and secret-like pattern are rejected.
- [ ] Proposals are stored only under the run-specific artifact folder.
- [ ] Each proposed file has SHA-256, byte count, `executed=false`, and `applied_to_repository=false`.
- [ ] Security `blocked` yields a blocked pipeline result; otherwise result still requires human review.
- [ ] No generated file is executed, applied, committed, merged or deployed automatically.
- [ ] Credentialed environment runs real model requests; mock tests are not presented as live API validation.
