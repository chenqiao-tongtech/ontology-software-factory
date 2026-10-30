import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from ontology_software_factory.quality_gate import evaluate_quality
p=argparse.ArgumentParser(description='Evaluate release gates for a local configuration-only run.')
p.add_argument('--run-dir',required=True);p.add_argument('--catalog',default='catalog/examples/demo-catalog.json');a=p.parse_args()
r=evaluate_quality(a.run_dir,catalog_path=a.catalog);print(json.dumps(r,ensure_ascii=False,indent=2));raise SystemExit(0 if r['status']=='passed' else 2)
