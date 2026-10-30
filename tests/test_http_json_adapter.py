import io,json,unittest
from types import SimpleNamespace
from ontology_software_factory.adapters.http_json import HTTPSJSONAdapter,APIAdapterError
class FakeResponse:
 def __init__(self,body,status=200): self.body=body;self.status=status
 def read(self,n=-1): return self.body[:n]
 def __enter__(self): return self
 def __exit__(self,*a): pass
class FakeOpener:
 def __init__(self,response): self.response=response;self.request=None;self.timeout=None
 def open(self,request,timeout): self.request=request;self.timeout=timeout;return self.response
class HTTPJSONAdapterTests(unittest.TestCase):
 def test_https_allowlist_and_idempotency_header(self):
  opener=FakeOpener(FakeResponse(b'{"ok":true}')); adapter=HTTPSJSONAdapter('https://api.example.invalid/v1',allowed_hosts={'api.example.invalid'},token_provider=lambda:'short-token',opener=opener)
  self.assertEqual(adapter.request_json('POST','tasks',{'x':1},idempotency_key='task-1'),{'ok':True})
  self.assertEqual(opener.request.get_header('Authorization'),'Bearer short-token'); self.assertEqual(opener.request.get_header('Idempotency-key'),'task-1')
 def test_reject_http_and_unapproved_hosts(self):
  with self.assertRaises(ValueError): HTTPSJSONAdapter('http://api.example.invalid',allowed_hosts={'api.example.invalid'})
  with self.assertRaises(ValueError): HTTPSJSONAdapter('https://other.example.invalid',allowed_hosts={'api.example.invalid'})
 def test_path_traversal_and_absolute_url_rejected(self):
  adapter=HTTPSJSONAdapter('https://api.example.invalid/v1',allowed_hosts={'api.example.invalid'},opener=FakeOpener(FakeResponse(b'{}')))
  for path in ('../admin','https://evil.invalid/a','/admin'):
   with self.subTest(path=path),self.assertRaises(ValueError): adapter.request_json('GET',path)
 def test_response_byte_limit_fails_closed(self):
  adapter=HTTPSJSONAdapter('https://api.example.invalid/v1',allowed_hosts={'api.example.invalid'},max_response_bytes=3,opener=FakeOpener(FakeResponse(b'{"ok":true}')))
  with self.assertRaises(APIAdapterError): adapter.request_json('GET','health')
if __name__=='__main__':unittest.main()
