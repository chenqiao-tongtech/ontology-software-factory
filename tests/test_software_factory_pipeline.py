import json
import tempfile
import unittest
from pathlib import Path

from ontology_software_factory.ontology_versioning import create_snapshot
from ontology_software_factory.software_factory_pipeline import (
    PipelineValidationError, SoftwareFactoryPipeline,
)


class FakeRunner:
    def __init__(self):
        self.calls = []

    def run_agent(self, role_id, task_input):
        self.calls.append((role_id, task_input))
        outputs = {
            "requirement-analyst": {"summary": "demo", "functional_requirements": ["FR-1"],
                                    "non_functional_requirements": ["no secret"], "acceptance_criteria": ["AC-1"],
                                    "assumptions": [], "open_questions": [], "risk_level": "low"},
            "solution-architect": {"summary": "one module", "components": ["API"], "data_flows": ["user -> API"],
                                   "security_controls": ["input validation"], "tradeoffs": [], "open_questions": []},
            "implementation-agent": {"work_items": [{"title": "add API", "description": "implement", "depends_on": [],
                                                    "verification": "unit tests"}],
                                     "proposed_changes": [{"relative_path": "src/demo.py", "purpose": "demo", "content": "def hello():\n    return 'hello'\n"}],
                                     "out_of_scope": ["deployment"], "requires_human_review": True},
            "test-agent": {"test_cases": [{"name": "hello", "test_type": "unit", "setup": "import module",
                                           "assertion": "returns hello", "automation_candidate": True}],
                           "required_gates": ["tests pass"], "residual_risks": []},
            "security-reviewer": {"findings": [], "release_recommendation": "ready_with_conditions",
                                  "rationale": "review required", "evidence_gaps": ["real tests not run"]},
        }
        return {"output": outputs[role_id], "latency_ms": 1, "tool_ids": []}


class PipelineTests(unittest.TestCase):
    def test_full_pipeline_writes_proposals_but_does_not_apply_them(self):
        with tempfile.TemporaryDirectory() as temp:
            runner = FakeRunner()
            result = SoftwareFactoryPipeline(runner, artifact_root=temp).run("Build a hello API", run_id="run-001")
            self.assertEqual(result.status, "needs_human_review")
            self.assertEqual([x[0] for x in runner.calls], SoftwareFactoryPipeline.STAGES)
            proposed = result.proposed_files[0]
            self.assertFalse(proposed["executed"])
            self.assertFalse(proposed["applied_to_repository"])
            self.assertTrue((Path(temp) / "run-001" / "proposed_changes/src/demo.py").is_file())
            self.assertTrue((Path(temp) / "run-001" / "run-report.json").is_file())

    def test_real_runtime_pipeline_records_pinned_ontology_and_task_contracts(self):
        class OntologyAwareFakeRunner(FakeRunner):
            requires_ontology_binding = True
            project_root = ROOT

            def run_agent(self, role_id, task_input, *, ontology_binding, task_contract):
                result = super().run_agent(role_id, task_input)
                result["ontology_binding"] = {
                    key: ontology_binding[key]
                    for key in ("snapshotId", "digest", "ontologyId", "ontologyVersion", "schemaVersion")
                }
                result["task_contract_digest"] = "test-task-contract-digest"
                return result

        ontology = json.loads((ROOT / "ontology/software-factory-ontology.json").read_text(encoding="utf-8"))
        binding = create_snapshot(ontology, actor="test", reason="direct pipeline binding")
        with tempfile.TemporaryDirectory() as temp:
            result = SoftwareFactoryPipeline(
                OntologyAwareFakeRunner(), artifact_root=temp, ontology_binding=binding
            ).run("Build a hello API", run_id="run-bound")
            self.assertTrue(all(stage["ontology_binding"]["snapshotId"] == binding["snapshotId"] for stage in result.stages))
            self.assertTrue(all(stage["task_contract"]["ontologyDigest"] == binding["digest"] for stage in result.stages))
            self.assertTrue(all(stage["task_contract_digest"] == "test-task-contract-digest" for stage in result.stages))

    def test_empty_requirement_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(PipelineValidationError):
                SoftwareFactoryPipeline(FakeRunner(), artifact_root=temp).run(" ")

    def test_traversal_path_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            pipeline = SoftwareFactoryPipeline(FakeRunner(), artifact_root=temp)
            dest = Path(temp) / "stage" / "proposed_changes"
            dest.mkdir(parents=True)
            with self.assertRaises(PipelineValidationError):
                pipeline._write_proposals(dest, [{"relative_path": "../../outside.py", "content": "x", "purpose": "escape"}])

    def test_secret_like_content_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            pipeline = SoftwareFactoryPipeline(FakeRunner(), artifact_root=temp)
            dest = Path(temp) / "stage" / "proposed_changes"
            dest.mkdir(parents=True)
            with self.assertRaises(PipelineValidationError):
                pipeline._write_proposals(dest, [{"relative_path": "config.py", "content": "API_KEY = 'sk-12345678901234567890'", "purpose": "secret"}])

    def test_existing_run_not_overwritten(self):
        with tempfile.TemporaryDirectory() as temp:
            runner = FakeRunner()
            pipeline = SoftwareFactoryPipeline(runner, artifact_root=temp)
            pipeline.run("Build a hello API", run_id="run-001")
            with self.assertRaises(PipelineValidationError):
                pipeline.run("Build another API", run_id="run-001")


if __name__ == "__main__":
    unittest.main()
