"""Small MCP stdio JSON-RPC client for administrator-configured, trusted servers.

The command must come from reviewed deployment configuration, never from an Agent or user input.
This module is a protocol adapter, not a sandbox: use OS/container isolation for untrusted servers.
"""
from __future__ import annotations
import json, os, queue, subprocess, threading, time
from pathlib import Path
from typing import Any
from ..tool_registry import require_gateway_context

class MCPTransportError(RuntimeError): pass

class MCPStdioClient:
    def __init__(self, command: list[str], *, cwd: str | Path, env_allowlist: tuple[str,...]=('PATH','SYSTEMROOT','WINDIR','TMP','TEMP'), timeout: float=10.0, protocol_version: str='2025-06-18'):
        if not command or any(not isinstance(x,str) or not x for x in command):
            raise ValueError('MCP command must be a non-empty string array')
        self.command=list(command); self.cwd=Path(cwd).resolve(); self.timeout=timeout; self.protocol_version=protocol_version
        # Do not pass all process environment variables (especially API keys) to the MCP server.
        self.env={k:os.environ[k] for k in env_allowlist if k in os.environ}
        self.proc: subprocess.Popen[str] | None=None; self._next_id=0; self._lock=threading.Lock(); self._pending: dict[int,queue.Queue]= {}; self._reader_thread=None
    def start(self) -> dict[str, Any]:
        if self.proc is not None: raise MCPTransportError('client already started')
        self.proc=subprocess.Popen(self.command,cwd=self.cwd,env=self.env,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,encoding='utf-8',bufsize=1,shell=False)
        self._reader_thread=threading.Thread(target=self._read_loop,name='mcp-stdio-reader',daemon=True); self._reader_thread.start()
        result=self.request('initialize',{'protocolVersion':self.protocol_version,'capabilities':{},'clientInfo':{'name':'ontology-software-factory','version':'0.1.0'}})
        self.notify('notifications/initialized',{})
        return result
    def _read_loop(self) -> None:
        assert self.proc and self.proc.stdout
        for line in self.proc.stdout:
            try: message=json.loads(line)
            except json.JSONDecodeError: continue
            msg_id=message.get('id')
            if isinstance(msg_id,int) and msg_id in self._pending:
                self._pending[msg_id].put(message)
    def request(self, method: str, params: dict[str,Any] | None=None, *, _gateway_context: object | None = None) -> dict[str,Any]:
        if method == 'tools/call':
            require_gateway_context(_gateway_context)
        if self.proc is None or self.proc.stdin is None: raise MCPTransportError('client is not started')
        with self._lock:
            self._next_id+=1; msg_id=self._next_id; waiter=queue.Queue(maxsize=1); self._pending[msg_id]=waiter
            payload={'jsonrpc':'2.0','id':msg_id,'method':method,'params':params or {}}
            try:
                self.proc.stdin.write(json.dumps(payload,separators=(',',':'))+'\n'); self.proc.stdin.flush()
            except (OSError, BrokenPipeError) as exc:
                self._pending.pop(msg_id,None); raise MCPTransportError('failed to write MCP request') from exc
        try: response=waiter.get(timeout=self.timeout)
        except queue.Empty as exc:
            self._pending.pop(msg_id,None); raise MCPTransportError(f'MCP request timed out: {method}') from exc
        self._pending.pop(msg_id,None)
        if 'error' in response: raise MCPTransportError(f'MCP server returned error for {method}: {response["error"].get("code","unknown")}')
        result=response.get('result')
        if not isinstance(result,dict): raise MCPTransportError(f'invalid MCP response for {method}')
        return result
    def notify(self, method: str, params: dict[str,Any] | None=None) -> None:
        if self.proc is None or self.proc.stdin is None: raise MCPTransportError('client is not started')
        self.proc.stdin.write(json.dumps({'jsonrpc':'2.0','method':method,'params':params or {}},separators=(',',':'))+'\n'); self.proc.stdin.flush()
    def list_tools(self) -> list[dict[str,Any]]:
        result=self.request('tools/list',{})
        tools=result.get('tools')
        if not isinstance(tools,list): raise MCPTransportError('tools/list did not return a tools array')
        return tools
    def call_tool(self, name: str, arguments: dict[str,Any], *, allowed_names: set[str], allowed_tool_ids: set[str], invocation_context: object | None = None) -> dict[str,Any]:
        context = require_gateway_context(invocation_context)
        if context.tool_id not in allowed_tool_ids:
            raise MCPTransportError('tool is not allow-listed for this MCP action connector')
        if context.idempotency_key is None:
            raise MCPTransportError('MCP tool invocation requires a Gateway idempotency key')
        if name not in allowed_names: raise MCPTransportError(f'MCP tool is not allow-listed: {name}')
        return self.request('tools/call',{'name':name,'arguments':arguments},_gateway_context=context)
    def close(self) -> None:
        proc=self.proc; self.proc=None
        if proc is None: return
        try:
            if proc.stdin: proc.stdin.close()
        except OSError: pass
        if proc.poll() is None: proc.terminate()
        try: proc.wait(timeout=2)
        except subprocess.TimeoutExpired: proc.kill(); proc.wait(timeout=2)
        for stream in (proc.stdin, proc.stdout, proc.stderr):
            try:
                if stream is not None and not stream.closed: stream.close()
            except OSError: pass
        if self._reader_thread is not None and self._reader_thread.is_alive(): self._reader_thread.join(timeout=1)
    def __enter__(self): return self
    def __exit__(self,*exc): self.close()
