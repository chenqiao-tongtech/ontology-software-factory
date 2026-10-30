from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ontology_software_factory.ontology_runtime import (
    OntologyBindingError,
    build_agent_task_contract,
    load_active_ontology_binding,
    validate_agent_task_contract,
    validate_agent_output,
    validate_ontology_binding,
)
from ontology_software_factory.ontology_versioning import create_snapshot

ROOT = Path(__file__).resolve().parents[1]


class OntologyRuntimeBindingTests(unittest.TestCase):
    def setUp(self):
        self.ontology = json.loads((ROOT / "ontology/software-factory-ontology.json").read_text(encoding="utf-8"))
        self.snapshot = create_snapshot(self.ontology, actor="test", reason="runtime test")
        self.role = json.loads((ROOT / "agents/roles/requirement-analyst.json").read_text(encoding="utf-8"))

    def test_load_active_binding_from_portal_state(self):
        with tempfile.TemporaryDirectory() as temp:
            state_dir = Path(temp) / ".local-portal"
            state_dir.mkdir()
            (state_dir / "state.json").write_text(json.dumps({
                "activeOntologySnapshotId": self.snapshot["snapshotId"],
                "ontologySnapshots": [self.snapshot],
            }), encoding="utf-8")
            loaded = load_active_ontology_binding(temp)
            self.assertEqual(loaded["snapshotId"], self.snapshot["snapshotId"])
            self.assertEqual(loaded["digest"], self.snapshot["digest"])
            self.assertEqual(loaded["ontologyVersion"], self.snapshot["ontologyVersion"])

    def test_missing_active_binding_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            state_dir = Path(temp) / ".local-portal"
            state_dir.mkdir()
            (state_dir / "state.json").write_text(json.dumps({
                "activeOntologySnapshotId": None, "ontologySnapshots": [self.snapshot],
            }), encoding="utf-8")
            with self.assertRaises(OntologyBindingError):
                load_active_ontology_binding(temp)

    def test_tampered_snapshot_digest_is_rejected(self):
        tampered = json.loads(json.dumps(self.snapshot))
        tampered["ontology"]["classes"][0]["description"] = "tampered"
        with self.assertRaises(OntologyBindingError):
            validate_ontology_binding(tampered)

    def test_task_contract_is_bound_to_snapshot_and_role(self):
        task = build_agent_task_contract(
            ROOT, role=self.role, binding=self.snapshot, run_id="RUN-ABC123",
            step_id="requirement-analysis", attempt=1, objective="Create a small API",
            idempotency_key="workflow:RUN-ABC123:requirement-analysis:1",
        )
        self.assertEqual(task["ontologySnapshotId"], self.snapshot["snapshotId"])
        self.assertEqual(task["ontologyDigest"], self.snapshot["digest"])
        self.assertEqual(task["ontologyVersion"], self.snapshot["ontologyVersion"])
        self.assertEqual(task["roleId"], self.role["roleId"])
        validate_agent_task_contract(ROOT, task, role=self.role, binding=self.snapshot)

    def test_task_contract_with_stale_digest_is_rejected(self):
        task = build_agent_task_contract(
            ROOT, role=self.role, binding=self.snapshot, run_id="RUN-ABC123",
            step_id="requirement-analysis", attempt=1, objective="Create a small API",
        )
        task["ontologyDigest"] = "0" * 64
        with self.assertRaises(OntologyBindingError):
            validate_agent_task_contract(ROOT, task, role=self.role, binding=self.snapshot)

    def test_role_cannot_reference_class_absent_from_pinned_snapshot(self):
        reduced = json.loads(json.dumps(self.ontology))
        reduced["classes"] = [item for item in reduced["classes"] if item["name"] != "Artifact"]
        snapshot = create_snapshot(reduced, actor="test", reason="reduced ontology")
        with self.assertRaises(OntologyBindingError):
            build_agent_task_contract(
                ROOT, role=self.role, binding=snapshot, run_id="RUN-ABC123",
                step_id="requirement-analysis", attempt=1, objective="Create a small API",
            )

    def test_typed_output_must_respect_role_output_types(self):
        with self.assertRaises(OntologyBindingError):
            validate_agent_output(
                {"entityType": "Deployment"}, role=self.role, binding=self.snapshot,
            )


if __name__ == "__main__":
    unittest.main()
