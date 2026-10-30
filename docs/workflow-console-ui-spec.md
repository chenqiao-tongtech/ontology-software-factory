# Workflow Console UI Spec

## Goals

The UI exists to answer five operational questions: which runs exist, where each run stopped, why it is allowed to advance, what evidence exists, and which safe operator actions are currently allowed.

## Layout

- Header: product/module identity, local-demo environment marker, backend connection state, create-run action.
- Metrics strip: total runs, running, waiting for approval, failed.
- Left panel: searchable/filterable run list with ID, title, status, environment, progress and updated time.
- Center panel: selected run summary, completion progress and ordered step timeline; each step shows owner/mode, dependency, attempt count, idempotency and approval marker.
- Right upper panel: selected/current node inspector, role, times, attempts, evidence and error; status-conditioned controls.
- Right lower panel: newest-first event ledger, action label, timestamp, actor and operator reason.

## Interaction rules

1. API responses are the source of truth; browser does not invent state.
2. Commands are available only when the current run/step state allows them, but the backend is authoritative and validates each command again.
3. Approve/reject require an auditable reason.
4. Retry is exposed only for an eligible failed node with attempts remaining.
5. A stale write receives HTTP 409 and is surfaced as an error toast.
6. All simulated actions are visibly labeled; no UI button executes OS commands.

## Accessibility / responsive behavior

Status is indicated with both color and text. Run cards are keyboard-focusable. At narrower widths, panels stack vertically, and action targets remain comfortably large. A production version should add fuller keyboard navigation for the timeline, accessible confirmation for cancel, localization and authenticated user identity.
