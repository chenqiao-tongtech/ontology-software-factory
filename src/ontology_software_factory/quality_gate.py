from __future__ import annotations
import hashlib,json,os,re,shutil,subprocess,sys
from datetime import datetime,timezone
from pathlib import Path
from typing import Any
ROOT=Path(__file__).resolve().parents[2]
SECRET_PATTERNS=[re.compile(r'(?i)(api[_-]?key|password|secret|token)\s*[:=]\s*["\'][^"\']{6,}["\']'),re.compile(r'sk-[A-Za-z0-9_-]{16,}')]
def sha256(path:Path)->str:
 h=hashlib.sha256()
 with path.open('rb') as f:
  for b in iter(lambda:f.read(65536),b''): h.update(b)
 return h.hexdigest()
def _scanner_has_findings(name:str, report:Any)->bool:
 if name=='gitleaks':
  return isinstance(report,list) and bool(report)
 if name=='trivy' and isinstance(report,dict):
  for result in report.get('Results') or []:
   for vuln in result.get('Vulnerabilities') or []:
    if str(vuln.get('Severity','')).upper() in ('HIGH','CRITICAL'):
     return True
   for misconfig in result.get('Misconfigurations') or []:
    if str(misconfig.get('Severity','')).upper() in ('HIGH','CRITICAL'):
     return True
   for secret in result.get('Secrets') or []:
    if str(secret.get('Severity','')).upper() in ('HIGH','CRITICAL'):
     return True
 return False

def evaluate_quality(run_dir:str|Path, *, catalog_path:str|Path|None=None, policy_path:str|Path|None=None)->dict[str,Any]:
 run_dir=Path(run_dir).resolve(); policy_path=Path(policy_path or ROOT/'policies/quality/quality-gate-policy.json'); policy=json.loads(policy_path.read_text(encoding='utf-8'))
 record_path=run_dir/'evidence/build-record.json'; validation_path=run_dir/'evidence/config-validation.json'; config=run_dir/'candidate/server.properties'; package=run_dir/'candidate-config-bundle.tar.gz'
 checks=[]; findings=[]
 def add(cid,status,detail,severity='info'):
  checks.append({'checkId':cid,'status':status,'detail':detail,'severity':severity})
 if not record_path.is_file() or not validation_path.is_file() or not config.is_file() or not package.is_file():
  add('required-evidence','failed','build record, validation report, config and package are all required','blocker')
 else:
  build=json.loads(record_path.read_text(encoding='utf-8')); validation=json.loads(validation_path.read_text(encoding='utf-8'))
  add('config-structure','passed' if validation.get('status')=='passed' else 'failed',f"validator status={validation.get('status')}",'blocker' if validation.get('status')!='passed' else 'info')
  if validation.get('status')!='passed': findings.extend(validation.get('issues',[]))
  add('artifact-integrity','passed' if sha256(package)==build.get('packageSha256') else 'failed','bundle SHA-256 compared to build record','blocker')
  content=config.read_text(encoding='utf-8')
  secret_hits=[i+1 for i,line in enumerate(content.splitlines()) if any(p.search(line) for p in SECRET_PATTERNS)]
  add('secret-pattern-scan','failed' if secret_hits else 'passed',f'potential credential-like lines={secret_hits}','blocker' if secret_hits else 'info')
 if catalog_path is None: catalog_path=ROOT/'catalog/examples/demo-catalog.json'
 try:
  from ontology_software_factory.catalog import validate_catalog
  errors=validate_catalog(json.loads(Path(catalog_path).read_text(encoding='utf-8')))
  add('catalogue-consistency','passed' if not errors else 'failed',f'catalogue errors={len(errors)}','blocker' if errors else 'info')
  for e in errors: findings.append({'id':'CATALOGUE','severity':'blocker','message':e})
  catalog=json.loads(Path(catalog_path).read_text(encoding='utf-8'))
  active=[c for c in catalog.get('components',[]) if c.get('lifecycleStatus')=='active']
  license_bad=[c.get('id') for c in active if c.get('license',{}).get('reviewStatus')!='approved']
  add('license-review-metadata','failed' if license_bad else 'passed',f'active components without approved metadata={license_bad}','blocker' if license_bad else 'info')
 except Exception as exc: add('catalogue-consistency','failed',f'catalogue validation error: {type(exc).__name__}','blocker')
 build={} if not record_path.exists() else json.loads(record_path.read_text(encoding='utf-8'))
 profile=build.get('targetProfile','development')
 external=[]
 names=['trivy','gitleaks']
 candidate_dir=run_dir/'candidate'
 for name in names:
  scanner_path=shutil.which(name)
  required=profile=='production' and name in policy.get('productionRequiredExternalTools',[])
  item={'tool':name,'status':'not_installed' if not scanner_path else 'available','path':scanner_path,'required':required,'scope':'candidate configuration bundle only'}
  if required and not scanner_path:
   item['status']='incomplete'
   add(f'external-{name}','incomplete',f'required scanner is not installed; production release remains blocked','blocker')
  elif required:
   evidence_dir=run_dir/'evidence'; evidence_dir.mkdir(parents=True,exist_ok=True)
   log_path=run_dir/'logs'/f'{name}.log'; log_path.parent.mkdir(parents=True,exist_ok=True)
   report_path=evidence_dir/f'{name}-report.json'
   if name=='trivy':
    argv=[scanner_path,'fs','--format','json','--output',str(report_path),'--timeout','30s','--exit-code','1','--severity','HIGH,CRITICAL',str(candidate_dir)]
   else:
    argv=[scanner_path,'dir','--report-format','json','--report-path',str(report_path),'--no-banner',str(candidate_dir)]
   env={'PATH':os.environ.get('PATH',''),'HOME':os.environ.get('HOME',''),'TMPDIR':os.environ.get('TMPDIR',''),'LANG':'C.UTF-8'}
   try:
    proc=subprocess.run(argv,cwd=run_dir,env=env,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf-8',errors='replace',timeout=45,shell=False,check=False)
    log_path.write_text(proc.stdout,encoding='utf-8')
    item.update({'exitCode':proc.returncode,'logPath':str(log_path.relative_to(run_dir)),'logSha256':sha256(log_path),'reportPath':str(report_path.relative_to(run_dir)) if report_path.is_file() else None,'reportSha256':sha256(report_path) if report_path.is_file() else None})
    parsed=None
    if report_path.is_file():
     try: parsed=json.loads(report_path.read_text(encoding='utf-8'))
     except (json.JSONDecodeError,UnicodeDecodeError): parsed=None
    if proc.returncode==0 and parsed is not None:
     item['status']='passed'; add(f'external-{name}','passed',f'{name} executed successfully on candidate directory; report SHA-256={item["reportSha256"]}','info')
    elif proc.returncode==1 and parsed is not None and _scanner_has_findings(name,parsed):
     item['status']='failed'; add(f'external-{name}','failed',f'{name} reported findings; inspect {item["reportPath"]}','blocker')
     findings.append({'id':f'{name.upper()}_FINDINGS','severity':'blocker','message':f'{name} reported one or more findings','evidence':item.get('reportPath')})
    else:
     item['status']='incomplete'; add(f'external-{name}','incomplete',f'{name} did not produce a parseable successful report (exit={proc.returncode}); see {item["logPath"]}','blocker')
   except subprocess.TimeoutExpired as exc:
    log_path.write_text((exc.stdout.decode('utf-8','replace') if isinstance(exc.stdout,bytes) else (exc.stdout or ''))+'\nSCANNER_TIMEOUT\n',encoding='utf-8')
    item.update({'status':'incomplete','error':'timeout','logPath':str(log_path.relative_to(run_dir)),'logSha256':sha256(log_path)})
    add(f'external-{name}','incomplete',f'{name} exceeded 45-second time limit','blocker')
   except OSError as exc:
    item.update({'status':'incomplete','error':type(exc).__name__})
    add(f'external-{name}','incomplete',f'{name} execution failed: {type(exc).__name__}','blocker')
  else:
   item['status']='not_run' if profile!='production' else 'incomplete'
   add(f'external-{name}','not_run',f'optional for profile={profile}; scanner is not required by this policy','warning')
  external.append(item)
 blocking=any(c['status']=='failed' and c['severity']=='blocker' for c in checks)
 incomplete=any(c['status'] in ('not_run','available_not_executed') and c.get('severity')=='blocker' for c in checks) or any(x['required'] and x['status']!='passed' for x in external)
 status='blocked' if blocking else ('incomplete' if incomplete else 'passed')
 report={'schemaVersion':'1.0.0','reportId':f'quality-{run_dir.name}','runId':run_dir.name,'profile':profile,'evaluatedAt':datetime.now(timezone.utc).isoformat(),'status':status,'releaseAllowed':status=='passed','policyVersion':policy['policyVersion'],'checks':checks,'findings':findings,'externalTools':external,'limitation':'built-in checks and external Trivy/Gitleaks (when installed) cover the candidate configuration directory only. This is NOT a source-code SAST, full dependency SCA, Kafka binary/container scan, live cluster validation, or legal license review.'}
 out=run_dir/'evidence/quality-gate-report.json'; out.parent.mkdir(parents=True,exist_ok=True); out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 return report


def evaluate_agent_workspace_evidence(
    test_evidence: list[dict[str, Any]], security_evidence: list[dict[str, Any]]
) -> dict[str, Any]:
    """Fail-closed release evidence gate for real Agent candidate workspaces."""
    checks: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    test_runs = [item for item in test_evidence if isinstance(item, dict)
                 and item.get("suiteId") == "python-unit-tests"]
    if not test_runs:
        checks.append({"checkId": "container-python-unit-tests", "status": "incomplete",
                       "detail": "No Python unit-test execution evidence was attached"})
    else:
        test = test_runs[-1]
        passed = (test.get("status") == "passed" and test.get("sandbox") == "docker"
                  and isinstance(test.get("evidence"), dict)
                  and bool(test["evidence"].get("reportSha256")))
        checks.append({"checkId": "container-python-unit-tests",
                       "status": "passed" if passed else "failed" if test.get("status") == "failed" else "incomplete",
                       "detail": f"status={test.get('status')}; sandbox={test.get('sandbox')}"})
        if test.get("status") == "failed":
            findings.append({"id": "UNIT_TEST_FAILURE", "severity": "blocker",
                             "detail": "Container unit test suite failed"})
    for scanner_id in ("semgrep", "gitleaks", "trivy"):
        runs = [item for item in security_evidence if isinstance(item, dict)
                and item.get("scannerId") == scanner_id]
        if not runs:
            checks.append({"checkId": f"container-{scanner_id}", "status": "incomplete",
                           "detail": "No container scanner evidence was attached"})
            continue
        scan = runs[-1]
        passed = (scan.get("status") == "passed" and scan.get("sandbox") == "docker"
                  and isinstance(scan.get("evidence"), dict)
                  and bool(scan["evidence"].get("reportSha256")))
        status = "passed" if passed else "failed" if scan.get("status") == "findings" else "incomplete"
        checks.append({"checkId": f"container-{scanner_id}", "status": status,
                       "detail": f"status={scan.get('status')}; sandbox={scan.get('sandbox')}"})
        if status == "failed":
            findings.append({"id": f"{scanner_id.upper()}_FINDINGS", "severity": "blocker",
                             "detail": f"{scanner_id} reported security findings"})
    blocking = any(item["status"] == "failed" for item in checks)
    incomplete = any(item["status"] == "incomplete" for item in checks)
    status = "blocked" if blocking else "incomplete" if incomplete else "passed"
    return {
        "schemaVersion": "1.0.0",
        "status": status,
        "releaseAllowed": status == "passed",
        "checks": checks,
        "findings": findings,
        "policy": {
            "requiredTestSuite": "python-unit-tests",
            "requiredContainerScanners": ["semgrep", "gitleaks", "trivy"],
            "hostExecutionAccepted": False,
        },
    }
