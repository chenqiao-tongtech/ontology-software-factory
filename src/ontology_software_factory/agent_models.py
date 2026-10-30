"""Typed output models for the optional OpenAI Agents SDK runtime.

This module requires the optional `agent-runtime` extra (Pydantic v2).
"""
from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class StrictOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RequirementBrief(StrictOutput):
    summary: str = Field(description="Short statement of the requested outcome.")
    functional_requirements: list[str] = Field(description="Observable functions the product must provide.")
    non_functional_requirements: list[str] = Field(description="Performance, security, privacy, operability or quality needs.")
    acceptance_criteria: list[str] = Field(description="Verifiable pass/fail acceptance criteria.")
    assumptions: list[str] = Field(description="Explicit assumptions; do not present them as facts.")
    open_questions: list[str] = Field(description="Ambiguities that require a human answer.")
    risk_level: Literal["low", "medium", "high"]


class ArchitecturePlan(StrictOutput):
    summary: str
    components: list[str]
    data_flows: list[str]
    security_controls: list[str]
    tradeoffs: list[str]
    open_questions: list[str]


class ProposedFileChange(StrictOutput):
    relative_path: str = Field(description="Relative path inside an isolated proposal folder; never an absolute path.")
    purpose: str
    content: str = Field(description="Candidate file content. It will be stored but never executed automatically.")


class WorkItem(StrictOutput):
    title: str
    description: str
    depends_on: list[str]
    verification: str


class ImplementationPlan(StrictOutput):
    work_items: list[WorkItem]
    proposed_changes: list[ProposedFileChange]
    out_of_scope: list[str]
    requires_human_review: bool


class TestCase(StrictOutput):
    name: str
    test_type: Literal["unit", "integration", "security", "performance", "acceptance"]
    setup: str
    assertion: str
    automation_candidate: bool


class TestStrategy(StrictOutput):
    test_cases: list[TestCase]
    required_gates: list[str]
    residual_risks: list[str]


class SecurityFinding(StrictOutput):
    severity: Literal["critical", "high", "medium", "low", "info"]
    area: str
    finding: str
    mitigation: str


class SecurityReview(StrictOutput):
    findings: list[SecurityFinding]
    release_recommendation: Literal["blocked", "needs_review", "ready_with_conditions"]
    rationale: str
    evidence_gaps: list[str]


class OntologyTermProposal(StrictOutput):
    name: str
    kind: Literal["class", "property", "relation", "event", "action", "metric", "state", "constraint"]
    definition: str
    aliases: list[str]
    source_refs: list[str] = Field(description="Source IDs and locators supporting the term; do not invent citations.")


class OntologyDiscoverySummary(StrictOutput):
    domain: str
    terms: list[OntologyTermProposal]
    unresolved_questions: list[str]
    evidence_gaps: list[str]
    requires_human_review: bool


class OntologyCriticFinding(StrictOutput):
    severity: Literal["info", "warning", "error", "blocker"]
    code: str
    affected_ids: list[str]
    message: str
    recommended_action: str


class OntologyCriticSummary(StrictOutput):
    findings: list[OntologyCriticFinding]
    duplicate_clusters: list[list[str]]
    unsupported_relations: list[str]
    missing_competency_questions: list[str]
    recommendation: Literal["revise", "needs_human_review", "no_blocking_findings"]
    cannot_approve_or_publish: Literal[True] = True



class PlanAssignment(StrictOutput):
    assignmentId: str
    roleId: str
    skillId: str
    objective: str
    inputRefs: list[str]
    outputEntityTypes: list[str]
    acceptanceCriteria: list[str]


class PlanPhase(StrictOutput):
    phaseId: str
    name: str
    objective: str
    dependsOn: list[str]
    assignments: list[PlanAssignment]
    acceptanceCriteria: list[str]


class OntologyBindingRef(StrictOutput):
    snapshotId: str
    digest: str
    ontologyId: str
    ontologyVersion: str
    schemaVersion: str


class PlanLimits(StrictOutput):
    maxAgentAssignments: int
    maxParallelAssignments: int
    maxRevisionLoops: int
    maxToolCalls: int
    timeoutSeconds: int


class PlanRiskAssessment(StrictOutput):
    level: Literal["low", "medium", "high", "critical"]
    risks: list[str]
    requiresHumanApproval: bool


class PlanControlAssertions(StrictOutput):
    mayChangeWorkflowState: Literal[False]
    mayGrantPermissions: Literal[False]
    mayApproveOwnPlan: Literal[False]
    mayPublishOntology: Literal[False]


class FactoryOrchestratorPlan(StrictOutput):
    schemaVersion: Literal["1.0.0"]
    planId: str
    workflowRunId: str
    objective: str
    ontologyBinding: OntologyBindingRef
    phases: list[PlanPhase]
    limits: PlanLimits
    riskAssessment: PlanRiskAssessment
    humanEscalations: list[str]
    controlAssertions: PlanControlAssertions


OUTPUT_MODELS = {
    "requirement-analyst": RequirementBrief,
    "solution-architect": ArchitecturePlan,
    "implementation-agent": ImplementationPlan,
    "test-agent": TestStrategy,
    "security-reviewer": SecurityReview,
    "ontology-discovery-agent": OntologyDiscoverySummary,
    "ontology-critic-agent": OntologyCriticSummary,
    "factory-orchestrator": FactoryOrchestratorPlan,
}
