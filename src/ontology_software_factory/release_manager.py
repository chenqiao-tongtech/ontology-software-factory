from __future__ import annotations
import hashlib,json,shutil,tarfile,uuid,zipfile
from datetime import datetime,timezone
from pathlib import Path
from typing import Any
ROOT=Path(__file__).resolve().parents[2]
class ReleaseError(RuntimeError): pass
def sha256(path:Path)->str:
 h=hashlib.sha256()
 with path.open('rb') as f:
  for b in iter(lambda:f.read(65536),b''): h.update(b)
 return h.hexdigest()
def _atomic(path:Path,obj:Any):
 path.parent.mkdir(parents=True,exist_ok=True); tmp=path.with_suffix(path.suffix+'.tmp'); tmp.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n',encoding='utf-8'); tmp.replace(path)
def create_release(run_dir:str|Path, deliverables_root:str|Path, *, release_id:str|None=None)->dict[str,Any]:
 run_dir=Path(run_dir).resolve(); deliverables_root=Path(deliverables_root).resolve(); quality_path=run_dir/'evidence/quality-gate-report.json'; build_path=run_dir/'evidence/build-record.json'
 if not quality_path.is_file() or not build_path.is_file(): raise ReleaseError('quality gate and build record are required')
 quality=json.loads(quality_path.read_text(encoding='utf-8')); build=json.loads(build_path.read_text(encoding='utf-8'))
 if quality.get('status')!='passed' or quality.get('releaseAllowed') is not True: raise ReleaseError('quality gate did not allow release')
 if quality.get('runId')!=run_dir.name or build.get('runId')!=run_dir.name: raise ReleaseError('run IDs do not match release inputs')
 cfg=run_dir/'candidate/server.properties'; package=run_dir/'candidate-config-bundle.tar.gz'
 if not cfg.is_file() or not package.is_file() or sha256(package)!=build.get('packageSha256'): raise ReleaseError('candidate package integrity mismatch')
 rid=release_id or f'rel-{uuid.uuid4().hex[:12]}'
 if not rid.replace('-','').isalnum() or len(rid)>64: raise ReleaseError('invalid release ID')
 folder=deliverables_root/rid
 if folder.exists(): raise ReleaseError('release directory already exists')
 folder.mkdir(parents=True)
 shutil.copy2(cfg,folder/'server.properties'); shutil.copy2(quality_path,folder/'quality-gate-report.json'); shutil.copy2(build_path,folder/'build-record.json'); shutil.copy2(run_dir/'evidence/config-validation.json',folder/'config-validation.json')
 # SBOM describes the delivered configuration bundle itself; upstream Kafka binary is not bundled.
 sbom={'bomFormat':'CycloneDX','specVersion':'1.5','version':1,'metadata':{'timestamp':datetime.now(timezone.utc).isoformat(),'component':{'type':'application','name':'kafka-configuration-delivery-bundle','version':'1.0.0','description':'Configuration-only example; no Kafka runtime binary included.'}},'components':[{'type':'file','name':'server.properties','version':'1','hashes':[{'alg':'SHA-256','content':sha256(cfg)}],'properties':[{'name':'delivery:purpose','value':'configuration-only'}]}],'dependencies':[]}
 _atomic(folder/'sbom.cdx.json',sbom)
 files=[]
 for p in sorted(folder.rglob('*')):
  if p.is_file(): files.append({'path':p.relative_to(folder).as_posix(),'sha256':sha256(p),'bytes':p.stat().st_size})
 manifest={'schemaVersion':'1.0.0','releaseId':rid,'runId':run_dir.name,'requestId':build.get('requestId'),'tenantId':build.get('tenantId'),'targetProfile':build.get('targetProfile'),'createdAt':datetime.now(timezone.utc).isoformat(),'componentVersionId':build.get('versionId'),'sourceRevision':build.get('sourceRevision'),'bundleType':'configuration-only','files':files,'qualityGateReportSha256':sha256(folder/'quality-gate-report.json'),'sbom':'sbom.cdx.json','promotionStatus':'candidate','deploymentPerformed':False}
 _atomic(folder/'release-manifest.json',manifest)
 archive=deliverables_root/f'{rid}.zip'
 with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED) as zf:
  for p in sorted(folder.rglob('*')):
   if p.is_file(): zf.write(p,p.relative_to(folder).as_posix())
 record={'releaseId':rid,'runId':run_dir.name,'status':'candidate','bundlePath':str(archive),'bundleSha256':sha256(archive),'bundleBytes':archive.stat().st_size,'manifestPath':str(folder/'release-manifest.json'),'deploymentPerformed':False,'qualification':'configuration-only candidate; no live Kafka compatibility claim'}
 _atomic(deliverables_root/f'{rid}.release-record.json',record); return record

def rehearse_upgrade(state_path:str|Path, release_record_path:str|Path, *, approved_by:str, approval_reason:str, target_environment:str='staging-simulation', simulate_health_failure:bool=False)->dict[str,Any]:
 if not approved_by.strip() or not approval_reason.strip(): raise ReleaseError('independent approver and reason are required')
 if target_environment not in {'test-simulation','staging-simulation'}: raise ReleaseError('this reference tool never deploys to production or external environments')
 record=json.loads(Path(release_record_path).read_text(encoding='utf-8'))
 if record.get('status')!='candidate' or record.get('deploymentPerformed') is not False: raise ReleaseError('release must be an unpromoted candidate')
 archive=Path(record['bundlePath']).resolve()
 if not archive.is_file() or sha256(archive)!=record.get('bundleSha256'): raise ReleaseError('release package hash mismatch')
 state_path=Path(state_path).resolve(); state_path.parent.mkdir(parents=True,exist_ok=True)
 previous=json.loads(state_path.read_text(encoding='utf-8')) if state_path.exists() else {'currentReleaseId':None,'revision':0,'health':'unknown'}
 backup=state_path.with_suffix(state_path.suffix+'.rollback-backup'); _atomic(backup,previous)
 now=datetime.now(timezone.utc).isoformat()
 if simulate_health_failure:
  # Simulate failed post-upgrade health check and restore the previous state atomically.
  _atomic(state_path,previous); outcome='rolled_back'
 else:
  new_state={'currentReleaseId':record['releaseId'],'revision':int(previous.get('revision',0))+1,'health':'passed','updatedAt':now,'targetEnvironment':target_environment}
  _atomic(state_path,new_state); outcome='upgrade_rehearsal_passed'
 result={'rehearsalId':f'rehearsal-{uuid.uuid4().hex[:10]}','releaseId':record['releaseId'],'targetEnvironment':target_environment,'approvedBy':approved_by,'approvalReason':approval_reason,'approvedAt':now,'outcome':outcome,'before':previous,'after':json.loads(state_path.read_text(encoding='utf-8')),'rollbackBackupPath':str(backup),'realDeploymentPerformed':False,'note':'Local state-machine rehearsal only; no real service, cluster or Kafka node was changed.'}
 _atomic(state_path.parent/f'{result["rehearsalId"]}.json',result); return result
