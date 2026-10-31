import tempfile,unittest
from pathlib import Path
from ontology_software_factory.tool_registry import ToolRegistry,ToolPolicyError
ROOT=Path(__file__).resolve().parents[1]
class ToolRegistryTests(unittest.TestCase):
 def test_effective_tools_intersection_and_handler(self):
  registry=ToolRegistry(ROOT,{'catalog.read':lambda payload:{'ok':True}})
  self.assertIn('catalog.read',registry.effective_tools('requirement-analyst'))
  self.assertEqual(registry.invoke('requirement-analyst','catalog.read',{'catalogPath':'catalog/examples/demo-catalog.json'}),{'ok':True})
 def test_boolean_cannot_forge_high_impact_approval(self):
  registry=ToolRegistry(ROOT,{'release.simulation.promote':lambda p:'promoted'})
  with self.assertRaises(ToolPolicyError): registry.invoke('requirement-analyst','release.simulation.promote',{'releaseId':'r1','targetEnvironment':'prod'},_approval_grant=True)
 def test_high_impact_needs_approval(self):
  registry=ToolRegistry(ROOT,{'release.simulation.promote':lambda p:'promoted'})
  with self.assertRaises(ToolPolicyError): registry.invoke('release-coordinator','release.simulation.promote',{'releaseId':'r1','targetEnvironment':'prod'})
  with self.assertRaises(ToolPolicyError): registry.invoke('release-coordinator','release.simulation.promote',{'releaseId':'r1','targetEnvironment':'prod'},_approval_grant=True)
 def test_tool_input_schema_enforced(self):
  registry=ToolRegistry(ROOT,{'catalog.read':lambda p:p})
  with self.assertRaises(ValueError): registry.invoke('requirement-analyst','catalog.read',{'unexpected':True})
if __name__=='__main__': unittest.main()
