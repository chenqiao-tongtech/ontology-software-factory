import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from ontology_software_factory.release_manager import create_release
p=argparse.ArgumentParser();p.add_argument('--run-dir',required=True);p.add_argument('--deliverables',default='deliverables');p.add_argument('--release-id');a=p.parse_args()
print(json.dumps(create_release(a.run_dir,a.deliverables,release_id=a.release_id),ensure_ascii=False,indent=2))
