from pathlib import Path
from ontology_software_factory.connector_catalog import ConnectorCatalog

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    catalog = ConnectorCatalog(ROOT)
    sources = catalog.list_connectors(category="ontology-source")
    actions = catalog.list_connectors(category="agent-action")
    if any(item.direction != "read" for item in sources):
        raise SystemExit("ontology source connector must be read-only")
    if any(item.direction != "write" for item in actions):
        raise SystemExit("agent action connector must be write-capable")
    print(f"Connector runtime contracts valid: {len(sources)} sources, {len(actions)} actions")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
