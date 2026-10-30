import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from ontology_software_factory.release_manager import rehearse_upgrade
p=argparse.ArgumentParser();p.add_argument('--state',default='.local-environments/staging.json');p.add_argument('--release-record',required=True);p.add_argument('--approved-by',required=True);p.add_argument('--reason',required=True);p.add_argument('--environment',choices=['test-simulation','staging-simulation'],default='staging-simulation');p.add_argument('--simulate-health-failure',action='store_true');a=p.parse_args()
r=rehearse_upgrade(a.state,a.release_record,approved_by=a.approved_by,approval_reason=a.reason,target_environment=a.environment,simulate_health_failure=a.simulate_health_failure);print(json.dumps(r,ensure_ascii=False,indent=2))
