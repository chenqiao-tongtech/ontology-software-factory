from __future__ import annotations
import argparse,json,sys
from pathlib import Path
SCRIPT_DIR=Path(__file__).resolve().parent
sys.path.insert(0,str(SCRIPT_DIR))
from validate_kafka_profile import validate

def main():
 p=argparse.ArgumentParser(description='Execute candidate-specific assertions against the rendered configuration.')
 p.add_argument('--config',required=True);p.add_argument('--profile',choices=['development','production'],required=True);p.add_argument('--json-out',required=True);a=p.parse_args()
 path=Path(a.config).resolve(); validation=validate(path,a.profile); checks=[]
 checks.append({'id':'TEST-CFG-EXISTS','status':'passed' if path.is_file() else 'failed','message':'candidate file exists'})
 checks.append({'id':'TEST-CONFIG-VALIDATOR','status':'passed' if validation.get('status')=='passed' else 'failed','message':'deterministic profile validator result','details':validation})
 text=path.read_text(encoding='utf-8') if path.is_file() else ''
 required=['node.id=','listeners=','default.replication.factor=','min.insync.replicas=']
 missing=[x for x in required if x not in text]
 checks.append({'id':'TEST-REQUIRED-KEYS','status':'failed' if missing else 'passed','message':'required output keys exist','missing':missing})
 result={'suiteId':'candidate-config-tests','profile':a.profile,'configPath':str(path),'status':'passed' if all(x['status']=='passed' for x in checks) else 'failed','tests':checks}
 target=Path(a.json_out).resolve();target.parent.mkdir(parents=True,exist_ok=True);target.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');print(json.dumps(result,ensure_ascii=False,indent=2));return 0 if result['status']=='passed' else 1
if __name__=='__main__':raise SystemExit(main())
