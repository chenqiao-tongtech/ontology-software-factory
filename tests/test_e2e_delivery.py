import tempfile,unittest
from pathlib import Path
from ontology_software_factory.e2e_delivery import run_end_to_end
ROOT=Path(__file__).resolve().parents[1]
class E2EDeliveryTests(unittest.TestCase):
 def test_development_request_flows_to_candidate_release_without_deploy(self):
  with tempfile.TemporaryDirectory() as d:
   r=run_end_to_end(ROOT/'examples/requests/kafka-development.json',runs_root=Path(d)/'runs',deliverables_root=Path(d)/'deliverables',run_id='e2e-001')
   self.assertEqual(r['status'],'release_candidate_ready');self.assertTrue(r['release'])
   self.assertFalse(r['release']['deploymentPerformed']);self.assertIsNone(r['rehearsal'])
   self.assertTrue((Path(d)/'runs/e2e-001/evidence/e2e-report.json').is_file())
 def test_production_flow_fails_closed_when_external_scanner_evidence_missing(self):
  with tempfile.TemporaryDirectory() as d:
   r=run_end_to_end(ROOT/'examples/requests/kafka-production.json',runs_root=Path(d)/'runs',deliverables_root=Path(d)/'deliverables',run_id='e2e-prod')
   self.assertEqual(r['status'],'blocked');self.assertIsNone(r['release'])
 def test_approved_simulation_rehearsal_rolls_back_on_health_failure(self):
  with tempfile.TemporaryDirectory() as d:
   r=run_end_to_end(ROOT/'examples/requests/kafka-development.json',runs_root=Path(d)/'runs',deliverables_root=Path(d)/'deliverables',run_id='e2e-rollback',approval_by='reviewer',approval_reason='rehearsal',simulate_health_failure=True)
   self.assertEqual(r['status'],'rolled_back');self.assertFalse(r['rehearsal']['realDeploymentPerformed'])
if __name__=='__main__':unittest.main()
