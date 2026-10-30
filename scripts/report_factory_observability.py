import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from ontology_software_factory.observability import build_observability_report
p=argparse.ArgumentParser();p.add_argument('--runs-root',default='.local-runs');p.add_argument('--rates',default='observability/config/model-rates.example.json');p.add_argument('--out',default='observability/reports/latest.json');a=p.parse_args()
r=build_observability_report(a.runs_root,a.rates);o=Path(a.out);o.parent.mkdir(parents=True,exist_ok=True);o.write_text(json.dumps(r,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');print(json.dumps(r,ensure_ascii=False,indent=2))
