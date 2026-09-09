# Task Lifecycle OSS Reference

**Purpose:** compare lifecycle contracts, not copy a distributed engine into
NetConsole. All references below are official project documentation.

| Project | Stable execution ID | Operational store | Terminal state | Long-term history | Log ownership | Result ownership | Removal semantics | Relevant pattern | Do Not Copy |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Temporal | Workflow ID is business identity; Run ID identifies an execution and may change across retry | Temporal service execution/history store | terminal workflow execution | append-only Event History with lifecycle/limits | workflow/activity logging and external sinks | workflow result/payload contracts | execution history is governed separately from external files | identity must survive worker/context changes; event history is durable | Temporal Server, event-history archive or distributed orchestration |
| Apache Airflow | DAG/task instance identity; TaskInstance is the state authority | metadata DB / TaskInstance rows | task instance states | historical metadata and TaskInstance history APIs | task log handlers / remote log stores | XCom/task outputs and external stores | explicit DB cleanup can purge old metadata with dry-run/archive safeguards | live metadata and historical metadata are distinct | Airflow scheduler/DB cleanup policy as NetConsole retention |
| Argo Workflows | workflow name/UID | Kubernetes CR plus optional Workflow Archive DB | workflow phase | optional Workflow Archive | pod logs are not archived by the workflow archive; artifact/log repository is separate | artifact repository and workflow result/status | archive is optional and independent of live workflow object | archive/status and logs/artifacts have different lifetimes | Kubernetes control plane and archive server |
| Prefect | Task Run identity is an invocation; task definition/key is different | orchestration API/client state | final task-run state | each state transition is tracked according to orchestration policy | task/runtime logging | task run result state and result storage | client/server state retention is separate from task definition | execution identity is not task type/context | Prefect server/cloud orchestration model |
| Celery | task ID uniquely identifies a submitted task | broker + result backend | `SUCCESS`, `FAILURE`, `REVOKED` etc. | simple result/state backend; not a rich permanent archive | worker/application logs | result backend; caller may `forget()` it | result resources are explicitly released by caller/backend policy | result query is keyed by task ID, not current UI context | Celery broker/result backend and distributed worker stack |
| NetConsole selected pattern | `task_id` is stable for operational lifetime; site is routing context | per-site `tasks.db` plus small authority index | `PENDING`, `STARTING`, `RUNNING`, `STOPPING`, `COMPLETED`, `FAILED`, `CANCELLED` | no permanent Task Detail archive; manual retirement is the boundary | Log Center owns long-term application logs; task events are bounded tail | Artifact/File Store and business DB own formal outputs; task DB keeps operational references | explicit single/batch retirement deletes safe task-owned rows only | current/recent view, stable identity, explicit ownership and fail-closed references | all external engines, automatic retention framework and new history system |

## Extracted principles

### Temporal

Workflow ID is the user/business identity and Run ID is the unique execution
identifier. NetConsole maps the stable operational identity to `task_id`; the
active site is context/routing metadata and must not become identity. Temporal's
event history also confirms that durable event history is an execution concern,
not a reason to keep a user-facing task detail archive forever.

### Airflow

TaskInstance metadata is an operational state authority, while historical
metadata and cleanup are separate concerns. NetConsole adopts the distinction
and the explicit, reviewable cleanup boundary, but does not adopt Airflow's
scheduler or retention framework.

### Argo

The live workflow object, archive, pod logs, and artifacts are separate
lifecycles. This directly supports keeping Log Center files and Artifacts after
Task Center metadata retirement.

### Prefect and Celery

Both reinforce that a task definition/type is not an execution identity and
that result state is queried by execution ID. NetConsole therefore routes
`task_id` to its owning site database across active-site changes. Celery's
simple result-backend release model is useful as a boundary reminder, not as a
proposal to add a broker/backend.

## Official references

- [Temporal Workflow ID and Run ID](https://docs.temporal.io/workflow-execution/workflowid-runid)
- [Temporal Event History](https://docs.temporal.io/workflow-execution/event)
- [Apache Airflow TaskInstance source](https://airflow.apache.org/docs/apache-airflow/stable/_modules/airflow/models/taskinstance.html)
- [Apache Airflow database cleanup](https://airflow.apache.org/docs/apache-airflow/3.3.0/stable/howto/usage-cli.html)
- [Argo Workflow Archive](https://argo-workflows.readthedocs.io/en/latest/workflow-archive/)
- [Prefect Tasks](https://docs.prefect.io/v3/concepts/tasks)
- [Celery Tasks](https://docs.celeryq.dev/en/stable/userguide/tasks.html)
- [Celery result backend API](https://docs.celeryq.dev/en/stable/reference/celery.result.html)
