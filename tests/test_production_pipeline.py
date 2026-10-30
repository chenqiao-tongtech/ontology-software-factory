import json,tempfile,unittest
from pathlib import Path
from ontology_software_factory.production_pipeline import run_pipeline,PipelineError
ROOT=Path(__file__).resolve().parents[1]
class ProductionPipelineTests(unittest.TestCase):
 def test_development_request_runs_real_validator_and_builds_bundle(self):
  with tempfile.TemporaryDirectory() as d:
   result=run_pipeline(ROOT/'examples/requests/kafka-development.json',d,run_id='pipeline-001')
   self.assertEqual(result['status'],'candidate_built'); self.assertFalse(result['releaseEligible'])
   run=Path(d)/'pipeline-001'; self.assertTrue((run/'candidate-config-bundle.tar.gz').is_file())
   self.assertIn('exitCode',next(s for s in result['stages'] if s['stageId']=='config-validation'))
   self.assertEqual(json.loads((run/'evidence/config-validation.json').read_text())['status'],'passed')
 def test_production_profile_runs_tool_and_output_bundle(self):
  with tempfile.TemporaryDirectory() as d:
   result=run_pipeline(ROOT/'examples/requests/kafka-production.json',d,run_id='pipeline-prod')
   self.assertEqual(result['status'],'candidate_built')
 def test_bad_request_fails_before_run(self):
  with tempfile.TemporaryDirectory() as d:
   req={'requestId':'REQ-BAD','tenantId':'t','summary':'bad','targetProfile':'anything','acceptanceCriteria':[]}
   path=Path(d)/'bad.json'; path.write_text(json.dumps(req))
   with self.assertRaises(PipelineError): run_pipeline(path,Path(d)/'out')
 def test_unsafe_production_config_is_blocked(self):
  import subprocess,sys
  cfg=Path(ROOT/'examples/requests/kafka-production.json')
  with tempfile.TemporaryDirectory() as d:
   bad=Path(d)/'server.properties'; bad.write_text('process.roles=broker,controller\nnode.id=1\ncontroller.listener.names=CONTROLLER\ncontroller.quorum.voters=1@localhost:9093\nlisteners=PLAINTEXT://:9092\nlistener.security.protocol.map=PLAINTEXT:PLAINTEXT\ninter.broker.listener.name=PLAINTEXT\nnum.partitions=3\ndefault.replication.factor=1\nmin.insync.replicas=1\n')
   proc=subprocess.run([sys.executable,str(ROOT/'scripts/validate_kafka_profile.py'),'--config',str(bad),'--profile','production'],capture_output=True,text=True)
   self.assertNotEqual(proc.returncode,0); self.assertIn('SEC-PLAINTEXT',proc.stdout)
if __name__=='__main__': unittest.main()
