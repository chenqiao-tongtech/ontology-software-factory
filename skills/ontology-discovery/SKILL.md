# Skill: LLM-assisted ontology discovery

1. Collect only authorized, redacted source material and preserve source IDs, locators, and SHA-256 hashes.
2. Run the term, relation, constraint/competency-question, and independent-critic passes separately.
3. Require structured output that validates against each JSON Schema.
4. Verify every evidence quote against its original source; unresolved claims remain findings, not facts.
5. Evaluate the candidate against a domain-owner-reviewed gold benchmark. Scores do not approve publication.
6. Save a candidate snapshot with digest, generation trace, source manifest, and validation report.
7. Never update production ontology, permissions, policy, or workflows from this Skill.
