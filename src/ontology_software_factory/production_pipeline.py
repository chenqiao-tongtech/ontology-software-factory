from __future__ import annotations
import hashlib,json,os,subprocess,sys,tarfile,time,uuid
from datetime import datetime,timezone
from pathlib import Path
from typing import Any
from jsonschema import Draft202012Validator
ROOT=Path(__file__).resolve().parents[2]
class PipelineError(RuntimeError): pass
def sha256(path:Path)->str:
 h=hashlib.sha256()
 with path.open('rb') as f:
  for chunk in iter(lambda:f.read(1024*1024),b''): h.update(chunk)
 return h.hexdigest()
def _atomic_json(path:Path,obj:Any):
 path.parent.mkdir(parents=True,exist_ok=True); tmp=path.with_suffix(path.suffix+'.tmp'); tmp.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n',encoding='utf-8'); tmp.replace(path)
def run_pipeline(request_path:str|Path,output_root:str|Path,*,run_id:str|None=None)->dict[str,Any]:
 request_path=Path(request_path).resolve(); output_root=Path(output_root).resolve()
 req=json.loads(request_path.read_text(encoding='utf-8')); schema=json.loads((ROOT/'contracts/schemas/production-request.schema.json').read_text(encoding='utf-8'))
 errors=list(Draft202012Validator(schema).iter_errors(req))
 if errors: raise PipelineError('request contract invalid: '+errors[0].message)
 rid=run_id or f'run-{uuid.uuid4().hex[:12]}'
 if not rid.replace('-','').replace('_','').isalnum() or len(rid)>64: raise PipelineError('invalid run_id')
 run_dir=output_root/rid
 run_dir.mkdir(parents=True,exist_ok=False); (run_dir/'candidate').mkdir(); (run_dir/'logs').mkdir(); (run_dir/'evidence').mkdir()
 started=datetime.now(timezone.utc).isoformat(); stages=[]
 try:
  catalog=json.loads((ROOT/'catalog/examples/demo-catalog.json').read_text(encoding='utf-8'))
  product=next(p for p in catalog['products'] if p['id']=='sf:product:event-platform')
  component=next(c for c in catalog['components'] if c['id']=='sf:component:event-broker' and c['lifecycleStatus']=='active')
  if component.get('license',{}).get('reviewStatus')!='approved': raise PipelineError('catalog asset lacks approved licence review metadata')
  version=next(v for v in component['versions'] if v['id']==component['defaultVersionId'] and v['lifecycleStatus']=='active')
  stages.append({'stageId':'asset-selection','status':'passed','assetId':component['id'],'versionId':version['id'],'note':'catalog metadata only; upstream binary not included or verified'})
  over=req.get('overrides',{}); profile=req['targetProfile']
  values={'node_id':1,'listeners':'SSL://:9092,CONTROLLER://:9093' if profile=='production' else 'PLAINTEXT://:9092,CONTROLLER://:9093','listener_protocol_map':'SSL:SSL,PLAINTEXT:PLAINTEXT,CONTROLLER:PLAINTEXT' if profile=='development' else 'SSL:SSL,CONTROLLER:PLAINTEXT','inter_broker_listener':'SSL' if profile=='production' else 'PLAINTEXT','partitions':over.get('partitions',3),'replication_factor':over.get('replicationFactor',3 if profile=='production' else 1),'min_insync_replicas':over.get('minInsyncReplicas',2 if profile=='production' else 1)}
  template=(ROOT/'examples/kafka-standard/base/server.properties.template').read_text(encoding='utf-8')
  for key,value in values.items(): template=template.replace('{{'+key+'}}',str(value))
  cfg=run_dir/'candidate/server.properties'; cfg.write_text(template.strip()+'\n',encoding='utf-8')
  stage={'stageId':'configuration-render','status':'passed','artifact':'candidate/server.properties','sha256':sha256(cfg),'bytes':cfg.stat().st_size}; stages.append(stage)
  validation_path=run_dir/'evidence/config-validation.json'; log_path=run_dir/'logs/config-validation.log'
  argv=[sys.executable,str(ROOT/'scripts/validate_kafka_profile.py'),'--config',str(cfg),'--profile',profile,'--json-out',str(validation_path)]
  env={'PATH':os.environ.get('PATH',''),'PYTHONIOENCODING':'utf-8','PYTHONUTF8':'1'}
  start=time.monotonic(); proc=subprocess.run(argv,cwd=ROOT,env=env,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf-8',timeout=15,shell=False,check=False)
  log_path.write_text(proc.stdout,encoding='utf-8'); stages.append({'stageId':'config-validation','status':'passed' if proc.returncode==0 else 'failed','toolId':'kafka.config.validate','exitCode':proc.returncode,'durationMs':round((time.monotonic()-start)*1000),'log':'logs/config-validation.log','logSha256':sha256(log_path),'evidence':'evidence/config-validation.json'})
  if proc.returncode: raise PipelineError('configuration validation failed; see run evidence')
  # Run a fixed, candidate-specific test tool using a fixed argv (the full regression suite
  # is executed separately by `make test`, not redundantly for every delivery run).
  test_log=run_dir/'logs/candidate-tests.log'; test_json=run_dir/'evidence/candidate-tests.json'
  test_argv=[sys.executable,str(ROOT/'scripts/test_candidate_config.py'),'--config',str(cfg),'--profile',profile,'--json-out',str(test_json)]
  test_start=time.monotonic(); test_proc=subprocess.run(test_argv,cwd=ROOT,env=env,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf-8',timeout=15,shell=False,check=False)
  test_log.write_text(test_proc.stdout,encoding='utf-8')
  _atomic_json(run_dir/'evidence/candidate-test-execution.json',{'suiteId':'candidate-config-tests','status':'passed' if test_proc.returncode==0 else 'failed','exitCode':test_proc.returncode,'durationMs':round((time.monotonic()-test_start)*1000),'logSha256':sha256(test_log),'logPath':'logs/candidate-tests.log'})
  stages.append({'stageId':'candidate-tests','status':'passed' if test_proc.returncode==0 else 'failed','toolId':'tests.run','exitCode':test_proc.returncode,'durationMs':round((time.monotonic()-test_start)*1000),'log':'logs/candidate-tests.log','evidence':'evidence/candidate-test-execution.json'})
  if test_proc.returncode: raise PipelineError('candidate test tool failed; see run evidence')
  # Source revision is recorded only if this checkout actually has Git metadata.
  # Avoid spawning Git in extracted source bundles that intentionally omit .git.
  source_revision=None
  if (ROOT/'.git').exists():
   git_proc=subprocess.run(['git','rev-parse','HEAD'],cwd=ROOT,env=env,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,encoding='utf-8',timeout=3,shell=False,check=False)
   source_revision=git_proc.stdout.strip() if git_proc.returncode==0 and git_proc.stdout.strip() else None
  # A real, deterministic package build of the configuration deliverable, not Kafka itself.
  package=run_dir/'candidate-config-bundle.tar.gz'
  with tarfile.open(package,'w:gz') as tf: tf.add(cfg,arcname='config/server.properties')
  manifest={'runId':rid,'requestId':req['requestId'],'tenantId':req['tenantId'],'targetProfile':profile,'catalogProductId':product['id'],'componentId':component['id'],'versionId':version['id'],'sourceRevision':source_revision,'sourceRevisionStatus':'recorded' if source_revision else 'unavailable-no-git-metadata','candidateTestStatus':'passed','builtAt':datetime.now(timezone.utc).isoformat(),'contents':[{'path':'config/server.properties','sha256':sha256(cfg),'bytes':cfg.stat().st_size}],'packageSha256':sha256(package),'packageBytes':package.stat().st_size,'qualification':'configuration-only; no upstream binary or live cluster validation'}
  _atomic_json(run_dir/'evidence/build-record.json',manifest)
  stages.append({'stageId':'package-build','status':'passed','toolId':'config.bundle.package','artifact':'candidate-config-bundle.tar.gz','sha256':sha256(package),'bytes':package.stat().st_size})
  result={'runId':rid,'status':'candidate_built','startedAt':started,'completedAt':datetime.now(timezone.utc).isoformat(),'request':req,'assetSelection':stages[0],'stages':stages,'packagePath':str(package.relative_to(output_root)),'evidencePaths':['evidence/config-validation.json','evidence/candidate-tests.json','evidence/candidate-test-execution.json','evidence/build-record.json','logs/config-validation.log','logs/candidate-tests.log'],'releaseEligible':False,'note':'Candidate only. Quality/security gates and human approval are separate, later stages.'}
  _atomic_json(run_dir/'run-record.json',result); return result
 except Exception as exc:
  result={'runId':rid,'status':'failed','startedAt':started,'completedAt':datetime.now(timezone.utc).isoformat(),'stages':stages,'errorType':type(exc).__name__,'error':str(exc)[:500],'releaseEligible':False}
  _atomic_json(run_dir/'run-record.json',result)
  raise
