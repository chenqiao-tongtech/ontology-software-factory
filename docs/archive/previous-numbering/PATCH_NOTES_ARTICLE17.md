# Article 17 patch notes — reusable asset catalogue

## Added

- `catalog/schemas/asset-catalog.schema.json`
- `catalog/examples/demo-catalog.json` (synthetic placeholder data only)
- `catalog/compatibility-matrix.md`
- `catalog/policies/lifecycle-and-customization.md`
- `docs/asset-catalog.md`
- `docs/adr/0005-versioned-asset-catalogue-and-customer-config-boundary.md`
- `src/ontology_software_factory/catalog.py`
- `scripts/validate_asset_catalog.py`
- `tests/test_catalog.py`
- `article/通往AI之桥_本体论系列17_公众号发布稿.md`

## Updated

- `README.md`, `Makefile`, `pyproject.toml`
- `catalog/README.md`
- `config/mvp-scope.json`
- `docs/acceptance/mvp-checklist.md`

## Merge and verify

1. Commit or back up your current GitHub working tree.
2. Merge the files from the patch into the repository root. Review changes to README, Makefile, `pyproject.toml`, MVP scope manifest and acceptance checklist rather than blindly overwriting your own edits.
3. Run `python -m pip install -e .`, `make validate`, and `make test`.
4. The included demo catalogue should pass structural and semantic validation. Its example release-readiness check is expected to be blocked because sample artifact digests, SBOM and provenance references are placeholders marked `pending`.

The validator does not fetch artifacts, verify bytes or signatures, parse SBOM content, run scanners, or release/deploy software.
