\# SANGAM / GovOrchestrator — Development Context



\## Project



This is the SIH 2026 project for Problem Statement 26129:



"System Integration and Interoperability Among Government Digital Platforms"



Product name:

SANGAM — Connecting Government Services, Seamlessly.



Backend/internal name:

GovOrchestrator



The system is a federated government interoperability/orchestration platform.



The core principle is:



Existing government systems are NOT replaced.

SANGAM acts as an interoperability and orchestration layer between them.



The prototype demonstrates:

\- federated identity

\- consent-based verified data reuse

\- semantic schema mapping

\- cross-system entity resolution

\- dependency-aware service orchestration

\- unified application tracking

\- auditability

\- provider integration

\- resilient workflow execution



The prototype uses MOCK department/provider systems.

Never claim that real Maharashtra government APIs are connected unless explicitly implemented.



\---



\# CURRENT DEVELOPMENT GOAL



We are progressively moving workflow state from process-local Python dictionaries to

PostgreSQL-authoritative, transaction-safe state.



This is production-hardening work.



DO NOT attempt to rewrite the whole system at once.



Each workflow write must be audited before migration.



The required pattern is:



PostgreSQL authoritative state

→ caller-owned transaction

→ row locking

→ optimistic version check

→ atomic mutation

→ commit

→ refresh local state

→ post-commit side effects



Never mutate local workflow dictionaries first and then persist them.



\---



\# IMPORTANT ARCHITECTURAL RULES



\## PostgreSQL authority



For migrated workflow operations, PostgreSQL is authoritative.



Process-local dictionaries are compatibility/cache state only.



Do not introduce a new source of truth.



\## Concurrency



ApplicationRow.version is the aggregate concurrency token.



For workflow mutations:



1\. Lock ApplicationRow FOR UPDATE.

2\. Check expected version.

3\. Lock the required child row.

4\. Mutate authoritative PostgreSQL state.

5\. Increment ApplicationRow.version exactly once.

6\. Update JSONB projections consistently.

7\. Add WorkflowHistory when required.

8\. Flush.

9\. Commit at the workflow boundary.

10\. Refresh local state only after commit.



Lock order:



ApplicationRow → child row



Do not reverse this order.



\## Local state



Never mutate:



APPLICATIONS

ENTITY\_REVIEWS

local status history

local timeline



before PostgreSQL succeeds for a migrated workflow.



If DB commit succeeds but local refresh fails:

DO NOT attempt to roll back the DB transaction.

PostgreSQL remains authoritative and local state must be refreshed/reloaded.



\## Side effects



Events, audit and notifications must happen AFTER the authoritative database transaction commits.



Do not introduce an outbox unless explicitly requested.



\## Legacy fencing



Authoritative applications have authoritative\_at != NULL.



Legacy persistence must not overwrite authoritative state.



persist\_transition() must continue rejecting writes to authoritative applications.



persist\_state() must continue protecting authoritative applications and migrated child state.



Do not weaken this fencing.



\---



\# COMPLETED CHECKPOINTS



The following work is already completed and should NOT be unnecessarily rewritten.



\### 1. PostgreSQL persistence foundation



PostgreSQL persistence was introduced for workflow state.



\### 2. Application authority boundary



Applications can become PostgreSQL-authoritative using authoritative\_at.



\### 3. Legacy application write fencing



Legacy application writes are blocked after authority is established.



\### 4. Application mutation gateway



A reusable PostgreSQL-authoritative application mutation gateway exists.



It supports:

\- SELECT FOR UPDATE

\- expected\_version

\- version increment

\- authoritative\_at

\- typed + JSONB updates

\- caller-owned transactions



\### 5. Consent persistence



Consent versioning was implemented.



Migration:

0012\_consent\_version



Consent history is preserved.



Consent persistence uses source-version/CAS semantics.



Consent IDs are propagated explicitly through:

application → dependency → provider job → worker → provider authorization.



Provider authorization:

\- exact consent\_id is deterministic

\- missing consent\_id fails closed

\- historical consent rows must not be selected using arbitrary ordering



\### 6. Transaction-scoped workflow mutation boundary



A reusable workflow aggregate mutation boundary exists.



It supports:

\- caller-owned SQLAlchemy session

\- ApplicationRow locking

\- child-row locking

\- expected application version

\- application version increment

\- JSONB updates

\- child updates

\- WorkflowHistory

\- authority establishment

\- post-commit refresh



It must remain infrastructure unless a specific production workflow is explicitly migrated.



\### 7. Entity-review migration



The FIRST production workflow migrated to PostgreSQL-authoritative transactions is:



entity\_review\_action()



It is committed in:



ffaa535

"Migrate entity review to authoritative workflow transaction"



Entity review now:

\- locks ApplicationRow first

\- locks EntityReviewRow second

\- checks ApplicationRow.version

\- updates PostgreSQL EntityReviewRow

\- updates application entityReviews JSONB projection

\- updates requirement state

\- updates application status where appropriate

\- increments ApplicationRow.version once

\- creates WorkflowHistory when status changes

\- updates JSONB statusHistory

\- establishes authority

\- commits

\- refreshes local state after commit

\- performs side effects after commit

\- does NOT call persist\_transition()

\- does NOT call persist\_state()



Tests at this checkpoint:

150 backend tests passed.



Git state at handoff:

HEAD = ffaa535

branch = local-production-upgrade

working tree = clean

main has NOT been modified/pushed.



\---



\# REMAINING WORK



Remaining workflow areas include things such as:



\- conflict review

\- dependency creation/completion

\- application submission

\- officer actions

\- provider completion

\- event/audit/notification reliability



BUT:



DO NOT assume any of these are safe to migrate.



Before implementing any next workflow:



1\. Perform a READ-ONLY audit.

2\. Trace the complete call graph.

3\. Identify every local and PostgreSQL mutation.

4\. Identify related child state.

5\. Identify side effects.

6\. Check whether the operation can be isolated in one transaction.

7\. Identify concurrency requirements.

8\. Identify legacy fencing requirements.

9\. Decide whether it is actually safe.

10\. Only then propose implementation.



If no safe operation exists, STOP.

Do not invent a new endpoint just to create a migration candidate.



\---



\# CURRENT BRANCH



Work only on:



local-production-upgrade



Do NOT:

\- switch to main

\- modify main

\- push to main

\- merge into main

\- reset existing commits

\- rewrite history



Current checkpoint:



ffaa535



The user wants to continue development from this checkpoint.



\---



\# CHANGE DISCIPLINE



For every future checkpoint:



1\. Audit first.

2\. Implement only the approved scope.

3\. Run focused tests.

4\. Run relevant regression tests.

5\. Run full backend tests when appropriate.

6\. Run compile checks.

7\. Run git diff --check.

8\. Review git diff.

9\. Report exact files changed.

10\. Do NOT commit until the user explicitly approves.

11\. Do NOT push unless the user explicitly asks.



Never silently broaden scope.



\---



\# IMPORTANT



This is an existing working system.



Prefer:

\- small changes

\- existing abstractions

\- existing field mappings

\- existing API behavior

\- existing security behavior

\- existing tests



Do not invent:

\- new endpoints

\- new schemas

\- new migrations

\- new workflow semantics

\- new provider behavior



unless the audit explicitly demonstrates they are necessary and the user approves.



When uncertain, STOP and explain the exact blocker rather than guessing.

