from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from ontology_software_factory.governance import (
    ApprovalError, ApprovalStore, InvocationError, SQLiteInvocationLedger, ToolGateway,
)
from ontology_software_factory.harness import HarnessPrincipal, HarnessRuntime
from ontology_software_factory.tool_registry import ToolRegistry
from ontology_software_factory.task_runtime import EvidenceContractError, SQLiteTaskStore

ROOT = Path(__file__).resolve().parents[1]


class GovernanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Path(self.temp.name) / "governance.sqlite3"

    def test_approval_is_bound_to_payload_and_consumed_once(self):
        store = ApprovalStore(self.db)
        self.addCleanup(store.close)
        payload = {"releaseId": "rel-1", "targetEnvironment": "prod"}
        store.request(
            approval_id="APR-1", run_id="run-1", task_id="task-1",
            tenant_id="tenant-a", tool_id="release.simulation.promote",
            payload=payload, requested_by="requester", now=100,
        )
        with self.assertRaises(ApprovalError):
            store.decide("APR-1", decision="approved", actor="requester",
                         reason="self approval", now=101)
        store.decide("APR-1", decision="approved", actor="approver",
                     reason="change reviewed", now=102)
        with self.assertRaises(ApprovalError):
            store.consume("APR-1", run_id="run-1", task_id="task-1",
                          tenant_id="tenant-a", tool_id="release.simulation.promote",
                          payload={"releaseId": "rel-2", "targetEnvironment": "prod"},
                          executor="executor", now=103)
        consumed = store.consume(
            "APR-1", run_id="run-1", task_id="task-1", tenant_id="tenant-a",
            tool_id="release.simulation.promote", payload=payload,
            executor="executor", now=104,
        )
        self.assertEqual(consumed["status"], "approved")
        self.assertIsNotNone(consumed["consumedAt"])
        with self.assertRaises(ApprovalError):
            store.consume("APR-1", run_id="run-1", task_id="task-1",
                          tenant_id="tenant-a", tool_id="release.simulation.promote",
                          payload=payload, executor="executor", now=105)


    def test_approval_reservation_is_finalized_or_left_uncertain(self):
        store = ApprovalStore(self.db)
        self.addCleanup(store.close)
        payload = {"releaseId": "rel-reserve", "targetEnvironment": "prod"}
        store.request(approval_id="APR-reserve", run_id="run-r", task_id="task-r",
            tenant_id="tenant-r", tool_id="release.simulation.promote",
            payload=payload, requested_by="requester", now=100)
        store.decide("APR-reserve", decision="approved", actor="approver",
            reason="reviewed", now=101)
        reserved = store.reserve("APR-reserve", run_id="run-r", task_id="task-r",
            tenant_id="tenant-r", tool_id="release.simulation.promote",
            payload=payload, executor="executor", now=102)
        self.assertEqual(reserved["status"], "reserved")
        uncertain = store.finalize_reservation("APR-reserve", outcome="uncertain")
        self.assertEqual(uncertain["status"], "uncertain")
        with self.assertRaises(ApprovalError):
            store.reserve("APR-reserve", run_id="run-r", task_id="task-r",
                tenant_id="tenant-r", tool_id="release.simulation.promote",
                payload=payload, executor="executor", now=103)

    def test_expired_approval_cannot_be_used(self):
        store = ApprovalStore(self.db)
        self.addCleanup(store.close)
        store.request(
            approval_id="APR-exp", run_id="run", task_id="task", tenant_id="tenant",
            tool_id="release.simulation.promote", payload={"x": 1},
            requested_by="requester", ttl_seconds=10, now=100,
        )
        store.decide("APR-exp", decision="approved", actor="approver",
                     reason="reviewed", now=101)
        with self.assertRaises(ApprovalError):
            store.consume("APR-exp", run_id="run", task_id="task", tenant_id="tenant",
                          tool_id="release.simulation.promote", payload={"x": 1},
                          executor="executor", now=111)

    def test_harness_requires_persisted_approval_for_high_impact_tool(self):
        approvals = ApprovalStore(self.db)
        self.addCleanup(approvals.close)
        payload = {"releaseId": "rel-1", "targetEnvironment": "prod"}
        approvals.request(
            approval_id="APR-H", run_id="run-h", task_id="task-h", tenant_id="tenant-a",
            tool_id="release.simulation.promote", payload=payload, requested_by="requester",
        )
        approvals.decide("APR-H", decision="approved", actor="approver", reason="reviewed")
        calls = []
        registry = ToolRegistry(ROOT, {"release.simulation.promote": lambda p: calls.append(p) or {"ok": True}})
        principal = HarnessPrincipal("executor", "release-coordinator", "tenant-a", "project-a")
        harness = HarnessRuntime(
            project_root=ROOT, tool_registry=registry,
            audit_path=Path(self.temp.name) / "audit.jsonl", approval_store=approvals,
        )
        result = harness.invoke_tool(
            principal, run_id="run-h", task_id="task-h",
            tool_id="release.simulation.promote", payload=payload, approval_ref="APR-H",
        )
        self.assertEqual(result, {"ok": True})
        self.assertEqual(len(calls), 1)
        with self.assertRaises(PermissionError):
            harness.invoke_tool(
                principal, run_id="run-h", task_id="task-h",
                tool_id="release.simulation.promote", payload=payload, approval_ref="APR-H",
            )
        self.assertEqual(len(calls), 1)


    def test_harness_marks_reserved_approval_uncertain_when_handler_raises(self):
        approvals = ApprovalStore(self.db)
        self.addCleanup(approvals.close)
        payload = {"releaseId": "rel-fail", "targetEnvironment": "prod"}
        approvals.request(approval_id="APR-fail", run_id="run-f", task_id="task-f",
            tenant_id="tenant-a", tool_id="release.simulation.promote",
            payload=payload, requested_by="requester")
        approvals.decide("APR-fail", decision="approved", actor="approver", reason="reviewed")
        def failing_handler(_payload):
            raise RuntimeError("simulated remote timeout")
        registry = ToolRegistry(ROOT, {"release.simulation.promote": failing_handler})
        harness = HarnessRuntime(project_root=ROOT, tool_registry=registry,
            audit_path=Path(self.temp.name) / "failure-audit.jsonl", approval_store=approvals)
        principal = HarnessPrincipal("executor", "release-coordinator", "tenant-a", "project-a")
        with self.assertRaises(RuntimeError):
            harness.invoke_tool(principal, run_id="run-f", task_id="task-f",
                tool_id="release.simulation.promote", payload=payload, approval_ref="APR-fail")
        self.assertEqual(approvals.get("APR-fail")["status"], "uncertain")

    def test_tool_registry_passes_idempotency_context_to_adapter_handler(self):
        captured = []
        def adapter_handler(payload, context):
            captured.append((payload, context))
            return {"accepted": True}
        registry = ToolRegistry(ROOT, {"documents.read": adapter_handler})
        principal = HarnessPrincipal("principal", "requirement-analyst", "tenant-a", "project-a")
        harness = HarnessRuntime(project_root=ROOT, tool_registry=registry,
            audit_path=Path(self.temp.name) / "context-audit.jsonl")
        result = harness.invoke_tool(principal, run_id="run-context", task_id="task-context",
            tool_id="documents.read", payload={"relativePath": "README.md"}, idempotency_key="idem-context")
        self.assertEqual(result, {"accepted": True})
        self.assertEqual(captured[0][1].run_id, "run-context")
        self.assertEqual(captured[0][1].task_id, "task-context")
        self.assertEqual(captured[0][1].idempotency_key, "idem-context")
        self.assertEqual(len(captured[0][1].payload_sha256), 64)

    def test_tool_gateway_replays_completed_result_without_second_dispatch(self):
        class FakeHarness:
            def __init__(self):
                self.calls = 0
            def invoke_tool(self, principal, **kwargs):
                self.calls += 1
                return {"dispatch": self.calls, "tool": kwargs["tool_id"]}
        harness = FakeHarness()
        ledger = SQLiteInvocationLedger(self.db)
        self.addCleanup(ledger.close)
        gateway = ToolGateway(harness, ledger)
        principal = object()
        args = dict(
            run_id="run", task_id="task", tool_id="documents.write",
            payload={"path": "a.txt", "content": "hello"}, idempotency_key="idem-1",
        )
        first = gateway.invoke(principal, **args)
        second = gateway.invoke(principal, **args)
        self.assertEqual(first, second)
        self.assertEqual(harness.calls, 1)
        with self.assertRaises(InvocationError):
            gateway.invoke(principal, **{**args, "payload": {"path": "a.txt", "content": "changed"}})

    def test_evidence_contract_binds_task_input_tool_and_report(self):
        store = SQLiteTaskStore(Path(self.temp.name) / "tasks.sqlite3")
        self.addCleanup(store.close)
        contract = {
            "contractVersion": "1.0", "runId": "run-e", "taskId": "$TASK_ID",
            "inputSha256": "a" * 64, "toolVersion": "builder@1.2.0",
            "exitCode": 0, "reportSha256": "b" * 64,
        }
        task, _ = store.enqueue(
            task_type="build", payload={"evidenceContract": contract},
            idempotency_key="evidence:1", required_evidence=["build-report"],
        )
        claimed = store.claim("worker", lease_seconds=30)
        self.assertEqual(claimed["payload"]["evidenceContract"]["taskId"], task["id"])
        bad = {
            "type": "build-report", "uri": "artifact://build/report.json",
            "sha256": hashlib.sha256(b"report").hexdigest(),
            "provenance": {"runId": "run-e", "taskId": "wrong",
                "inputSha256": "a" * 64, "toolVersion": "builder@1.2.0",
                "exitCode": 0, "reportSha256": "b" * 64},
        }
        with self.assertRaises(EvidenceContractError):
            store.complete(task["id"], "worker", output={}, evidence=[bad])
        good = {**bad, "provenance": {**bad["provenance"], "taskId": task["id"]}}
        done = store.complete(task["id"], "worker", output={"ok": True}, evidence=[good])
        self.assertEqual(done["status"], "succeeded")


if __name__ == "__main__":
    unittest.main()
