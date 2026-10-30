import json,tempfile,unittest
from pathlib import Path
from ontology_software_factory.observability import JsonlUsageLedger,calculate_llm_cost,build_observability_report,build_platform_observability_report,create_change_proposal,write_change_proposal
ROOT=Path(__file__).resolve().parents[1]
class ObservabilityTests(unittest.TestCase):
 def test_cost_remains_unknown_when_rate_is_missing(self):
  result=calculate_llm_cost('model-unknown',100,200,{'currency':'USD','modelRates':{}})
  self.assertIsNone(result['estimatedCost']); self.assertEqual(result['costStatus'],'unknown_rate')
 def test_cost_uses_explicit_configured_rates(self):
  result=calculate_llm_cost('demo',1000000,500000,{'currency':'USD','modelRates':{'demo':{'inputUsdPerMillionTokens':2,'outputUsdPerMillionTokens':4}}})
  self.assertEqual(result['estimatedCost'],4.0)
 def test_change_proposal_never_mutates_ontology(self):
  proposal=create_change_proposal(source_run_id='run-1',observed_problem='missing constraint',proposed_change='add validation',affected_asset='ontology/software-factory-ontology.json',owner='domain-owner')
  self.assertFalse(proposal['automaticMutationPerformed']); self.assertEqual(proposal['status'],'proposed')
 def test_jsonl_usage_ledger_sanitizes_fields(self):
  with tempfile.TemporaryDirectory() as d:
   path=Path(d)/'llm-usage.jsonl'; ledger=JsonlUsageLedger(path)
   ledger({'model':'demo','inputTokens':12,'outputTokens':3,'prompt':'secret text','runId':'run-1'})
   event=json.loads(path.read_text().strip()); self.assertEqual(event['inputTokens'],12); self.assertNotIn('prompt',event)
 def test_report_aggregates_pipeline_runs_and_quality(self):
  with tempfile.TemporaryDirectory() as d:
   run=Path(d)/'r1';(run/'evidence').mkdir(parents=True);(run/'run-record.json').write_text(json.dumps({'runId':'r1','status':'candidate_built','request':{'requestId':'REQ-1'},'evidencePaths':['evidence/a.json'],'releaseEligible':False}));(run/'evidence/quality-gate-report.json').write_text(json.dumps({'status':'passed'}))
   report=build_observability_report(d)
   self.assertEqual(report['summary']['totalRuns'],1); self.assertEqual(report['summary']['successRate'],1.0); self.assertIsNone(report['llmUsage']['knownCostTotal'])

 def test_platform_report_aggregates_sanitized_harness_and_connector_audits(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d)
   harness=root/'harness.jsonl'; connector=root/'connector.jsonl'
   harness.write_text(json.dumps({'runId':'r1','taskId':'t1','toolId':'documents.read','status':'succeeded','durationMs':3,'prompt':'must-not-leak'})+chr(10))
   connector.write_text(json.dumps({'sourceId':'s1','connectorId':'source.sqlite','status':'complete','assetCount':4,'location':'/private/path'})+chr(10))
   report=build_platform_observability_report(root,{},harness_audit_path=harness,connector_audit_path=connector)
   self.assertEqual(report['platform']['harnessAudit']['total'],1)
   self.assertEqual(report['platform']['connectorAudit']['byOperation']['source.sqlite'],1)
   self.assertNotIn('prompt',report['platform']['harnessAudit']['recent'][0])
   self.assertNotIn('location',report['platform']['connectorAudit']['recent'][0])
 def test_proposal_refuses_overwrite(self):
  with tempfile.TemporaryDirectory() as d:
   path=Path(d)/'proposal.json';write_change_proposal(path,source_run_id='r1',observed_problem='p',proposed_change='c',affected_asset='a',owner='o')
   with self.assertRaises(FileExistsError): write_change_proposal(path,source_run_id='r2',observed_problem='p',proposed_change='c',affected_asset='a',owner='o')
if __name__=='__main__': unittest.main()
