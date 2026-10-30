import sys,unittest
from pathlib import Path
from ontology_software_factory.adapters.mcp_stdio import MCPStdioClient,MCPTransportError
ROOT=Path(__file__).resolve().parents[1]
class MCPStdioTests(unittest.TestCase):
 def test_initialize_list_and_call_allowlisted_tool(self):
  cmd=[sys.executable,str(ROOT/'tests/fixtures/fake_mcp_server.py')]
  with MCPStdioClient(cmd,cwd=ROOT,timeout=2) as client:
   init=client.start(); self.assertEqual(init['serverInfo']['name'],'fixture')
   self.assertEqual(client.list_tools()[0]['name'],'echo')
   result=client.call_tool('echo',{'x':1},allowed_names={'echo'})
   self.assertFalse(result['isError'])
 def test_tool_not_allowlisted_is_blocked(self):
  cmd=[sys.executable,str(ROOT/'tests/fixtures/fake_mcp_server.py')]
  with MCPStdioClient(cmd,cwd=ROOT,timeout=2) as client:
   client.start()
   with self.assertRaises(MCPTransportError): client.call_tool('exec',{},allowed_names={'echo'})
if __name__=='__main__': unittest.main()
