from pathlib import Path
from ontology_software_factory.connector_catalog import ConnectorCatalog

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    catalog = ConnectorCatalog(ROOT)
    items = catalog.list_connectors()
    enabled = sum(item.implementation_status == "implemented" for item in items)
    print(f"Connector catalog valid: {len(items)} descriptors ({enabled} implemented; {len(items)-enabled} not enabled)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
