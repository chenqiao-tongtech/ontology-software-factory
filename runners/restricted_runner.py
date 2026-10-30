from __future__ import annotations
import os,subprocess,sys,time
from dataclasses import dataclass
from pathlib import Path,PurePosixPath

@dataclass
class CommandResult:
    task_id:str; exit_code:int; duration_ms:int; stdout:str; timed_out:bool; argv_display:list[str]

class RestrictedRunnerError(RuntimeError): pass
class RestrictedCommandRunner:
    """A small fixed-command runner, not a kernel/container sandbox."""
    def __init__(self, project_root:str|Path, *, max_output_chars:int=100_000):
        self.root=Path(project_root).resolve(); self.max_output_chars=max_output_chars
    def run(self, task_id:str, workspace:str|Path, *, config_relative_path:str|None=None, profile:str|None=None, timeout_seconds:int=30)->CommandResult:
        workspace=Path(workspace).resolve()
        if not workspace.exists() or not workspace.is_dir(): raise RestrictedRunnerError('workspace must be an existing directory')
        if workspace == self.root or self.root in workspace.parents:  # Workspace must live outside source tree.
            raise RestrictedRunnerError('workspace must be outside the source checkout')
        if timeout_seconds<1 or timeout_seconds>120: raise RestrictedRunnerError('timeout must be between 1 and 120 seconds')
        if task_id=='kafka.config.validate':
            if profile not in {'development','production'}: raise RestrictedRunnerError('profile is required and must be allow-listed')
            posix=PurePosixPath(config_relative_path or '')
            if posix.is_absolute() or not posix.parts or '..' in posix.parts or '\\' in (config_relative_path or ''): raise RestrictedRunnerError('config path must be a safe relative path')
            target=(workspace/Path(*posix.parts)).resolve()
            if workspace not in target.parents or not target.is_file(): raise RestrictedRunnerError('config file is outside workspace or missing')
            argv=[sys.executable,str(self.root/'scripts/validate_kafka_profile.py'),'--config',str(target),'--profile',profile]
        elif task_id=='tests.kafka-profile-regression':
            argv=[sys.executable,'-m','unittest','discover','-s',str(self.root/'tests'),'-p','test_kafka_profile.py','-v']
        else: raise RestrictedRunnerError(f'unknown command task: {task_id}')
        env={'PATH':os.environ.get('PATH',''),'PYTHONIOENCODING':'utf-8','PYTHONUTF8':'1'}
        started=time.monotonic(); timed_out=False
        try:
            proc=subprocess.run(argv,cwd=workspace if task_id=='kafka.config.validate' else self.root,env=env,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf-8',timeout=timeout_seconds,shell=False,check=False)
            code=proc.returncode; out=proc.stdout
        except subprocess.TimeoutExpired as exc:
            timed_out=True; code=124; out=(exc.stdout or '') if isinstance(exc.stdout,str) else ''
            out+='\nRUNNER_TIMEOUT: task exceeded configured timeout'
        return CommandResult(task_id,code,round((time.monotonic()-started)*1000),out[:self.max_output_chars],timed_out,argv)
