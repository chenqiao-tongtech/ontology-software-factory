from __future__ import annotations
import argparse,json,re,sys
from pathlib import Path
REQUIRED={'process.roles','node.id','controller.listener.names','controller.quorum.voters','listeners','listener.security.protocol.map','inter.broker.listener.name','num.partitions','default.replication.factor','min.insync.replicas'}
def parse(path:Path):
 values={}; duplicates=[]
 for n,line in enumerate(path.read_text(encoding='utf-8').splitlines(),1):
  s=line.strip()
  if not s or s.startswith('#'): continue
  if '=' not in s: raise ValueError(f'line {n}: expected key=value')
  k,v=s.split('=',1); k=k.strip(); v=v.strip()
  if k in values: duplicates.append(k)
  values[k]=v
 return values,duplicates
def validate(path:Path,profile:str):
 issues=[]
 try: values,dups=parse(path)
 except Exception as e: return {'status':'failed','issues':[{'id':'CFG-PARSE','severity':'blocker','message':str(e)}]}
 for key in sorted(REQUIRED-set(values)): issues.append({'id':'CFG-REQUIRED','severity':'blocker','message':f'missing required property: {key}'})
 for key in sorted(set(dups)): issues.append({'id':'CFG-DUPLICATE','severity':'blocker','message':f'duplicate property: {key}'})
 def integer(name,minimum=1):
  try:
   v=int(values[name])
   if v<minimum: raise ValueError()
   return v
  except Exception:
   issues.append({'id':'CFG-NUMERIC','severity':'blocker','message':f'{name} must be integer >= {minimum}'})
   return None
 node=integer('node.id'); parts=integer('num.partitions'); rf=integer('default.replication.factor'); misr=integer('min.insync.replicas')
 if node is not None and node<0: issues.append({'id':'CFG-NODE','severity':'blocker','message':'node.id must be non-negative'})
 if rf and misr and misr>rf: issues.append({'id':'CFG-ISR','severity':'blocker','message':'min.insync.replicas cannot exceed replication factor'})
 listeners=values.get('listeners','')
 if not listeners: issues.append({'id':'CFG-LISTENER','severity':'blocker','message':'listeners must not be empty'})
 if profile=='production':
  if re.search(r'(?i)(^|[,;])\s*PLAINTEXT\s*://',listeners): issues.append({'id':'SEC-PLAINTEXT','severity':'blocker','message':'production profile cannot expose a PLAINTEXT client listener'})
  if rf is not None and rf<3: issues.append({'id':'SEC-REPLICATION','severity':'blocker','message':'production replication factor must be at least 3'})
  if misr is not None and misr<2: issues.append({'id':'SEC-ISR','severity':'blocker','message':'production min.insync.replicas must be at least 2'})
  if 'SSL' not in values.get('listener.security.protocol.map','') and 'SASL' not in values.get('listener.security.protocol.map',''): issues.append({'id':'SEC-CLIENT-TLS','severity':'blocker','message':'production protocol map must configure SSL or SASL for client access'})
 return {'status':'passed' if not issues else 'failed','profile':profile,'propertyCount':len(values),'issues':issues,'checksRun':['required-properties','duplicate-properties','numeric-ranges']+(['production-security-policy'] if profile=='production' else [])}
def main():
 p=argparse.ArgumentParser();p.add_argument('--config',required=True);p.add_argument('--profile',choices=['development','production'],required=True);p.add_argument('--json-out');a=p.parse_args(); result=validate(Path(a.config),a.profile); rendered=json.dumps(result,ensure_ascii=False,indent=2); print(rendered)
 if a.json_out: Path(a.json_out).write_text(rendered+'\n',encoding='utf-8')
 return 0 if result['status']=='passed' else 1
if __name__=='__main__': raise SystemExit(main())
