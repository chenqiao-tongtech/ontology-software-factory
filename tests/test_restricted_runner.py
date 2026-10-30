import tempfile,unittest
from pathlib import Path
from runners.restricted_runner import RestrictedCommandRunner,RestrictedRunnerError
ROOT=Path(__file__).resolve().parents[1]
class RestrictedRunnerTests(unittest.TestCase):
 def test_fixed_validator_runs_against_external_workspace(self):
  with tempfile.TemporaryDirectory() as d:
   ws=Path(d); (ws/'server.properties').write_text('process.roles=broker,controller\nnode.id=1\ncontroller.listener.names=CONTROLLER\ncontroller.quorum.voters=1@localhost:9093\nlisteners=PLAINTEXT://:9092,CONTROLLER://:9093\nlistener.security.protocol.map=PLAINTEXT:PLAINTEXT,CONTROLLER:PLAINTEXT\ninter.broker.listener.name=PLAINTEXT\nnum.partitions=3\ndefault.replication.factor=1\nmin.insync.replicas=1\n')
   result=RestrictedCommandRunner(ROOT).run('kafka.config.validate',ws,config_relative_path='server.properties',profile='development')
   self.assertEqual(result.exit_code,0);self.assertFalse(result.timed_out)
 def test_unknown_task_and_path_traversal_rejected(self):
  with tempfile.TemporaryDirectory() as d:
   with self.assertRaises(RestrictedRunnerError): RestrictedCommandRunner(ROOT).run('shell.exec',d)
   (Path(d)/'server.properties').write_text('x=y')
   with self.assertRaises(RestrictedRunnerError): RestrictedCommandRunner(ROOT).run('kafka.config.validate',d,config_relative_path='../etc/passwd',profile='development')
 def test_source_checkout_cannot_be_used_as_workspace(self):
  with self.assertRaises(RestrictedRunnerError): RestrictedCommandRunner(ROOT).run('tests.kafka-profile-regression',ROOT)
if __name__=='__main__':unittest.main()
