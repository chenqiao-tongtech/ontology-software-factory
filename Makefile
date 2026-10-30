PYTHON ?= python
export PYTHONPATH := src

.PHONY: docker-test-image portal ai-runtime-console agent-workflow-console llm-check validate architecture-baseline scope ontology catalog agent-contracts multi-agent workflow ontology-discovery-config ontology-discovery-workflow ontology-consumers connector-catalog runner-tests test demo-pipeline demo-gate demo-e2e demo-ontology-discovery demo-ontology-discovery-worker observability clean-local
portal:
	$(PYTHON) scripts/run_factory_portal.py --host 127.0.0.1 --port 8770
ai-runtime-console:
	$(PYTHON) scripts/run_ai_runtime_console.py --host 127.0.0.1 --port 8768
agent-workflow-console:
	$(PYTHON) scripts/run_agent_workflow_console.py --host 127.0.0.1 --port 8769
llm-check:
	$(PYTHON) scripts/check_llm_connection.py

docker-test-image:
	docker build -f runners/container/Dockerfile.test-runner -t ontology-software-factory-test-runner:py311-v1 .

validate: architecture-baseline scope ontology catalog agent-contracts multi-agent workflow ontology-discovery-config ontology-discovery-workflow ontology-consumers connector-catalog
architecture-baseline:
	$(PYTHON) scripts/validate_architecture_baseline.py
scope:
	$(PYTHON) scripts/check_mvp_scope.py
ontology:
	$(PYTHON) scripts/validate_domain_model.py
catalog:
	$(PYTHON) scripts/validate_asset_catalog.py
agent-contracts:
	$(PYTHON) scripts/validate_agent_contracts.py
multi-agent:
	$(PYTHON) scripts/validate_multi_agent_architecture.py
workflow:
	$(PYTHON) scripts/validate_workflow_definition.py
	$(PYTHON) scripts/validate_agent_workflow_definition.py
ontology-discovery-config:
	$(PYTHON) scripts/validate_ontology_discovery_config.py
ontology-discovery-workflow:
	$(PYTHON) scripts/validate_ontology_discovery_workflow.py
ontology-consumers:
	$(PYTHON) scripts/validate_ontology_consumers.py
connector-catalog:
	$(PYTHON) scripts/validate_connector_catalog.py
runner-tests:
	$(PYTHON) -m unittest tests.test_kafka_profile -v
test:
	$(PYTHON) -m unittest discover -s tests -v
demo-pipeline:
	$(PYTHON) scripts/run_software_factory_pipeline.py --request examples/requests/kafka-development.json --output-root .local-runs --run-id demo-pipeline

demo-gate: demo-pipeline
	$(PYTHON) scripts/run_quality_gate.py --run-dir .local-runs/demo-pipeline

demo-e2e:
	$(PYTHON) scripts/run_e2e_delivery.py --request examples/requests/kafka-development.json --runs-root .local-runs --deliverables deliverables --run-id demo-e2e
demo-ontology-discovery:
	$(PYTHON) scripts/run_ontology_discovery.py --demo --overwrite
demo-ontology-discovery-worker:
	$(PYTHON) scripts/run_ontology_discovery_worker_demo.py
observability:
	$(PYTHON) scripts/report_factory_observability.py --runs-root .local-runs --rates observability/config/model-rates.example.json --out observability/reports/latest.json
clean-local:
	rm -rf .local-runs .local-environments .local-portal deliverables observability/reports
