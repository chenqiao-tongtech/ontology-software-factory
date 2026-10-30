import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from ontology_software_factory.e2e_delivery import run_end_to_end
p=argparse.ArgumentParser(description='Run config pipeline, quality gate, release bundle and optional simulated upgrade rehearsal.')
p.add_argument('--request',default='examples/requests/kafka-development.json');p.add_argument('--runs-root',default='.local-runs');p.add_argument('--deliverables',default='deliverables');p.add_argument('--run-id',required=True);p.add_argument('--approved-by');p.add_argument('--approval-reason');p.add_argument('--environment',choices=['test-simulation','staging-simulation'],default='staging-simulation');p.add_argument('--simulate-health-failure',action='store_true');a=p.parse_args()
r=run_end_to_end(a.request,runs_root=a.runs_root,deliverables_root=a.deliverables,run_id=a.run_id,approval_by=a.approved_by,approval_reason=a.approval_reason,rehearsal_environment=a.environment,simulate_health_failure=a.simulate_health_failure);print(json.dumps(r,ensure_ascii=False,indent=2));raise SystemExit(0 if r['status']!='blocked' else 2)
