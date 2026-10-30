from __future__ import annotations
import json
from datetime import datetime,timezone
from pathlib import Path
from typing import Any
from .production_pipeline import run_pipeline
from .quality_gate import evaluate_quality
from .release_manager import create_release,rehearse_upgrade

def run_end_to_end(request_path:str|Path, *, runs_root:str|Path, deliverables_root:str|Path, run_id:str, approval_by:str|None=None, approval_reason:str|None=None, rehearsal_environment:str='staging-simulation', simulate_health_failure:bool=False)->dict[str,Any]:
 pipeline=run_pipeline(request_path,runs_root,run_id=run_id)
 run_dir=Path(runs_root).resolve()/run_id
 gate=evaluate_quality(run_dir)
 result={'runId':run_id,'startedAt':pipeline['startedAt'],'completedAt':datetime.now(timezone.utc).isoformat(),'pipelineStatus':pipeline['status'],'qualityGateStatus':gate['status'],'releaseAllowed':gate['releaseAllowed'],'release':None,'rehearsal':None,'status':'blocked' if not gate['releaseAllowed'] else 'release_candidate_ready'}
 if gate['releaseAllowed']:
  release=create_release(run_dir,deliverables_root,release_id=f'rel-{run_id}')
  result['release']=release
  if approval_by and approval_reason:
   result['rehearsal']=rehearse_upgrade(Path(deliverables_root).resolve()/'.environment-state.json',Path(deliverables_root).resolve()/f"{release['releaseId']}.release-record.json",approved_by=approval_by,approval_reason=approval_reason,target_environment=rehearsal_environment,simulate_health_failure=simulate_health_failure)
   result['status']=result['rehearsal']['outcome']
 _write=run_dir/'evidence/e2e-report.json'; _write.parent.mkdir(parents=True,exist_ok=True); _write.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 return result
