from __future__ import annotations

import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import importlib.util

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "run_factory_portal.py"
SPEC = importlib.util.spec_from_file_location("factory_portal_governance_api", SCRIPT)
portal = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(portal)


class OntologyGovernanceApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.originals = {name: getattr(portal, name) for name in ("STATE_DIR", "STATE_PATH", "SOURCES_PATH", "FORMAL_ONTOLOGY")}
        portal.STATE_DIR = self.base / ".state"
        portal.STATE_PATH = portal.STATE_DIR / "state.json"
        portal.SOURCES_PATH = self.base / "sources.json"
        portal.FORMAL_ONTOLOGY = self.base / "ontology.json"
        self._write_ontology("1.0.0", ["Requirement", "Artifact"])
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), portal.PortalHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        for name, value in self.originals.items():
            setattr(portal, name, value)
        self.tmp.cleanup()

    def _write_ontology(self, version, classes):
        value = {
            "ontologyId": "test-ontology", "ontologyVersion": version, "schemaVersion": "1.0.0",
            "classes": [{"name": name} for name in classes], "relations": [],
            "controlledVocabularies": {}, "mvpInvariants": [],
            "operationalExtensions": {"classes": [], "relations": []},
        }
        portal.FORMAL_ONTOLOGY.write_text(json.dumps(value), encoding="utf-8")

    def _request(self, method, path, payload=None, expected=200):
        data = json.dumps(payload).encode() if payload is not None else None
        req = Request(self.base_url + path, data=data, method=method,
                      headers={"Content-Type": "application/json"} if data else {})
        try:
            with urlopen(req, timeout=4) as response:
                status, raw = response.status, response.read()
        except HTTPError as exc:
            status, raw = exc.code, exc.read()
        self.assertEqual(status, expected, raw.decode("utf-8"))
        return json.loads(raw.decode("utf-8")) if raw else {}

    def _snapshot(self, reason):
        data = self._request("POST", "/api/ontology/versions/snapshot",
                             {"actor": "maintainer", "reason": reason}, 201)
        return data["snapshot"]["snapshotId"]

    def _proposal(self, snapshot_id, action="promote"):
        data = self._request("POST", "/api/ontology/governance/proposals", {
            "snapshotId": snapshot_id, "action": action,
            "actor": "requester", "reason": "controlled ontology release",
        }, 201)
        return data["proposal"]["proposalId"]

    def _approve(self, proposal_id, *, actor="reviewer", accept=False):
        return self._request("POST", f"/api/ontology/governance/proposals/{proposal_id}/decision", {
            "actor": actor, "decision": "approve", "notes": "reviewed",
            "acceptBreakingChanges": accept,
        })

    def test_promotion_requires_independent_approval_and_execution(self):
        first = self._snapshot("initial baseline")
        proposal = self._proposal(first)
        self._request("POST", f"/api/ontology/governance/proposals/{proposal}/decision", {
            "actor": "requester", "decision": "approve", "notes": "self approval",
        }, 400)
        self._approve(proposal)
        self._request("POST", f"/api/ontology/governance/proposals/{proposal}/execute", {"actor": "reviewer", "reason": "same as approver"}, 400)
        result = self._request("POST", f"/api/ontology/governance/proposals/{proposal}/execute", {"actor": "executor", "reason": "activate reviewed baseline"})
        self.assertEqual(result["activeSnapshotId"], first)
        self.assertFalse(result["release"]["formalFileModified"])
        governance = self._request("GET", "/api/ontology/governance")
        self.assertEqual(governance["activeSnapshot"]["snapshotId"], first)

    def test_rollback_requires_explicit_acceptance_of_downgrade_risk(self):
        first = self._snapshot("baseline")
        first_proposal = self._proposal(first)
        self._approve(first_proposal)
        self._request("POST", f"/api/ontology/governance/proposals/{first_proposal}/execute", {"actor": "executor", "reason": "activate baseline"})
        self._write_ontology("1.1.0", ["Requirement", "Artifact", "Release"])
        second = self._snapshot("additive release")
        second_proposal = self._proposal(second)
        self._approve(second_proposal)
        self._request("POST", f"/api/ontology/governance/proposals/{second_proposal}/execute", {"actor": "executor", "reason": "activate additive version"})
        rollback = self._proposal(first, action="rollback")
        self._request("POST", f"/api/ontology/governance/proposals/{rollback}/decision", {
            "actor": "reviewer", "decision": "approve", "notes": "rollback review",
            "acceptBreakingChanges": False,
        }, 400)
        self._approve(rollback, accept=True)
        result = self._request("POST", f"/api/ontology/governance/proposals/{rollback}/execute", {"actor": "executor", "reason": "restore previous snapshot"})
        self.assertEqual(result["activeSnapshotId"], first)
        self.assertEqual(result["release"]["action"], "rollback")

    def test_promotion_cannot_override_missing_major_version_bump(self):
        first = self._snapshot("baseline")
        first_proposal = self._proposal(first)
        self._approve(first_proposal)
        self._request("POST", f"/api/ontology/governance/proposals/{first_proposal}/execute", {"actor": "executor", "reason": "activate baseline"})
        self._write_ontology("1.1.0", ["Requirement"])
        second = self._snapshot("breaking change without major bump")
        proposal = self._proposal(second)
        self._request("POST", f"/api/ontology/governance/proposals/{proposal}/decision", {
            "actor": "reviewer", "decision": "approve", "notes": "trying to override version rule",
            "acceptBreakingChanges": True,
        }, 400)

    def test_stale_proposal_cannot_overwrite_new_active_pointer(self):
        first = self._snapshot("baseline")
        proposal = self._proposal(first)
        self._approve(proposal)
        # A newer activation invalidates this proposal's expected-active pointer.
        state = portal.state_read()
        state["activeOntologySnapshotId"] = "different-snapshot"
        portal.dump(portal.STATE_PATH, state)
        self._request("POST", f"/api/ontology/governance/proposals/{proposal}/execute", {"actor": "executor", "reason": "stale execution"}, 400)


if __name__ == "__main__":
    unittest.main()
