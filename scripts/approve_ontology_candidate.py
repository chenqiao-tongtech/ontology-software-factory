#!/usr/bin/env python3
"""Record human approval of a candidate digest and create a versioned change proposal.

This command never modifies the authoritative ontology file. The caller is responsible
for authenticating the reviewer and protecting the approval record in an enterprise setup.
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from ontology_software_factory.ontology_discovery import approve_candidate, candidate_digest  # noqa: E402


def main() -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", required=True, type=Path)
    parser.add_argument("--reviewer-id", required=True)
    parser.add_argument("--approval-ref", required=True, help="Ticket/approval record reference in the real approval system")
    parser.add_argument("--expected-digest", required=True, help="Digest shown to the reviewer; prevents approval of changed content")
    parser.add_argument("--output-root", type=Path, default=ROOT/".local-runs/ontology-change-proposals")
    args=parser.parse_args()
    try:
        candidate=json.loads(args.candidate.read_text(encoding="utf-8"))
        actual=candidate_digest(candidate)
        if actual != args.expected_digest:
            raise ValueError("candidate digest differs from the reviewer-confirmed digest")
        approved=approve_candidate(candidate, reviewer_id=args.reviewer_id, approval_ref=args.approval_ref,
                                  expected_digest=args.expected_digest)
        root=args.output_root.resolve(); root.mkdir(parents=True,exist_ok=True)
        target=root/f"{approved['candidateId']}.approved-candidate.json"
        if target.exists():
            existing=json.loads(target.read_text(encoding="utf-8"))
            if candidate_digest(existing) != candidate_digest(approved):
                raise ValueError("approved candidate path already exists with different content")
        else:
            target.write_text(json.dumps(approved,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        proposal={
            "proposalId": f"oprop-{approved['candidateId'][6:]}",
            "proposalVersion": "1.0.0",
            "candidateId": approved["candidateId"],
            "candidateDigest": approved["candidateDigest"],
            "approval": approved["approval"],
            "status": "approved_change_proposal",
            "productionOntologyMutation": False,
            "requiresSemanticRegression": True,
            "requiresVersionedPullRequest": True,
            "affectedTargets": ["ontology/software-factory-ontology.json", "contracts/schemas/", "agents/", "skills/", "workflows/", "policies/"],
            "candidatePath": str(target),
        }
        proposal_path=root/f"{proposal['proposalId']}.proposal.json"
        if proposal_path.exists():
            raise ValueError("change proposal file already exists; refusing overwrite")
        proposal_path.write_text(json.dumps(proposal,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        print(json.dumps({"approvedCandidatePath":str(target),"proposalPath":str(proposal_path),
                          "candidateDigest":approved["candidateDigest"],"status":proposal["status"],
                          "productionOntologyMutation":False},ensure_ascii=False,indent=2))
        return 0
    except Exception as exc:
        print(f"Ontology candidate approval failed closed: {type(exc).__name__}: {exc}",file=sys.stderr)
        return 2

if __name__=="__main__":
    raise SystemExit(main())
