from __future__ import annotations
import json,uuid,threading
from datetime import datetime,timezone
from pathlib import Path
from typing import Any

def _read_json(path:Path,default=None):
 try: return json.loads(path.read_text(encoding='utf-8'))
 except (OSError,json.JSONDecodeError): return default

def _iso_now(): return datetime.now(timezone.utc).isoformat()

class JsonlUsageLedger:
    """Append sanitized LLM usage events; never accepts prompt or response contents."""
    def __init__(self, path: str | Path):
        self.path = Path(path).resolve()
        self._lock = threading.Lock()
    def __call__(self, event: dict[str, Any]) -> None:
        allowed = {"occurredAt","provider","model","responseId","latencyMs","attemptCount","inputTokens","outputTokens","runId","stageId"}
        sanitized = {key: event.get(key) for key in allowed if key in event}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(sanitized, ensure_ascii=False, separators=(",", ":")) + "\n"
        with self._lock:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(line)
                handle.flush()

def calculate_llm_cost(model:str,input_tokens:int,output_tokens:int,rates:dict[str,Any])->dict[str,Any]:
 rate=rates.get('modelRates',{}).get(model)
 if not isinstance(rate,dict) or rate.get('inputUsdPerMillionTokens') is None or rate.get('outputUsdPerMillionTokens') is None:
  return {'model':model,'inputTokens':input_tokens,'outputTokens':output_tokens,'currency':rates.get('currency','USD'),'estimatedCost':None,'costStatus':'unknown_rate'}
 cost=(input_tokens*float(rate['inputUsdPerMillionTokens'])+output_tokens*float(rate['outputUsdPerMillionTokens']))/1_000_000
 return {'model':model,'inputTokens':input_tokens,'outputTokens':output_tokens,'currency':rates.get('currency','USD'),'estimatedCost':round(cost,8),'costStatus':'estimated_from_configured_rate'}

def build_observability_report(runs_root:str|Path,rates_path:str|Path|None=None)->dict[str,Any]:
 root=Path(runs_root).resolve(); rate_obj=_read_json(Path(rates_path).resolve()) if rates_path else {'currency':'USD','modelRates':{}}
 records=[]
 if root.exists():
  for path in sorted(root.rglob('run-record.json')):
   obj=_read_json(path)
   if isinstance(obj,dict): records.append(obj)
 total=len(records); successful=sum(r.get('status') in ('candidate_built','succeeded') for r in records); failed=sum(r.get('status') in ('failed','blocked') for r in records)
 quality=[]
 for p in root.rglob('quality-gate-report.json') if root.exists() else []:
  obj=_read_json(p)
  if obj: quality.append(obj)
 llm_costs=[]; usage_file=root/'llm-usage.jsonl'
 if usage_file.is_file():
  for line in usage_file.read_text(encoding='utf-8').splitlines():
   try: ev=json.loads(line)
   except json.JSONDecodeError: continue
   llm_costs.append(calculate_llm_cost(str(ev.get('model','unknown')),int(ev.get('inputTokens',0)),int(ev.get('outputTokens',0)),rate_obj))
 known_costs=[x['estimatedCost'] for x in llm_costs if x['estimatedCost'] is not None]
 report={'schemaVersion':'1.0.0','generatedAt':_iso_now(),'runsRoot':str(root),'summary':{'totalRuns':total,'candidateBuilt':successful,'failedOrBlocked':failed,'successRate':(successful/total if total else None),'qualityReports':len(quality),'qualityBlocked':sum(x.get('status')=='blocked' for x in quality),'qualityIncomplete':sum(x.get('status')=='incomplete' for x in quality)},'llmUsage':{'events':len(llm_costs),'knownCostTotal':round(sum(known_costs),8) if known_costs else None,'unknownRateCount':sum(x['costStatus']=='unknown_rate' for x in llm_costs),'costs':llm_costs},'traceability':[{'runId':r.get('runId'),'requestId':r.get('request',{}).get('requestId'),'status':r.get('status'),'evidencePaths':r.get('evidencePaths',[]),'releaseEligible':r.get('releaseEligible',False)} for r in records],'limitations':['LLM costs are null when model rates are not configured.','Metric denominators are local run records; they do not yet represent a production multi-tenant service.','No automatic ontology or policy mutation is performed.']}
 return report

def create_change_proposal(*,source_run_id:str,observed_problem:str,proposed_change:str,affected_asset:str,owner:str)->dict[str,Any]:
 if not all(x.strip() for x in (source_run_id,observed_problem,proposed_change,affected_asset,owner)): raise ValueError('all proposal fields are required')
 return {'proposalId':'ont-change-'+uuid.uuid4().hex[:12],'createdAt':_iso_now(),'sourceRunId':source_run_id,'observedProblem':observed_problem,'proposedChange':proposed_change,'affectedAsset':affected_asset,'owner':owner,'status':'proposed','approvalRequired':True,'automaticMutationPerformed':False,'requiredEvidence':['impact-analysis','regression-tests','review-record'],'reviewState':'pending'}

def write_change_proposal(path:str|Path,**kwargs)->dict[str,Any]:
 proposal=create_change_proposal(**kwargs); target=Path(path).resolve()
 if target.exists(): raise FileExistsError('refusing to overwrite an existing change proposal')
 target.parent.mkdir(parents=True,exist_ok=True); target.write_text(json.dumps(proposal,ensure_ascii=False,indent=2)+'\n',encoding='utf-8'); return proposal



def build_platform_observability_report(
    runs_root: str | Path,
    portal_state: dict[str, Any],
    rates_path: str | Path | None = None,
    agent_workflow_db: str | Path | None = None,
) -> dict[str, Any]:
    """Combine pipeline run records with sanitized local Portal/Agent state.

    This is a read-only aggregation. It deliberately excludes prompts, model responses,
    credentials, raw tool arguments and event payloads from the returned report.
    """
    state = portal_state if isinstance(portal_state, dict) else {}
    report = build_observability_report(runs_root, rates_path)
    agent_runs = [item for item in state.get("agentRuns", []) if isinstance(item, dict)]
    quality_runs = [item for item in state.get("qualityRuns", []) if isinstance(item, dict)]
    sources = state.get("sourceSyncHistory", {})
    source_status_counts: dict[str, int] = {}
    sync_count = 0
    if isinstance(sources, dict):
        for history in sources.values():
            if not isinstance(history, list):
                continue
            sync_count += len(history)
            for item in history:
                if isinstance(item, dict):
                    status = str(item.get("status", "unknown"))
                    source_status_counts[status] = source_status_counts.get(status, 0) + 1

    run_status_counts: dict[str, int] = {}
    runtime_mode_counts: dict[str, int] = {}
    step_status_counts: dict[str, int] = {}
    for run in agent_runs:
        status = str(run.get("status", "unknown"))
        mode = str(run.get("runtimeMode", "unspecified"))
        run_status_counts[status] = run_status_counts.get(status, 0) + 1
        runtime_mode_counts[mode] = runtime_mode_counts.get(mode, 0) + 1
        for step in run.get("steps", []) if isinstance(run.get("steps", []), list) else []:
            if isinstance(step, dict):
                step_status = str(step.get("status", "unknown"))
                step_status_counts[step_status] = step_status_counts.get(step_status, 0) + 1

    quality_status_counts: dict[str, int] = {}
    for item in quality_runs:
        status = str(item.get("status", "unknown"))
        quality_status_counts[status] = quality_status_counts.get(status, 0) + 1

    events = []
    for event in state.get("portalEvents", [])[-30:]:
        if isinstance(event, dict):
            events.append({
                "eventId": event.get("eventId"),
                "at": event.get("at"),
                "type": event.get("type"),
                "actor": event.get("actor"),
                "summary": event.get("summary"),
            })

    from .runtime_observability import read_agent_workflow_store
    real_agent_workflow = read_agent_workflow_store(agent_workflow_db) if agent_workflow_db else {
        "available": False, "sourceMode": "read-only-sqlite", "reason": "database path not configured"
    }
    report["platform"] = {
        "mode": "local-reference-portal",
        "realAgentWorkflow": real_agent_workflow,
        "agentRuns": {
            "total": len(agent_runs),
            "byStatus": run_status_counts,
            "byRuntimeMode": runtime_mode_counts,
            "stepStatuses": step_status_counts,
            "recent": [{
                "runId": run.get("runId"),
                "status": run.get("status"),
                "runtimeMode": run.get("runtimeMode"),
                "updatedAt": run.get("updatedAt"),
                "currentStep": run.get("currentStep"),
                "stepCount": len(run.get("steps", [])) if isinstance(run.get("steps", []), list) else 0,
            } for run in agent_runs[:20]],
        },
        "qualityRuns": {"total": len(quality_runs), "byStatus": quality_status_counts},
        "sourceSync": {"historyEntries": sync_count, "byStatus": source_status_counts},
        "ontology": {
            "candidateCount": len(state.get("ontologyCandidates", [])),
            "pendingChangeCount": sum(
                1 for item in state.get("ontologyChanges", [])
                if isinstance(item, dict) and item.get("status") == "pending"
            ),
        },
        "recentEvents": events,
    }
    report["limitations"] = list(report.get("limitations", [])) + [
        "Portal/Agent counters are local JSON state and are not a distributed, multi-tenant telemetry backend.",
        "Fixture Agent runs are reported separately by runtimeMode and must not be interpreted as real LLM executions.",
        "Event payloads, prompts, model responses, credentials and raw tool arguments are intentionally excluded.",
    ]
    return report
