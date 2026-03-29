# Ops Hub Roadmap

This document turns Ops Hub from a migration target into a product plan.

The core idea is simple:

- Ops Hub should become the system of action for operations work
- BlueFolder should remain an important system of record
- Discord should remain a useful client surface, not the full product boundary

## Product Direction

Ops Hub wins when it owns the operational layer that people actually work from:

- actionable queues
- next-action guidance
- ownership and follow-up state
- cross-role workflow handoffs
- notice routing and escalation
- operational metrics and audit history

That means Ops Hub should not stop at job lookups, comment wrappers, or read-only summaries.

## What Ops Hub Must Become

### Core identity

Ops Hub should be the place where the business answers:

- what needs action right now
- who owns it
- what is blocked
- what happened last
- what should happen next

### Primary roles

Ops Hub should serve four operating roles directly:

- technicians in the field
- dispatch staff managing today and near-term follow-up
- parts staff handling blockers, ETA, and readiness
- admins supporting runtime, mapping, and policy

### Product surfaces

Ops Hub should support multiple role-native surfaces over one shared domain:

- Discord for quick commands, notifications, and lightweight actions
- technician API and mobile flows for field work
- a dispatcher board for queue management and live triage
- admin and operational reporting surfaces as the system matures

## Strategic Bets

These are the bets that make Ops Hub materially better than a bot wrapper.

### 1. Attention engine

Ops Hub should continuously derive actionable work items from BlueFolder data plus Ops Hub events.

Examples:

- waiting on dispatch follow-up
- parts received but not scheduled
- customer unreachable and unresolved
- photo compliance gap
- technician issue reported and aging

This is the center of gravity for the product.

### 2. Real workflow objects

Ops Hub needs its own operational objects instead of relying on raw comments and ad hoc command output.

Priority objects:

- `attention_item`
- `parts_case`
- `dispatch_followup`
- `photo_gap`
- `customer_contact_issue`

Each object should support:

- status
- owner
- created_at / updated_at
- age
- next_action
- linked service request
- linked event history

### 3. Event-first architecture

Every meaningful action should become a typed event with source, actor, timestamp, target, and outcome.

Sources include:

- Discord commands
- technician API actions
- future dispatcher UI actions
- background reconciliation and policy jobs

If the event model is clean, new clients can be added without rebuilding workflow logic.

### 4. Role-native views

Each role should see work in the shape they need, not just a different set of slash commands.

- technicians need a focused daily workflow
- dispatch needs live triage and queue control
- parts needs blocker, ETA, and handoff visibility
- admins need health, policy, and coverage visibility

### 5. Outcome-driven product management

Ops Hub should optimize for operating outcomes, not command count.

Primary outcome targets:

- lower time-to-next-action
- fewer dropped follow-ups
- fewer parts stalls
- better photo compliance
- less dispatcher thrash
- faster technician updates

## 90-Day Delivery Plan

### Phase 1: Days 1-30

Goal: make the domain real.

#### Deliverables

- define the first internal workflow objects in Ops Hub
- define a typed event schema for operational actions
- persist ownership, stage, next action, and age for workflow objects
- create a merged service-request timeline that combines BlueFolder facts with Ops Hub events
- identify the first policy-derived queues for dispatch and parts

#### Scope focus

- attention model
- workflow state model
- event capture
- storage boundaries

#### Success criteria

- dispatch can answer "what needs action now?" from Ops Hub
- parts can answer "what is blocked and why?" from Ops Hub
- important actions are no longer trapped only in comments or ephemeral responses

#### Start here

The first implementation slice should be:

1. define event and workflow models in `src/ops_hub/models/`
2. add a persistence boundary for Ops Hub-owned workflow state
3. build a service that derives `attention_item` records from current BlueFolder and parts state
4. expose that service first through dispatch-facing views before adding a new UI surface

### Phase 2: Days 31-60

Goal: build role-native control surfaces on top of the shared domain.

#### Deliverables

- expand the technician API from a thin companion surface into a real daily workflow backend
- promote dispatch from board summaries into queue-based triage and follow-up workflows
- introduce a first-class `parts_case` model instead of relying on comment-derived status alone
- formalize handoff flows between technician, dispatch, and parts

#### Scope focus

- technician mobile/API parity for key workflows
- dispatch queue workflows
- parts lifecycle ownership
- role-specific views over shared state

#### Success criteria

- the technician mobile surface can complete the most common field actions cleanly
- dispatch can work from queue views instead of hunting through lookups
- parts can work from tracked case state instead of comment archaeology

### Phase 3: Days 61-90

Goal: add automation, escalation, and operating signal.

#### Deliverables

- SLA-style timers and age-based attention rules
- escalation and notice policies by queue type and age
- operational metrics for backlog, latency, and handoff quality
- first serious non-Discord dispatch surface

#### Scope focus

- automation
- escalation
- measurement
- management visibility

#### Success criteria

- aging work is surfaced before it becomes invisible
- dispatch and parts notices are driven by policy, not only manual command use
- the team can measure whether Ops Hub is improving workflow speed and reliability

## Implementation Order

The recommended order of work is:

1. attention engine
2. parts case model
3. dispatcher queue and board
4. technician workflow API expansion
5. metrics and escalation policy

If sequencing pressure forces tradeoffs, protect the first three. They change product identity the most.

## Repository-Level Execution Map

These are the likely repo areas that carry the early roadmap work.

### Core domain and orchestration

- `src/ops_hub/services/`
- `src/ops_hub/models/`
- `src/ops_hub/core/`

Expected additions:

- workflow state models
- event models
- attention derivation services
- policy evaluation services

### Client surfaces

- `src/ops_hub/bot/`
- `src/ops_hub/api_server.py`
- `src/ops_hub/services/technician_api.py`

Expected changes:

- slimmer command handlers
- cleaner use-case boundaries
- more shared service logic

### Docs and operational guidance

- `docs/`

Expected additions:

- roadmap tracking
- queue definitions
- role workflow docs
- operating metrics definitions

## Non-Goals For This Roadmap

These may still matter, but they should not displace the current product shift.

- premature bot splitting by subsystem
- polishing every command before the workflow model is stronger
- treating photo ingest as the product center
- expanding wrapper behavior without adding owned workflow state

## Decision Rule

When choosing what to build next, prefer work that makes Ops Hub more authoritative about:

- action
- ownership
- state
- follow-up
- measurement

Prefer not to spend major effort on work that only adds another way to read or relay BlueFolder data.
