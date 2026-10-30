import tempfile
import unittest
from pathlib import Path
from scripts.validate_kafka_profile import validate

class KafkaProfileValidatorTests(unittest.TestCase):
    def _write(self, content):
        temp = tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', delete=False)
        temp.write(content)
        temp.close()
        self.addCleanup(lambda: Path(temp.name).unlink(missing_ok=True))
        return Path(temp.name)

    def test_development_profile_accepts_explicit_listener_and_replication(self):
        path = self._write('''process.roles=broker,controller\nnode.id=1\ncontroller.listener.names=CONTROLLER\ncontroller.quorum.voters=1@localhost:9093\nlisteners=PLAINTEXT://:9092,CONTROLLER://:9093\nlistener.security.protocol.map=PLAINTEXT:PLAINTEXT,CONTROLLER:PLAINTEXT\ninter.broker.listener.name=PLAINTEXT\nnum.partitions=3\ndefault.replication.factor=1\nmin.insync.replicas=1\n''')
        self.assertEqual(validate(path, 'development')['status'], 'passed')

    def test_production_profile_rejects_plaintext(self):
        path = self._write('''process.roles=broker,controller\nnode.id=1\ncontroller.listener.names=CONTROLLER\ncontroller.quorum.voters=1@localhost:9093\nlisteners=PLAINTEXT://:9092\nlistener.security.protocol.map=PLAINTEXT:PLAINTEXT\ninter.broker.listener.name=PLAINTEXT\nnum.partitions=3\ndefault.replication.factor=3\nmin.insync.replicas=2\n''')
        result = validate(path, 'production')
        self.assertEqual(result['status'], 'failed')
        self.assertIn('SEC-PLAINTEXT', [x['id'] for x in result['issues']])

    def test_duplicate_property_is_rejected(self):
        path = self._write('''process.roles=broker,controller\nnode.id=1\nnode.id=2\ncontroller.listener.names=CONTROLLER\ncontroller.quorum.voters=1@localhost:9093\nlisteners=PLAINTEXT://:9092\nlistener.security.protocol.map=PLAINTEXT:PLAINTEXT\ninter.broker.listener.name=PLAINTEXT\nnum.partitions=3\ndefault.replication.factor=1\nmin.insync.replicas=1\n''')
        self.assertEqual(validate(path, 'development')['status'], 'failed')

if __name__ == '__main__': unittest.main()
