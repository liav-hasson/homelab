<!-- markdownlint-disable MD013 -->

# Monitoring acceptance and incident runbook

## Deployment prerequisites

- Coordinate gateway/dictionary/sentence instrumentation rollout first. Scrapes
  use `/metrics` on named `http` ports; lookups otherwise retain existing
  resources, SQL, timeouts and retry policies.
- **Before reconciling this PostgreSQL release**, provision the monitoring login
  and `ankilabs/postgres-monitoring` Secret described below. Missing credentials
  intentionally leave the exporter unavailable, not apparently healthy.
- PostgreSQL logging arguments change its Pod template and cause a restart on
  rollout. Schedule that interruption explicitly. No deployment is performed by
  the local validation suite.
- Keep `application_name` bounded and service-specific. Never put request IDs,
  fingerprints, PIDs, cursors, query/card text, prompts, Usage Codes or DSNs in
  application names, metric labels or Loki index labels.
- No live commands, Secret reads or decryption are needed for local validation.
  The operator steps below require separate approval and an authorized operator.

### PostgreSQL monitoring login

Existing-volume init scripts **do not run again**. This change intentionally does
not pretend an added init script provisions an existing database. Both existing
and fresh clusters need this explicit step. For a fresh cluster, initially install
with `monitoring.enabled=false`, provision the login/Secret, then enable it.

In an authorized administrative `psql` session, inspect whether the login exists.
Create it only if absent; reconcile grants if it already exists. Do not drop a
role or reuse a lookup reader/superuser login.

```sql
CREATE ROLE ankilabs_monitor LOGIN
  NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS
  CONNECTION LIMIT 5;
GRANT CONNECT ON DATABASE ankilabs TO ankilabs_monitor;
GRANT pg_read_all_stats TO ankilabs_monitor;
ALTER ROLE ankilabs_monitor IN DATABASE ankilabs
  SET default_transaction_read_only = on;
```

Set its password interactively with `\password ankilabs_monitor`; do not put a
password in SQL files, shell history, a URI or a report. Through the existing
SOPS/approved Secret-management process, provision a separate Secret named
`postgres-monitoring` in `ankilabs`, with key `password` holding that same value.
This deliverable contains no credential and creates no administrative Job.

`pg_read_all_stats` supplies activity/wait information without `pg_monitor`,
superuser, table-data grants or `pg_read_all_settings`. It can nevertheless read
other sessions' SQL text through system views: protect this credential as a
monitoring credential. The exporter never exports that text. Do not broaden
lookup-reader privileges. Verify the monitoring login cannot select corpus or
dictionary tables and cannot write; investigate any pre-existing PUBLIC grants.

The exporter connects only to `postgres:5432/ankilabs`, with fixed
`application_name=postgres_exporter`. Only Prometheus Pods in `monitoring` may
reach its metrics port. Only the exporter, not Prometheus, gains DB ingress.
Collector timeout is bounded to 8 seconds, below the 10-second scrape timeout.
Enabled collectors are database, locks, numeric settings, activity, bgwriter,
checkpointer and database statistics. No table/index/statement scans,
auto-discovery, extensions or query-text collector are enabled.

## Server rollout walkthrough

Run Kubernetes/psql commands in Bash on the server with the intended Kubernetes
context and an authorized operator account; they do not require the Flux CLI.
Run the SOPS editing step in your homelab checkout on a machine with your existing
SOPS key. There is no need to copy that key to the server. Stop on unexpected output.

The review branch is not a deployment. Leave Flux tracking `main`: pointing it
at an older review-branch snapshot could undo newer image promotions.

### 1. Confirm context and current application rollout

```sh
kubectl config current-context
kubectl get nodes
kubectl -n flux-system get gitrepository flux-system
kubectl -n flux-system get kustomizations platform ankilabs monitoring-configs
kubectl -n ankilabs get statefulset postgres
kubectl -n ankilabs get deployments api-gateway dictionary-lookup sentence-lookup
kubectl -n ankilabs get deployments api-gateway dictionary-lookup sentence-lookup \
  -o custom-columns='NAME:.metadata.name,IMAGE:.spec.template.spec.containers[0].image'
```

Wait for the three application CI pipelines to pass and their new images to be
promoted. Then confirm their deployments are ready:

```sh
kubectl -n ankilabs rollout status deployment/api-gateway --timeout=10m
kubectl -n ankilabs rollout status deployment/dictionary-lookup --timeout=10m
kubectl -n ankilabs rollout status deployment/sentence-lookup --timeout=10m
```

Readiness alone does not establish that the image contains the instrumentation.
Check the promoted versions against the three application pipeline runs.

### 2. Provision the database login

Open an administrative session inside the existing database Pod:

```sh
kubectl -n ankilabs exec -it statefulset/postgres -c postgres -- \
  psql -X -U ankilabs -d ankilabs -v ON_ERROR_STOP=1
```

First inspect whether this dedicated login already exists:

```sql
SELECT rolname, rolsuper, rolcreatedb, rolcreaterole, rolreplication, rolbypassrls
FROM pg_roles WHERE rolname = 'ankilabs_monitor';
```

If absent, run the `CREATE ROLE` statement in the preceding monitoring-login
section. If present, review its privileges instead of recreating or dropping it.
Run that section's `GRANT` and `ALTER ROLE` statements. Choose one strong
password, then run `\password ankilabs_monitor`. At the hidden prompts, enter
that actual password twice, not YAML, a Kubernetes Secret name or `ENC[...]`
ciphertext. Leave psql with `\q`.

The exact narrow grant recipe, including database read-only defaults, was
validated against PostgreSQL 18 and all seven configured exporter collectors.
Neither `pg_monitor` nor `pg_read_all_settings` is required.

### 3. Store the same password in the SOPS Secret

The SOPS-managed manifest is
`k8s/apps/ankilabs/postgres/monitoring-secrets.yaml`. During initial setup, keep
its resource entry disabled until it contains the real password. If the live
Secret is already configured, retain that same password rather than generating
a different one.

From your homelab checkout, open it with your existing SOPS setup:

```sh
sops k8s/apps/ankilabs/postgres/monitoring-secrets.yaml
```

For an initial template, in the editor SOPS opens replace
`REPLACE_WITH_THE_PASSWORD_SET_IN_POSTGRESQL` with the exact same password you
entered at the psql prompts. Save and exit; SOPS encrypts the value again
automatically. Do not edit the file directly to insert a plaintext password.

Then ensure `- monitoring-secrets.yaml` appears exactly once in the resources of
`k8s/apps/ankilabs/postgres/kustomization.yaml`. Commit the encrypted Secret and
that resource entry to the review branch when ready. Do not add a second entry
if it is already enabled, or commit plaintext password files or SOPS private keys.

After the branch is merged and Flux reconciles, it creates the Secret before
Helm can use it. If you also want to create it before the merge, use the
operator-managed alternative below with the same password; otherwise perform
the Secret-backed login check after reconciliation.

#### Alternative: create the Secret directly on the server

Skip this alternative when using the SOPS manifest. The following is for
operator-managed provisioning; keep an approved encrypted backup for cluster
recovery. It does not write plaintext credentials to Git or command arguments.

Enter the same password just assigned to the database login:

```sh
(
  set -euo pipefail
  umask 077
  password_file="$(mktemp)"
  trap 'rm -f -- "$password_file"' EXIT
  read -r -s -p 'Monitoring database password: ' monitoring_password
  printf '\n'
  if [ -z "$monitoring_password" ]; then
    printf 'Refusing an empty password.\n' >&2
    exit 1
  fi
  printf '%s' "$monitoring_password" > "$password_file"
  unset monitoring_password
  kubectl -n ankilabs create secret generic postgres-monitoring \
    --from-file=password="$password_file" --dry-run=client -o yaml |
    kubectl apply --server-side --field-manager=monitoring-operator -f -
)
```

Do not use `--force-conflicts` if another manager owns the Secret. Resolve that
ownership through the existing Secret-management process.

Verify the Secret-backed password and role over TCP without printing it:

```sh
(
  set -euo pipefail
  kubectl -n ankilabs get secret postgres-monitoring \
    -o jsonpath='{.data.password}' |
    base64 --decode |
    kubectl -n ankilabs exec -i statefulset/postgres -c postgres -- sh -c '
      PGPASSWORD="$(cat)"
      export PGPASSWORD
      exec psql -X -h 127.0.0.1 -U ankilabs_monitor -d ankilabs \
        -v ON_ERROR_STOP=1 \
        -c "SELECT current_user, current_setting('\''default_transaction_read_only'\'') AS read_only;"
    '
)
```

Expected: `ankilabs_monitor` and `on`. This reads the Secret only into a pipe and
the database client's environment. Do not enable shell tracing or paste secret
values into logs or chat.

### 4. Authorize the infrastructure rollout

Only after prerequisites pass and the PostgreSQL interruption is acceptable,
review and merge the infrastructure branch into `main` in GitHub. Do not switch
the Flux source branch. Merging is the deployment approval: Flux can reconcile
automatically before you run the following commands.

Request source reconciliation:

```sh
kubectl -n flux-system annotate gitrepository/flux-system \
  reconcile.fluxcd.io/requestedAt="$(date -u +%s)" --overwrite
kubectl -n flux-system get gitrepository flux-system \
  -o jsonpath='{.status.artifact.revision}{"\n"}'
```

Wait until that revision includes the merged changes, then request the affected
Kustomizations:

```sh
kubectl -n flux-system annotate kustomization/platform \
  kustomization/ankilabs kustomization/monitoring-configs \
  reconcile.fluxcd.io/requestedAt="$(date -u +%s)" --overwrite
kubectl -n flux-system get kustomizations platform ankilabs monitoring-configs -w
```

When they report Ready with the new applied revision, stop the watch with Ctrl-C.
Verify the Helm releases and workloads:

```sh
kubectl -n ankilabs get helmrelease postgres
kubectl -n monitoring get helmreleases kube-prometheus-stack promtail
kubectl -n ankilabs rollout status statefulset/postgres --timeout=15m
kubectl -n ankilabs rollout status deployment/postgres-exporter --timeout=10m
kubectl -n monitoring rollout status daemonset/promtail --timeout=10m
kubectl -n monitoring get podmonitors
```

For reconciliation failures, inspect the affected resource before retrying:

```sh
kubectl -n flux-system describe kustomization monitoring-configs
kubectl -n ankilabs describe helmrelease postgres
kubectl -n monitoring describe helmrelease promtail
```

### 5. Check exporter health and Grafana

In one server terminal, run:

```sh
kubectl -n ankilabs port-forward --address 127.0.0.1 \
  deployment/postgres-exporter 9187:9187
```

In a second terminal on that same server:

```sh
curl --fail --silent --show-error http://127.0.0.1:9187/metrics |
  grep -E '^pg_up |^pg_scrape_collector_success'
```

Expected: `pg_up 1` and success `1` for every enabled collector. Stop the
port-forward with Ctrl-C afterward. Follow the Grafana/Discord operator
acceptance checklist and queries below. Missing targets are not healthy zeros.

### 6. Capture one controlled Avoir reproduction

After confirming monitoring is healthy, perform a successful ordinary lookup,
then one controlled `Avoir` lookup. Save the UTC time, front/back languages,
query options, browser HTTP status and response `X-Request-ID`. Use that ID and
the narrow time window in the request/database queries below. Do not repeatedly
stress the known failing lookup before reviewing the first captured attempt.

## Local validation

Run from the homelab root. These tests read only non-secret definitions, render
Cloudflare with synthetic values and use temporary local files. They do not
contact Kubernetes, PostgreSQL, Loki or Discord. Remote chart rendering below
fetches only the public pinned Helm chart.

```sh
python3 -m unittest discover -s k8s/platform/monitoring/tests -v
ruff check k8s/platform/monitoring/tests
pylint k8s/platform/monitoring/tests/test_*.py
pytest -q k8s/platform/monitoring/tests
markdownlint-cli2 k8s/platform/monitoring/runbook.md
git diff --check
```

The suite includes local JSON-contract/schema/unique-UID/layout checks
(including panels nested in collapsed rows), panel descriptions, dashboard
tags and runbook links against this file's headings, exact per-folder
provisioning and its sidecar settings, namespace/privacy/routing guards, `helm lint` and
`helm template` for the PostgreSQL, LLM Proxy, Envoy and Cloudflare charts, monitoring-only `kustomize build`,
`promtool check rules` for alerts **and all dashboard PromQL**, eighteen real
Prometheus evaluator cases, and actual Promtail stdin/dry-run replay tests.
The checked-in dashboard schema is a focused provisioning contract, not the
entire Grafana API schema.

Dependencies are Python with `tests/requirements.txt`, Helm, Kustomize,
Prometheus' `promtool`, and the Promtail **3.5.1** binary corresponding to pinned
chart **6.17.1**. Missing binaries fail explicitly, never silently skip. Supply
`PROMTAIL_BIN`, `PROMTOOL_BIN`, `HELM_BIN` or `KUSTOMIZE_BIN` if needed. If a
missing-tool failure occurs, install only the missing tools before rerunning:

```sh
python3 -m pip install -r k8s/platform/monitoring/tests/requirements.txt ruff pylint pytest
brew install helm kustomize prometheus
npm install --global markdownlint-cli2
```

Obtain the appropriate Promtail 3.5.1 binary from the
[official release](https://github.com/grafana/loki/releases/tag/v3.5.1) and set
`PROMTAIL_BIN` to its absolute path. Do not silently substitute another agent.
Also render the actual public Promtail chart to validate Helm's template-escape
layer (the replay tests exercise the unwrapped collector pipeline):

```sh
python3 -c 'from pathlib import Path; import yaml; print(yaml.safe_dump(yaml.safe_load(Path("k8s/platform/monitoring/controllers/loki-stack/promtail-release.yaml").read_text())["spec"]["values"]))' |
  helm template promtail promtail --repo https://grafana.github.io/helm-charts \
    --version 6.17.1 --namespace monitoring --values -
```

After changing Grafana values, render kube-prometheus-stack the same way and
check the dashboard sidecar and provider (expect `FOLDER_ANNOTATION` set to
`grafana_folder`, `foldersFromFilesStructure: true` and
`allowUiUpdates: false`). The encrypted `grafana-helm-values` Secret is not
included:

```sh
python3 -c 'from pathlib import Path; import yaml; print(yaml.safe_dump(yaml.safe_load(Path("k8s/platform/monitoring/controllers/kube-prometheus-stack/release.yaml").read_text())["spec"]["values"]))' |
  helm template kube-prometheus-stack oci://ghcr.io/prometheus-community/charts/kube-prometheus-stack \
    --version 69.8.2 --namespace monitoring --values - |
  grep -E -A1 'FOLDER_ANNOTATION|foldersFromFilesStructure|allowUiUpdates'
```

Inspect changed-file editor diagnostics as well; no editor Problems API is
available to the command-line suite. No workflow, commit, image push or live
deployment is part of these commands.

## Operator acceptance

After an explicitly authorized rollout:

1. Grafana must contain exactly the seven provisioned dashboards, in the
   folders listed under [Dashboards](#dashboards) and none in General. Check
   that Flux pruned every older dashboard ConfigMap, leaving only
   `homelab-grafana-dashboards-ankilabs`, `-quizlabs` and `-platform`, and that
   the Grafana sidecar removed their dashboards. Do not keep old dashboards as
   a second source of truth.
2. Select the Prometheus and Loki data sources. Confirm each expected target is
   present and reachable, `pg_up=1`, and every enabled collector reports success.
   Missing series remain **unknown**. An idle histogram can legitimately have no
   label set yet; it must not be filled with green or synthetic zero.
3. Generate an ordinary successful lookup and one controlled failure using the
   application's existing approved test method. Inspect counts, sample counts,
   status, stages, pool states, and matching structured events. Do not generate
   real-user errors or modify SQL algorithms to exercise monitoring.
4. Verify record fields, not just colors: EOF/open transaction has native
   `pg_severity=LOG` and normalized `level=WARNING`; severe PG diagnostic text is
   redacted with `raw_redacted=true`; unknown/malformed records remain visible.
   Inspect only synthetic traffic when checking that no query/parameter text,
   URLs, card content, prompts, Usage Codes or DSNs reach Loki.
5. Confirm new application/database alerts reach the existing **POD Discord**
   receiver, including their dashboard/runbook links. Namespace matcher strategy
   `None` is required because the config lives in `monitoring`, but alert labels
   retain `ankilabs`/`quizlabs`. Config selection stays restricted to the existing
   monitoring namespace/label. Node alerts still use the node receiver; unrelated
   unscoped/default chart alerts still use the existing discard route.
6. Confirm native edge targets are internal only. Envoy uses named `metrics`
   port `/stats/prometheus`, selected for the platform/homelab-gateway proxy.
   Cloudflared already binds `:2000`; it now declares that named port and permits
   monitoring ingress only. No public admin Service/HTTPRoute is added.

## Dashboards

Seven dashboards are provisioned from `configs/dashboards/*.json`, one
ConfigMap per Grafana folder:

| Folder | Dashboards |
| --- | --- |
| AnkiLabs | AnkiLabs - Service Health, AnkiLabs - Search & PostgreSQL, AnkiLabs - AI |
| QuizLabs | QuizLabs - Overview |
| Platform | Homelab Overview, Platform - Delivery & Edge, Platform - Storage |

Each dashboard's **Runbook** link opens its section below, and its
**Monitoring** menu lists the others, keeping the time range and variables.
Every panel explains itself in its description (the info icon next to its
title). Missing data is unknown, never zero or healthy: check scrape health
before reading any chart.

The kube-prometheus-stack Grafana sidecar writes each ConfigMap into the
subdirectory named by its `grafana_folder` annotation, and the dashboard
provider (`foldersFromFilesStructure`) makes every subdirectory a folder.
Dashboards are addressed by UID (`/d/<uid>`), so moving one to another folder
keeps its URL, alert links and bookmarks. During the move Grafana can delete
and re-create a dashboard, which drops its stars and version history.

### Dashboard conventions

Rules for new and redesigned panels; existing dashboards adopt them as they are
redesigned. The schema and `tests/test_static.py` enforce the ones marked
*(tested)*.

- **Headline numbers**: stat with a sparkline.
- **Share of a capacity** (memory of its limit, disk used): gauge or bar gauge
  with thresholds.
- **Latency**: a heatmap of the histogram buckets for the distribution, plus a
  p95 time series. Heatmap targets are
  `sum by (le) (rate(<metric>_bucket{...}[...]))` (or `increase`) with format
  **Heatmap**, and seconds buckets use unit `s` *(tested)*. A percentile is shown
  only with a minimum sample count in the same window *(tested)*.
- **Counts over time**: bars. Stack only series that add up to a true total.
- **Shares of a whole**: pie/donut or bar gauge.
- **Up/down and other states over time**: state timeline.
- **Inventories** (targets, replicas, claims, Usage Codes): tables with cell
  styling.
- **Logs**: in a collapsed row at the bottom.
- **No text panels** *(tested)*. A panel explains itself in a one- or
  two-sentence description: what it shows, how to read it, what to do when it
  looks bad *(tested)*. A dashboard explains itself in its description and its
  section below; group panels with rows.
- **No fake data**: no `vector(0)` or null-as-zero, an absent series stays
  empty, and durations are in seconds *(tested)*.
- **Panel types**: Grafana 11.5 core panels that are generally available, plus
  rows. Beta (`trend`, `datagrid`) and `text` panels fail the schema.
- **Folders and tags** *(tested)*: add a dashboard to its folder's ConfigMap in
  `configs/kustomization.yaml`. Tag it `homelab-monitoring` (feeds the
  Monitoring menu), its app (`ankilabs`, `quizlabs`, `platform` or `homelab`)
  and, where obvious, its layer (`ai`, `storage`, `database`, `edge`,
  `overview`, `services`).

### Homelab Overview

Start here: node CPU, memory and filesystems, persistent volumes, scrape
coverage, Deployment and StatefulSet availability, restarts, active alerts and
node pressure. Availability is Kubernetes readiness, not a synthetic user
journey. Then go to Platform - Delivery & Edge for Flux, Envoy and cloudflared;
Platform - Storage for disk space, volumes and I/O; AnkiLabs - Service Health
for request failures; AnkiLabs - Search & PostgreSQL for lookup stages and
pools; AnkiLabs - AI for AI calls, Usage Codes and spend; QuizLabs - Overview
for the legacy stack. Node and pod alerts link here; their steps are under
[Resources](#resources).

### Platform Delivery and Edge

Flux readiness comes from kube-state-metrics custom-resource metrics;
reconciliation mean duration is in seconds, not uptime. Envoy counters are
real proxy activity per route cluster. Cloudflared counters cover the whole
tunnel and cannot be split per application, so application dashboards show only
route-bound Envoy data. No log regex is used as a failure counter. Native scrape
ports stay internal; there is no public admin route. Target checks are under
[Telemetry](#telemetry).

### Platform Storage

Read it top to bottom: headline numbers, then the **node disk**
(node-exporter, authoritative for free space), **persistent volumes**
(kube-state-metrics claims plus kubelet volume stats), **disk performance**,
**application self-metrics** (Prometheus TSDB, PostgreSQL) and, collapsed, the
OpenEBS provisioner logs.

- Every PVC is an `openebs-hostpath` directory on the node filesystem, so all
  volumes share one pool of free space and requested sizes are not enforced.
  The per-volume bars show kubelet used bytes against the **requested** size,
  not against the reported capacity (which can be the whole filesystem); over
  100% means the volume outgrew its request, not that it is full.
- kubelet stats for hostpath volumes may be missing or filesystem-wide. In the
  Volume inventory, an empty Used cell is unknown, and a kubelet capacity equal
  to the node disk size, or the same used bytes on every claim, means the
  per-volume panels (and Total and Largest PVC) are not per volume: trust Disk
  used and the application panels instead.
- Days until full uses the 24h linear decline of free space; **Not filling**
  means free space did not shrink over 24h. The 3-day projection uses the
  alert's 6h trend. Short write bursts (image pulls, restores, compaction)
  exaggerate both.
- Throughput and IOPS draw reads above zero and writes below it. 100% busy is
  not saturation on NVMe; read it with queue depth and latency.
- Prometheus at 100% of its size cap is expected once the cap is reached: it
  then deletes the oldest blocks (retention block deletions, size) and keeps
  less than 7 days.

Loki, MinIO, MongoDB and Redis expose no storage metrics; only their claims are
shown. Incident steps are under [Storage](#storage).

### AnkiLabs Service Health

All data is restricted to the `ankilabs` namespace. A failure is an observed
5xx or an explicit upstream `timeout`/`unavailable`, never a keyword count.
Latency is a mean next to its sample count rather than a sparse p95; zero
observations give no mean. A request killed before completing leaves started
breadcrumbs but no latency sample. Request IDs are parsed only at query time.
Incident steps are under [Requests](#requests) and [Resources](#resources).

### AnkiLabs Search and PostgreSQL

All data is restricted to `ankilabs`. Compare each stage's mean with its sample
and error counts; stages overlap, so never add their times into a request
total. Started events locate the last stage when a process dies before
completing. Pool states (size, available, waiting, max) are separate, not
additive. Row histograms are per-phase observations, not SQL execution plans.
Request IDs, fingerprints and backend PIDs are query-time fields, never index
labels. The PostgreSQL panels need the
[monitoring login](#postgresql-monitoring-login); a reachable exporter does not
prove its collectors succeed. No query text, statement collector or extension
is enabled. Incident steps are under [Database](#database).

### AnkiLabs AI

AI Card Actions metrics (Prometheus), LiteLLM's own records through read-only
views (datasource **LiteLLM**: Usage Code metadata and spend, never key hashes,
prompts or answers) and AI Card Actions logs (Loki). The rows are headline
numbers, traffic and errors, latency, input size, tokens and cost, Usage Codes
and LiteLLM spend, and the collapsed logs.

- Bar charts count per bar (about 48 bars over the range; hover for each bar's
  time span), and the AI calls, Cost and Tokens stats add those bars up over
  the dashboard range. Window counts include a series first seen inside the
  window, so the first call after a restart is not lost; they can still be
  fractional. The heatmaps cannot use that correction, so they can miss the
  first call after a restart.
- The Error ratio stat and the per-action ratio follow
  `AnkiLabsAIErrorRatioHigh` (the dashed 20% line): Usage Code errors and
  `ai_refused` are excluded. Errors by code shows every code, `ai_timeout` in
  red.
- Percentiles need at least 5 calls in their window (24 hours for the p95
  stat, 30 minutes for the per-action lines) and stay empty otherwise. Latency
  buckets step 10, 30, 60, 120 s, so upper percentiles are coarse; calls time
  out at 75 s (`ai_timeout`), which the duration heatmap shows in the 60-120 s
  band.
- An answer that AI Card Actions rejected (`ai_output_invalid`) is
  `outcome=error` in metrics but `outcome=success` in its
  `llm.request.completed` record; its tokens and cost still count. `ai_refused`
  and Usage Code errors are errors on the dashboard but not in the alert.
- Reasoning tokens are part of completion tokens: a total is prompt +
  completion. The token bars stack only prompt and completion; reasoning is a
  separate dashed line, never added *(tested)*.
- Durations nest: LiteLLM duration (provider plus proxy) inside LLM duration
  (adds the in-cluster path) inside HTTP duration (adds AI Card Actions' own
  work).
- Usage Code states come from the view: blocked, expired (past `expires`),
  exhausted (spend reached the budget, so LiteLLM rejects its calls) or active.
  They show the current state, not the dashboard range.

Incident steps and the LiteLLM database access are under [AI](#ai).

### QuizLabs Overview

quiz-backend, quiz-multiplayer (Socket.IO), MongoDB and Redis, scoped to
`quizlabs`. Envoy panels select only `httproute/quizlabs/quizlabs/` clusters
(rule 0 backend, rule 1 Socket.IO, rule 2 frontend): proxy requests and
connections, not players, rooms, games, messages or WebSocket sessions. Shared
cloudflared data stays on Platform - Delivery & Edge. MongoDB and Redis have no
exporters, so readiness, resources, claims and logs are evidence, not command
latency or replication health. Legacy logs stay raw; no regex counts pretend
to be failures. Incident steps are under [QuizLabs](#quizlabs).

## Telemetry

In Prometheus:

```promql
up{namespace="ankilabs",job=~"monitoring/(ankilabs-api-gateway|ankilabs-lookups|ankilabs-postgres|ankilabs-ai-card-actions)"}
up{job=~"monitoring/(envoy-proxy|cloudflared)"}
pg_up{namespace="ankilabs"}
pg_scrape_collector_success{namespace="ankilabs"}
gotk_resource_info{ready="False"}
```

Check Prometheus target errors first, then PodMonitor selection/named ports,
network-policy sources, rollout state and exporter logs. Do not “fix” a failed
monitoring login by supplying superuser credentials.

For QuizLabs edge panels, verify the `envoy_cluster_name` series are prefixed
`httproute/quizlabs/quizlabs/`; rule 0 is backend, rule 1 Socket.IO, rule 2 frontend.
This is the pinned Envoy Gateway route-destination naming convention. If a future
version changes it, panels must stay empty until their scope is verified: never
remove the prefix filter. Tunnel counters are shared and deliberately absent from
application dashboards.

## Requests

A single observed 5xx or lookup upstream `timeout`/`unavailable` can alert even
at low traffic. No minimum request volume or error-ratio gate suppresses it.
Counts use counter increases and can be fractional due to scrape extrapolation;
they are not an audit log. A failure's new status series can first be scraped
at one, with no preceding zero: request/upstream alerts also detect newly seen
nonzero failure counters, while raw-counter tables preserve that evidence.
On new scrape discovery this can warn about an older failure; verify log
timestamps rather than asserting exact event recency. Compare latency means
with their sample counts.

```promql
sum by (service, status) (increase(ankilabs_api_gateway_upstream_request_duration_seconds_count{namespace="ankilabs",service=~"Sentence Lookup|Dictionary Lookup",status=~"5..|timeout|unavailable"}[10m]))
```

In Loki, substitute only a synthetic/request ID when investigating:

```logql
{namespace="ankilabs",app=~"api-gateway|sentence-lookup|dictionary-lookup"} | json | request_id="REQUEST_ID"
{namespace="ankilabs",app=~"sentence-lookup|dictionary-lookup"} | json | event="db.stage.started"
{namespace="ankilabs",app="api-gateway"} | json | event="upstream.request.completed" | status=~"timeout|unavailable|5.."
{namespace="ankilabs",app=~"api-gateway|sentence-lookup|dictionary-lookup",severity=~"WARNING|ERROR|CRITICAL|UNKNOWN"}
```

Events include `http.request.started/completed`,
`upstream.request.started/completed`, `db.stage.started/completed` and
`search.completed`. Upstream completion uses `upstream_service` and string
`status`, not `http_status`. A killed process may leave only started breadcrumbs.
No completion metric is fabricated.

## Database

```promql
ankilabs_sentence_lookup_db_pool_connections{namespace="ankilabs",state="waiting"}
sum by (stage, outcome) (increase(ankilabs_sentence_lookup_stage_duration_seconds_count{namespace="ankilabs"}[15m]))
sum by (phase) (increase(ankilabs_sentence_lookup_search_rows_count{namespace="ankilabs"}[15m]))
max by (state) (pg_stat_activity_max_tx_duration{namespace="ankilabs",datname="ankilabs"})
```

```logql
{namespace="ankilabs",app="sentence-lookup"} | json | query_fingerprint="FINGERPRINT"
{namespace="ankilabs",app="postgres",container="postgres"} | json | pg_severity="LOG" | level="WARNING"
{namespace="ankilabs",app="postgres",container="postgres"} | json | db_backend_pid="PID"
```

Correlate PID with request-stage records within a narrow time range; PIDs are
reused. Pool waiters sustained for three minutes indicate measurable pressure,
not proof that increasing pool/server limits is safe. Compare pool_acquire,
candidate_fetch, span_fetch, matching, translations, search, counts and release;
dictionary stages include query, resolve, translate and notes. Stages overlap;
do not sum them into an end-to-end duration. PostgreSQL checkpointer metrics use
the PG17+ collector, not old bgwriter checkpoint fields.

## AI

Use AnkiLabs - AI. It combines AI Card Actions metrics, LiteLLM's own records
from PostgreSQL (datasource **LiteLLM**, uid `litellm`) and AI Card Actions logs.
AI Card Actions must expose `/metrics` (ai-card-actions PR #9) before this
scrape is deployed; otherwise `AnkiLabsScrapeFailed` reports the target.

`AnkiLabsAIErrorRatioHigh` fires when more than 20% of one action's LLM calls
failed over 15 minutes, with at least 3 calls. Usage Code errors
(`usage_code_*`, user state) and `ai_refused` (the model declined; the user
gets 422) are excluded; `ai_output_invalid` (an answer returned but unusable)
counts. All codes stay visible on the dashboard. Window counts include a series
first seen inside the window, so the first failure after a restart is not lost.

```promql
sum by (action, error_code) (increase(ankilabs_ai_card_actions_llm_errors_total{namespace="ankilabs"}[1h]))
sum by (action, outcome) (increase(ankilabs_ai_card_actions_llm_request_duration_seconds_count{namespace="ankilabs"}[1h]))
```

```logql
{namespace="ankilabs",app="ai-card-actions"} | json | event="llm.request.completed" | error_code="ai_timeout"
{namespace="ankilabs",app="ai-card-actions"} | json | event="llm.output.rejected"
```

Each call has one `llm.request.completed` record with `duration_ms`,
`input_chars` and token/cost fields. A rejected answer logs `outcome=success`
there but is `outcome=error` in metrics, and its tokens and cost still count.
Compare AI Card Actions' LLM duration with LiteLLM's own duration for the same
model: a similar value points at the provider, a larger gap at the in-cluster
path. Calls time out at 75 seconds (`LLM_PROXY_TIMEOUT_SECONDS`); check input
size before raising it. Reasoning tokens are part of completion tokens.

### LiteLLM database access for Grafana

The `llm-proxy` chart provisions everything; there is no manual SQL. Its
pre-install/pre-upgrade bootstrap Job creates the `grafana_litellm` login
(`NOINHERIT`, connection limit 3, read-only transactions, 10-second statement
timeout, `CONNECT` on `litellm` only) with the password from Secret
`ankilabs/llm-proxy-grafana`, and drops the views. After the proxy is ready,
and so after LiteLLM's migrations, the `llm-proxy-grafana-views` Job recreates
the views from `k8s/apps/ankilabs/charts/llm-proxy/files/grafana-views.sql`
in schema `grafana`. The views expose no key hash, prompt, response or request
metadata, and the login has no grant on LiteLLM's tables. Like every role, it
can connect to the `ankilabs` database through PUBLIC's default `CONNECT`, but
it cannot read its tables.

If the database panels report that a `grafana.*` relation does not exist, read
the Job log. A LiteLLM upgrade that changed a column the views read logs a
warning there without failing the release:

```sh
kubectl -n ankilabs logs job/llm-proxy-grafana-views
```

Fix `grafana-views.sql` against the new LiteLLM schema. To recreate the views
without an upgrade, from the homelab checkout:

```sh
kubectl -n ankilabs exec -i statefulset/postgres -c postgres -- \
  psql -X -U ankilabs -d litellm -v ON_ERROR_STOP=1 --single-transaction \
  -v grafana_role=grafana_litellm \
  < k8s/apps/ankilabs/charts/llm-proxy/files/grafana-views.sql
```

### Rotate the Grafana LiteLLM password

The same password is in two SOPS Secrets: `llm-proxy-grafana`
(`k8s/apps/ankilabs/llm-proxy/grafana-secrets.yaml`, applied to PostgreSQL by
the bootstrap Job) and `monitoring/grafana-litellm-database`
(`k8s/platform/monitoring/controllers/kube-prometheus-stack/grafana-litellm-secrets.yaml`,
read by Grafana). It must be URL-safe:

```sh
python3 -c 'import secrets; print(secrets.token_urlsafe(32))'
sops k8s/apps/ankilabs/llm-proxy/grafana-secrets.yaml
sops k8s/platform/monitoring/controllers/kube-prometheus-stack/grafana-litellm-secrets.yaml
```

Set the same value in both editors, then commit and merge. After Flux applies
the Secrets, run the bootstrap Job with a forced Helm upgrade (the proxy keeps
running; its pod template does not change) and restart Grafana, which reads the
password only at startup:

```sh
now="$(date -u +%s)"
kubectl -n ankilabs annotate helmrelease/llm-proxy \
  reconcile.fluxcd.io/requestedAt="$now" reconcile.fluxcd.io/forceAt="$now" --overwrite
kubectl -n ankilabs get helmrelease llm-proxy -w
kubectl -n monitoring rollout restart deployment/kube-prometheus-stack-grafana
```

Between the two steps the LiteLLM panels fail authentication; nothing else is
affected.

## Resources

Check Homelab Overview and the affected application's dashboard for availability,
restarts, OOM reasons, working set versus configured limits, node pressure and
volume capacity. Confirm a recent restart alongside a last-terminated OOM reason;
the latter alone can be stale. Missing resource limits/volume metrics stay absent.
Investigate cause before changing resources, retries or timeouts.

## Storage

Use Platform - Storage. Every PVC is an `openebs-hostpath` directory under
`/var/openebs/local` on the node filesystem, so all volumes share one pool of free
space and requested PVC sizes are not enforced. The node filesystem panels are
authoritative for free space; kubelet volume stats for hostpath volumes may be
absent or filesystem-wide, so identical numbers across PVCs are not per-volume
usage. Prometheus keeps 7 days or 8GB of TSDB data on a 10Gi claim, whichever
limit is reached first; Alertmanager keeps silences on a 1Gi claim.

`NodeFilesystemLowSpace` fires below 15% free for 10 minutes and
`NodeFilesystemFillingUp` when the 6-hour trend reaches zero within 3 days for
an hour. Both route to the node receiver. Find the growing consumer first:

```promql
sort_desc(max by (namespace, persistentvolumeclaim) (delta(kubelet_volume_stats_used_bytes[24h])))
prometheus_tsdb_storage_blocks_bytes{namespace="monitoring"}
pg_database_size_bytes{namespace="ankilabs"}
```

```sh
kubectl get pvc -A
sudo du -sh /var/openebs/local/* | sort -h
```

Loki, MinIO, MongoDB and Redis expose no scraped storage metrics; measure their
directories on the node. Do not delete volume directories by hand: remove data
through the owning application, or lower its retention and let it compact.

## QuizLabs

Use the single QuizLabs overview for backend/multiplayer availability, route-bound
proxy counters, resource/OOM/storage evidence and separate component log streams:

```logql
{namespace="quizlabs",app="quiz-backend"}
{namespace="quizlabs",app="quiz-multiplayer"}
{namespace="quizlabs",app="mongodb"}
{namespace="quizlabs",app="redis"}
```

Readiness is not a successful datastore command. Active proxy connections are
not active players, Socket.IO rooms, messages or WebSocket-session totals.
MongoDB/Redis command latency, replication and application-level game outcomes
remain uninstrumented; no such metrics are invented here.

## Limitations and dependency sources

- Promtail is deprecated/EOL (March 2, 2026). This deliberately pins its existing
  supported pipeline capabilities rather than slipping in an agent migration.
  Plan a separately approved supported-agent migration. Loki's configured retention
  period is 24 hours; compactor enforcement has not been verified here.
  Outages/positions loss/container rotation can lose logs.
  Log ingestion is not an authoritative request or failure counter.
- PG keeps stderr with `logging_collector=off`; blindly switching to `jsonlog`
  would move records to files the current collector does not tail. Statement,
  duration-sampled SQL and parameter logging are disabled; TERSE removes
  DETAIL/HINT/QUERY/CONTEXT. Parsed ERROR/FATAL/PANIC text is additionally redacted
  before Loki because primary errors can quote input. Raw node/container logs
  can still contain primary diagnostics, and unknown/unparsed records are
  intentionally preserved. This is not a universal content scrubber: protect
  node-log access, use bound parameters/static application diagnostics, and
  verify synthetic privacy cases before rollout. Old Loki records are unchanged.
- Envoy's default access logs include the original request URI. They are replaced
  with allowlisted JSON fields: route **name**, never raw path, query, headers or
  body. No application request correlation is inferred from edge connection counts.
- PostgreSQL exporter:
  [v0.20.1 release](https://github.com/prometheus-community/postgres_exporter/releases/tag/v0.20.1),
  [pinned configuration/PG support](https://github.com/prometheus-community/postgres_exporter/blob/v0.20.1/README.md),
  [official registry tag/digest](https://quay.io/api/v1/repository/prometheuscommunity/postgres-exporter/tag/?specificTag=v0.20.1),
  [PG17+ checkpointer collector](https://github.com/prometheus-community/postgres_exporter/blob/v0.20.1/collector/pg_stat_checkpointer.go).
  Image manifest-list digest:
  `sha256:ac5ec343104fae0e2d84a27bb8d69b38430a11910c5382cad85d478d2bab713e`.
- PostgreSQL 18:
  [logging behavior/settings](https://www.postgresql.org/docs/18/runtime-config-logging.html),
  [predefined monitoring roles](https://www.postgresql.org/docs/18/predefined-roles.html).
- Envoy Gateway v1.7.1:
  [native scrape configuration](https://github.com/envoyproxy/gateway/blob/v1.7.1/examples/kubernetes/metric/pod-monitor.yaml),
  [proxy metrics](https://github.com/envoyproxy/gateway/blob/v1.7.1/site/content/en/latest/tasks/observability/proxy-metric.md),
  [access logging](https://github.com/envoyproxy/gateway/blob/v1.7.1/api/v1alpha1/envoyproxy_accesslogging_types.go),
  [route naming](https://github.com/envoyproxy/gateway/blob/v1.7.1/internal/gatewayapi/helpers.go).
- Cloudflared 2026.10.0:
  [HA connections](https://github.com/cloudflare/cloudflared/blob/2026.10.0/supervisor/metrics.go),
  [native request/response/error counters](https://github.com/cloudflare/cloudflared/blob/2026.10.0/proxy/metrics.go).
- Promtail:
  [pinned chart/application version](https://github.com/grafana/helm-charts/blob/promtail-6.17.1/charts/promtail/Chart.yaml),
  [supported template functions](https://github.com/grafana/loki/blob/v3.5.0/clients/pkg/logentry/stages/template.go),
  [lifecycle notice](https://grafana.com/docs/loki/latest/send-data/promtail/).
