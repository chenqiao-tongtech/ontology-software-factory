"""Configured-origin HTTPS JSON client with bounded response size and no redirects."""
from __future__ import annotations
import json,urllib.error,urllib.parse,urllib.request
from typing import Any,Callable
from ..tool_registry import require_gateway_context

class APIAdapterError(RuntimeError): pass
class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url,code,'redirect refused',headers,fp)

class HTTPSJSONAdapter:
    def __init__(self, base_url:str, *, allowed_hosts:set[str], token_provider:Callable[[],str|None]|None=None, timeout_seconds:float=10, max_response_bytes:int=1_000_000, opener=None, allowed_tool_ids:set[str]|None=None):
        parsed=urllib.parse.urlsplit(base_url)
        if parsed.scheme!='https' or not parsed.hostname or parsed.hostname.lower() not in {x.lower() for x in allowed_hosts}:
            raise ValueError('base_url must be HTTPS and its hostname must be explicitly allow-listed')
        if parsed.username or parsed.password: raise ValueError('credentials must not be embedded in URL')
        self.base_url=base_url.rstrip('/')+'/'; self.host=parsed.hostname.lower(); self.token_provider=token_provider
        self.allowed_tool_ids=set(allowed_tool_ids or set())
        self.timeout=float(timeout_seconds); self.max_response_bytes=int(max_response_bytes)
        if self.timeout<=0 or self.max_response_bytes<1: raise ValueError('timeouts and response limits must be positive')
        self.opener=opener or urllib.request.build_opener(_NoRedirect())
    def request_json(self, method:str, relative_path:str, payload:dict[str,Any]|None=None, *, idempotency_key:str|None=None, invocation_context:object|None=None)->dict[str,Any]:
        if method.upper() != 'GET':
            context = require_gateway_context(invocation_context)
            if context.tool_id not in self.allowed_tool_ids:
                raise ValueError('tool is not allow-listed for this HTTP action connector')
            if not context.idempotency_key:
                raise ValueError('mutating HTTP calls require a Gateway idempotency key')
            if idempotency_key and context.idempotency_key != idempotency_key:
                raise ValueError('idempotency key must match the Gateway invocation context')
            idempotency_key = context.idempotency_key
        if method.upper() not in {'GET','POST','PUT','PATCH','DELETE'}: raise ValueError('unsupported HTTP method')
        rel=urllib.parse.urlsplit(relative_path)
        if rel.scheme or rel.netloc or relative_path.startswith('/') or '..' in rel.path.split('/') or '\\' in relative_path:
            raise ValueError('API path must be relative and cannot traverse directories')
        url=urllib.parse.urljoin(self.base_url,relative_path)
        parsed=urllib.parse.urlsplit(url)
        if parsed.scheme!='https' or parsed.hostname is None or parsed.hostname.lower()!=self.host:
            raise ValueError('request escaped configured HTTPS origin')
        body=None if payload is None else json.dumps(payload,ensure_ascii=False).encode('utf-8')
        headers={'Accept':'application/json'}
        if body is not None: headers['Content-Type']='application/json'
        if idempotency_key:
            if len(idempotency_key)>200 or any(ord(ch)<32 for ch in idempotency_key): raise ValueError('invalid idempotency key')
            headers['Idempotency-Key']=idempotency_key
        if self.token_provider:
            token=self.token_provider()
            if token: headers['Authorization']='Bearer '+token
        request=urllib.request.Request(url,data=body,headers=headers,method=method.upper())
        try:
            with self.opener.open(request,timeout=self.timeout) as response:
                status=int(getattr(response,'status',200))
                raw=response.read(self.max_response_bytes+1)
                if len(raw)>self.max_response_bytes: raise APIAdapterError('API response exceeded configured byte limit')
                if status<200 or status>=300: raise APIAdapterError(f'API returned HTTP {status}')
                try: data=json.loads(raw.decode('utf-8'))
                except (UnicodeDecodeError,json.JSONDecodeError) as exc: raise APIAdapterError('API returned invalid JSON') from exc
                if not isinstance(data,dict): raise APIAdapterError('API response must be a JSON object')
                return data
        except urllib.error.HTTPError as exc:
            raise APIAdapterError(f'API request failed with HTTP {exc.code}; redirects are not followed') from exc
        except urllib.error.URLError as exc:
            raise APIAdapterError(f'API transport failed ({type(exc.reason).__name__})') from exc
