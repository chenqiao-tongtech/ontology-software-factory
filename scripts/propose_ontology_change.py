import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from ontology_software_factory.observability import write_change_proposal
p=argparse.ArgumentParser();p.add_argument('--out',required=True);p.add_argument('--run-id',required=True);p.add_argument('--problem',required=True);p.add_argument('--proposal',required=True);p.add_argument('--asset',required=True);p.add_argument('--owner',required=True);a=p.parse_args()
r=write_change_proposal(a.out,source_run_id=a.run_id,observed_problem=a.problem,proposed_change=a.proposal,affected_asset=a.asset,owner=a.owner);print(json.dumps(r,ensure_ascii=False,indent=2))
