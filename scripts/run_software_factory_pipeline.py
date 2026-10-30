import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from ontology_software_factory.production_pipeline import run_pipeline
p=argparse.ArgumentParser(description='Run a restricted, real configuration build pipeline (not Kafka binary build).')
p.add_argument('--request',default='examples/requests/kafka-development.json');p.add_argument('--output-root',default='.local-runs');p.add_argument('--run-id')
a=p.parse_args();result=run_pipeline(a.request,a.output_root,run_id=a.run_id);print(json.dumps(result,ensure_ascii=False,indent=2))
