# Compatibility matrix policy

Compatibility is a claim with a scope and evidence, not a property inferred from version numbers.

Each record identifies a `sourceVersionId`, `targetVersionId`, `status`, and `evidenceArtifactIds`.

- `untested`: no compatibility conclusion may be drawn.
- `compatible`: require a real, verified test report or equivalent evidence tied to the tested pair.
- `incompatible`: require verified evidence and a short explanation of the failure boundary.

A compatibility claim should also record at least the test date, platform/runtime, relevant configuration, test-suite version, and the source/build identifiers that were exercised. The MVP schema keeps some of these fields optional; teams should promote them to required fields once their test pipeline can reliably populate them.

Never infer compatibility solely because two versions satisfy a SemVer range. The range resolves candidate versions; only a defined test scope and evidence support a compatibility claim.
