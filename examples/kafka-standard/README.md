# Kafka-style standard delivery example (configuration-only)

This example packages and validates a configuration bundle referencing an approved catalogue entry. It **does not download, build, include, or run the Kafka binary** and does not prove cluster compatibility. The catalogue contains synthetic sample metadata whose upstream digests are placeholders.

Run the deterministic local pipeline:

```bash
python scripts/run_software_factory_pipeline.py --request examples/requests/kafka-development.json --output-root .local-runs
```

It executes fixed Python validation tools with `shell=False`, records output/exit code/hash, and creates a configuration package with a manifest. This is a restricted local runner, not an OS-level sandbox.
