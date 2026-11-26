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
`promtool check rules` for alerts **and all dashboard PromQL**, twenty-three real
Prometheus evaluator cases, the Discord title/message templates rendered by
Alertmanager's own `amtool` (see [Alerts](#alerts)), the node-exporter volume-usage sidecar's pinned
privileges and one run of its script over a synthetic volume tree (checked
with `promtool check metrics`; it needs `sh` and `du`), and actual Promtail
stdin/dry-run replay tests.
The checked-in dashboard schema is a focused provisioning contract, not the
entire Grafana API schema. Vendored dashboards (`configs/dashboards/vendor/`)
are exempt from the schema and style rules; `tests/test_vendored_dashboards.py`
still checks their UIDs, folder, recorded commit and PromQL syntax.

Dependencies are Python with `tests/requirements.txt`, Helm, Kustomize,
Prometheus' `promtool`, the Promtail **3.5.1** binary corresponding to pinned
chart **6.17.1**, and `amtool` from Alertmanager **0.28.1**, the version
kube-prometheus-stack 69.8.2 runs. Missing binaries fail explicitly, never silently skip. Supply
`PROMTAIL_BIN`, `PROMTOOL_BIN`, `HELM_BIN`, `KUSTOMIZE_BIN` or `AMTOOL_BIN` if needed. If a
missing-tool failure occurs, install only the missing tools before rerunning:

```sh
python3 -m pip install -r k8s/platform/monitoring/tests/requirements.txt ruff pylint pytest
brew install helm kustomize prometheus
npm install --global markdownlint-cli2
```

Obtain the appropriate Promtail 3.5.1 binary from the
[official release](https://github.com/grafana/loki/releases/tag/v3.5.1) and set
`PROMTAIL_BIN` to its absolute path. Do not silently substitute another agent.
Likewise take `amtool` from the
[Alertmanager 0.28.1 release](https://github.com/prometheus/alertmanager/releases/tag/v0.28.1)
and set `AMTOOL_BIN`; template functions differ between Alertmanager versions.
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

After changing the node-exporter values, render it the same way and check the
DaemonSet: node-exporter has `--collector.textfile.directory=/run/textfile`
and mounts it read-only; the `volume-usage` container mounts it writable,
mounts `/var/openebs/local` read-only and keeps its security context:

```sh
python3 -c 'from pathlib import Path; import yaml; print(yaml.safe_dump(yaml.safe_load(Path("k8s/platform/monitoring/controllers/kube-prometheus-stack/release.yaml").read_text())["spec"]["values"]))' |
  helm template kube-prometheus-stack oci://ghcr.io/prometheus-community/charts/kube-prometheus-stack \
    --version 69.8.2 --namespace monitoring --values - --show-only charts/prometheus-node-exporter/templates/daemonset.yaml
```

Inspect changed-file editor diagnostics as well; no editor Problems API is
available to the command-line suite. No workflow, commit, image push or live
deployment is part of these commands.

## Operator acceptance

After an explicitly authorized rollout:

1. Grafana must contain exactly the seven provisioned dashboards and the two
   vendored Flux dashboards, in the
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
   receiver in the [message format](#alerts), including their dashboard/runbook
   links. Namespace matcher strategy
   `None` is required because the config lives in `monitoring`, but alert labels
   retain `ankilabs`/`quizlabs`. Config selection stays restricted to the existing
   monitoring namespace/label. Node alerts still use the node receiver; unrelated
   unscoped/default chart alerts still use the existing discard route.
6. Confirm native edge targets are internal only. Envoy uses named `metrics`
   port `/stats/prometheus`, selected for the platform/homelab-gateway proxy.
   Cloudflared already binds `:2000`; it now declares that named port and permits
   monitoring ingress only. No public admin Service/HTTPRoute is added.
7. After the node-exporter pods restart with the volume-usage sidecar, the
   Platform - Storage scan tiles show an age under 6 minutes, 0 errors and as
   many volumes measured as bound claims, and the Volume inventory shows each
   claim's own used bytes, far below the node disk size.

## Alerts

Rules live in `configs/alerts.yaml`; `configs/alertmanager-config.yaml` routes
`scope=nodes` to the node Discord channel and `pods`, `applications`,
`database` and `platform` to the pod channel. Everything else is discarded.

### Discord message format

Both receivers use the same title and message templates. A notification is one
group: alerts with the same `alertname` and `namespace` (node alerts have no
namespace, so one message covers every node). Alertmanager waits 30 seconds
for related alerts before the first message, sends changes to a group at most
every 5 minutes and repeats an unchanged firing group every 4 hours.

Firing:

```text
Edge upstream failure · warning
AnkiLabs API (/api) · since 18:49 UTC
[Dashboard](https://grafana.ankilabs.org/d/ankilabs-service-health) · [Runbook](https://github.com/liav-hasson/homelab/blob/main/k8s/platform/monitoring/runbook.md#requests)
```

Resolved:

```text
Resolved · Pod crash-looping
ankilabs/api-gateway-0 (api-gateway) · lasted 12m 5s
ankilabs/api-gateway-1 (api-gateway) · lasted 1h 2m 0s
```

- The title is the alert's `name` annotation and its severity, or
  `Resolved ·` and the name. The embed color (red or green) also shows the
  status.
- Each line is one alert: its `subject` annotation and the UTC time it started
  or how long it lasted. Members of a firing group that already recovered are
  listed as `resolved, lasted …`.
- At most 10 firing and 10 resolved lines are listed, followed by `and N more`,
  which keeps messages far below Discord's 4096-character limit. Alertmanager
  itself truncates longer titles (256) and messages.
- The last line of a firing message links the first alert's dashboard and
  runbook section. Descriptions, empty labels and Prometheus' internal source
  URL are not sent. The message contains no emoji.

`EdgeUpstreamFailure` names each Envoy route after its HTTPRoute rule through a
`route` label: `AnkiLabs API (/api)`, `AnkiLabs web (/)`, `QuizLabs API (/api)`,
`QuizLabs multiplayer (/socket.io)` and `QuizLabs web (/)`. An unmapped rule
falls back to `<namespace>/<route> rule <index>`. AnkiLabs API failures link
AnkiLabs - Service Health, other routes Platform - Edge, which names routes the
same way. When a rule
is added to or reordered in `k8s/apps/*/httproute.yaml`, update the mapping in
the alert and the dashboard; `tests/test_alert_notifications.py` and
`tests/test_edge_dashboard.py` fail until they match.

### Add an alert

1. Add the rule to the matching group in `configs/alerts.yaml` with labels
   `scope` (`nodes`, `pods`, `applications`, `database` or `platform`) and
   `severity` (`warning` or `critical`).
2. Give it exactly these annotations:

   | Annotation | Content |
   | --- | --- |
   | `name` | Short title in sentence case, at most 40 characters, such as `Pod restarting` |
   | `subject` | What is affected, from labels, such as `'{{ $labels.namespace }}/{{ $labels.pod }}'`; add a value only when it helps, such as `'{{ $value \| humanizePercentage }} used'` |
   | `description` | One sentence of at most 120 characters stating the condition; it is shown in Alertmanager and Grafana, not in Discord |
   | `dashboard_url` | `https://grafana.ankilabs.org/d/<uid>` of the most useful dashboard |
   | `runbook_url` | This file's URL with the anchor of the section that has the first steps |

3. Put investigation steps in the runbook section, not in annotations, and add
   the alert to the reference below.
4. Add a positive and a negative case to `tests/rule-cases.yaml`. Its expected
   annotations are filled from the rule; a case lists only annotations that use
   `$value` or a conditional. Run the [local validation](#local-validation).

To see a message in Discord without a real failure, send a short-lived test
alert to Alertmanager from a machine with cluster access:

```sh
kubectl -n monitoring port-forward svc/kube-prometheus-stack-alertmanager 9093:9093
amtool --alertmanager.url=http://localhost:9093 alert add alertname=DiscordFormatTest \
  scope=pods severity=warning namespace=monitoring \
  --annotation=name='Discord format test' --annotation=subject='test alert' \
  --annotation=dashboard_url=https://grafana.ankilabs.org/d/homelab-overview \
  --annotation=runbook_url=https://github.com/liav-hasson/homelab/blob/main/k8s/platform/monitoring/runbook.md#alerts
```

The firing message arrives after the 30-second group wait. Repeat the command
with `--end="$(date -u +%Y-%m-%dT%H:%M:%SZ)"` to resolve it; the resolved
message follows within 5 minutes.

### Alert reference

| Alert | Discord name | Fires when | First checks |
| --- | --- | --- | --- |
| `NodeHighCPU` | Node CPU high | Node CPU above 90% for 5 minutes | Competing workloads before resizing ([Resources](#resources)) |
| `NodeHighMemory` | Node memory high | Node memory above 90% for 5 minutes | Working sets and OOM events ([Resources](#resources)) |
| `NodeFilesystemLowSpace` | Node disk low | Below 15% free for 10 minutes | The growing volume before deleting data; every openebs-hostpath volume shares this disk ([Storage](#storage)) |
| `NodeFilesystemFillingUp` | Node disk filling up | The 6-hour trend fills the disk within 3 days, for an hour | Confirm the trend; restores and image pulls cause short bursts ([Storage](#storage)) |
| `PersistentVolumeNearRequestedSize` | Volume near requested size | A claim uses over 90% of its request for 30 minutes | What grew; remove data through the application, lower retention or plan a larger claim ([Storage](#storage)) |
| `OpenEBSVolumeScanStale` | Volume usage scan stale | No volume scan newer than 20 minutes for 5 minutes | Sidecar log and textfile collector; per-volume panels are stale ([Per-volume usage](#per-volume-usage)) |
| `PodCrashLoopBackOff` | Pod crash-looping | A container in CrashLoopBackOff for 5 minutes | Container logs and last termination reason ([Resources](#resources)) |
| `PodFrequentRestarts` | Pod restarting | 3 or more restarts in 15 minutes | Container logs and last termination reason ([Resources](#resources)) |
| `AnkiLabsRequestFailure` | AnkiLabs request failure | A 5xx counter increased or first appeared | `request_id` and timestamps in namespace logs; a new scrape can expose an older failure ([Requests](#requests)) |
| `AnkiLabsUpstreamFailure` | AnkiLabs lookup upstream failure | A gateway-to-lookup 5xx, timeout or unavailable counter increased or first appeared | Gateway and lookup logs by `request_id` before retrying ([Requests](#requests)) |
| `AnkiLabsScrapeFailed` | AnkiLabs metrics scrape failing | A target failed scrapes for 3 minutes | Target error, named port, network policy, exporter credentials ([Telemetry](#telemetry)) |
| `AnkiLabsExpectedTargetMissing` | AnkiLabs metrics target missing | No target for a service for 5 minutes | PodMonitor selection, desired replicas, the postgres-monitoring Secret ([Telemetry](#telemetry)) |
| `AnkiLabsAIErrorRatioHigh` | AnkiLabs AI calls failing | Over 20% of an action's LLM calls failed in 15 minutes (3 or more calls) | Errors by code, especially `ai_timeout`, and LiteLLM's duration ([AI](#ai)) |
| `ApplicationDeploymentUnavailable` | Deployment unavailable | No available replica for 5 minutes | Rollout conditions and namespace logs ([Resources](#resources)) |
| `ApplicationOOMKilled` | Container OOM killed | Last termination was an OOM kill, with a recent restart | Memory against its limit before changing limits ([Resources](#resources)) |
| `LookupPoolWaiting` | Lookup DB pool waiting | Pool waiters for 3 minutes | Pool size and acquire samples, PostgreSQL activity ([Database](#database)) |
| `PostgreSQLUnavailable` | PostgreSQL unreachable | `pg_up` is 0 for 2 minutes | Exporter logs: outage, credentials or network policy; never use superuser credentials ([Database](#database)) |
| `PostgreSQLCollectorFailure` | PostgreSQL collector failing | A collector failed for 3 minutes | Exporter logs, PostgreSQL version and monitoring grants ([Database](#database)) |
| `QuizLabsMongoUnavailable` | QuizLabs MongoDB unavailable | No ready MongoDB replica for 5 minutes | Pod readiness, restarts, storage, quizlabs logs ([QuizLabs](#quizlabs)) |
| `EdgeUpstreamFailure` | Edge upstream failure | Envoy connect-failure or timeout counter of an AnkiLabs or QuizLabs route increased or first appeared | Endpoint readiness and the application's logs; retries can hide user impact ([Requests](#requests)) |
| `EdgeScrapeFailed` | Edge telemetry missing | Envoy or cloudflared metrics missing or failing for 5 minutes | Envoy's internal metrics port, cloudflared port 2000; never expose admin endpoints ([Telemetry](#telemetry)) |

## Dashboards

Seven dashboards are provisioned from `configs/dashboards/*.json` and two
unmodified upstream Flux dashboards from `configs/dashboards/vendor/`, one
ConfigMap per Grafana folder:

| Folder | Dashboards |
| --- | --- |
| AnkiLabs | AnkiLabs - Service Health, AnkiLabs - Search & PostgreSQL, AnkiLabs - AI |
| QuizLabs | QuizLabs - Overview |
| Platform | Homelab Overview, Platform - Edge, Platform - Storage, Flux Cluster Stats, Flux Control Plane |

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
*(tested)*. They do not apply to the vendored Flux dashboards, which stay as
upstream ships them (see [Flux dashboards](#flux-dashboards)).

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

Start here. The top rows are the at-a-glance view: node CPU, memory and
filesystem gauges, scrape targets up/down, firing alerts, unready workloads,
and one tile per area (AnkiLabs and QuizLabs replicas ready, Flux objects
ready, weakest tunnel replica) that opens its dashboard when clicked. Below are
the active alert list, workload availability, trends, volume usage, node
pressure and scrape coverage. Availability is Kubernetes readiness, not a
synthetic user journey. Firing alerts leave out the always-on Watchdog and
InfoInhibitor and show 0 only while Watchdog fires, so an empty tile means rule
evaluation itself is unknown. Then go to Platform - Edge for Envoy and
cloudflared; Flux Cluster Stats and Flux Control Plane for Flux;
Platform - Storage for disk space, volumes and I/O; AnkiLabs - Service Health
for request failures; AnkiLabs - Search & PostgreSQL for lookup stages and
pools; AnkiLabs - AI for AI calls, Usage Codes and spend; QuizLabs - Overview
for the legacy stack. Node and pod alerts link here; their steps are under
[Resources](#resources).

### Platform Delivery and Edge

The **Platform - Edge** dashboard (UID `platform-delivery-edge`, formerly
Platform - Delivery & Edge; the UID and this heading stay so alert and runbook
links keep working). Flux delivery moved to the [Flux dashboards](#flux-dashboards).

- Envoy panels read only the application routes,
  `envoy_cluster_name=~"httproute/(ankilabs|quizlabs)/.*"` *(tested)*. Grafana
  is served through the same gateway (`httproute/monitoring/grafana/rule/0`)
  and its own dashboard queries used to dominate every Envoy panel; it and
  Envoy's internal clusters are left out.
- Routes are named by HTTPRoute rule. `label_replace` in each query sets a
  `route` label, so legends, pie slices and tooltips agree, and the access-log
  panel uses the same names. A rule without a name shows as
  `<namespace>/<route> rule <index>` (the same form as the alert annotations);
  `tests/test_edge_dashboard.py` fails until every rule in
  `k8s/apps/{ankilabs,quizlabs}/httproute.yaml` has one, ending in its path
  prefix *(tested)*:

  | Envoy cluster | Route |
  | --- | --- |
  | `httproute/ankilabs/ankilabs/rule/0` | AnkiLabs API (/api) |
  | `httproute/ankilabs/ankilabs/rule/1` | AnkiLabs web (/) |
  | `httproute/quizlabs/quizlabs/rule/0` | QuizLabs API (/api) |
  | `httproute/quizlabs/quizlabs/rule/1` | QuizLabs multiplayer (/socket.io) |
  | `httproute/quizlabs/quizlabs/rule/2` | QuizLabs web (/) |

- Envoy sees route rules, not endpoints. Per-endpoint data (for example
  `/v1/review`) is in the API Gateway metrics on AnkiLabs - Service Health and
  AnkiLabs - AI.
- Count bars cover one bar interval (15 minutes, longer on wide ranges); shares
  cover the selected time range. Timeouts are requests Envoy gave up on after
  the route timeout (95 s for AnkiLabs API, Envoy's 15 s default elsewhere);
  connect failures are connections it could not open.
- The latency heatmaps show Envoy's upstream time
  (`envoy_cluster_upstream_rq_time`, milliseconds): Envoy to backend, not
  browser time. QuizLabs multiplayer has none, because Socket.IO long-polling
  and WebSockets hold requests open by design.
- Cloudflared counters cover the whole tunnel and cannot be split per
  application, so application dashboards show only route-bound Envoy data.
- The Envoy access-log panel shows only application-route records that
  returned 5xx, carry an Envoy response flag (`UF`, `UT`, `DC`, ...) or were
  slow (thresholds below), as
  `route status method duration [flags]`. Grafana's route, records without an
  application route (such as health checks) and fast successful requests are
  left out; query `{namespace="envoy-gateway-system",app="envoy"}` in Explore
  for everything. Envoy's own runtime records (severity `UNKNOWN`) have their
  own panel. Slow is 30 s or more on AnkiLabs API, where AI calls normally take
  10-20 s (well below its 95 s route timeout; the AI Card Actions slow log
  uses 45 s), and 2 s or more on the other routes. QuizLabs multiplayer shows
  only on errors, because Socket.IO holds requests open by design.

No log regex is used as a failure counter. Native scrape ports stay internal;
there is no public admin route. Target checks are under
[Telemetry](#telemetry).

### Flux dashboards

**Flux Cluster Stats** (`flux-cluster`) and **Flux Control Plane**
(`flux-control-plane`) are copied unmodified from
[fluxcd/flux2-monitoring-example](https://github.com/fluxcd/flux2-monitoring-example)
at commit `7ab65dc8b90f7a6751d88f18bbb4e1bee33bf334` into
`configs/dashboards/vendor/`. Cluster Stats shows readiness, suspension and
reconciliation duration per Flux object (kube-state-metrics
`gotk_resource_info` and the controllers' `gotk_reconcile_duration_seconds`);
Control Plane shows the controllers' reconciliations, work queues, Kubernetes
API requests, CPU and memory (Flux PodMonitor and cAdvisor). The Homelab
Overview Flux tile opens Flux Cluster Stats.

They keep the upstream layout: their own `DS_PROMETHEUS` variable, no runbook
link or Monitoring menu, and percentiles without sample guards. To update
them, follow `configs/dashboards/vendor/README.md` (replace both files from a
new upstream commit and record the commit) and run the monitoring tests.

### Platform Storage

Read it top to bottom: headline numbers, then the **node disk**
(node-exporter, authoritative for free space), **persistent volumes**
(per-volume usage from the node-exporter volume-usage sidecar, joined to
kube-state-metrics claims), **disk performance**, **application self-metrics**
(Prometheus TSDB, PostgreSQL) and, collapsed, the OpenEBS provisioner logs.

- Every PVC is an `openebs-hostpath` directory on the node filesystem, so all
  volumes share one pool of free space and requested sizes are not enforced.
  Volume usage is the disk space allocated to each volume directory, measured
  with `du` every 5 minutes, so it moves in 5-minute steps (see
  [Storage](#storage)). The per-volume bars divide it by the **requested** size:
  over 100% means the volume outgrew its request, not that it is full.
- The four scan tiles under Persistent volumes say whether those numbers are
  current: scan age (red after 20 minutes), scan duration, directories `du`
  could not fully read plus scan-file read errors, and volumes measured against
  bound claims. Total PVC used counts every volume directory, including those
  without a claim.
- Days until full uses the 24h linear decline of free space; **Not filling**
  means free space did not shrink over 24h. The 3-day projection uses the
  alert's 6h trend. Short write bursts (image pulls, restores, compaction)
  exaggerate both.
- Throughput and IOPS draw reads above zero and writes below it. 100% busy is
  not saturation on NVMe; read it with queue depth and latency.
- Prometheus at 100% of its size cap is expected once the cap is reached: it
  then deletes the oldest blocks (retention block deletions, size) and keeps
  less than 7 days.

Loki, MinIO, MongoDB and Redis expose no storage metrics; their volume usage
comes only from the scan. Incident steps are under [Storage](#storage).

### AnkiLabs Service Health

All data is restricted to the `ankilabs` namespace. A failure is an observed
5xx or an explicit upstream `timeout`/`unavailable`, never a keyword count.
Each service has requests, 5xx share and p95 at the top, then request and
failure bars, a latency heatmap and a p95 line. A p95 needs at least 5 requests
in its 15-minute window and stays empty otherwise; buckets step 2.5, 5, 10, 30,
60 and 120 s, so slow percentiles are coarse. The mean by route beside it
includes failures; zero observations give no mean. A 5xx share is empty
without traffic. A request killed before completing leaves started breadcrumbs
but no latency sample. Raw failure counters since process start are in a
collapsed row. Request IDs are parsed only at query time. Incident steps are under [Requests](#requests) and [Resources](#resources).

### AnkiLabs Search and PostgreSQL

All data is restricted to `ankilabs`. The top row is lookup requests, 5xx
share, p95, pool waiters and exporter health. Stage heatmaps show one stage at
a time: pick it with the **Sentence stage** and **Dictionary stage** variables;
the row heatmap uses **Search phase**. Compare each stage's p95 and mean with
its observations and error outcomes; stages overlap, so never add their times
into a request total. Started events locate the last stage when a process dies before
completing. Pool states (size, available, waiting, max) are separate, not
additive; connections in use is size minus available, over max. Connections
used counts every database's backends against `max_connections`, and the cache
hit ratio covers 15 minutes and is empty when the database was idle. Row
histograms are per-phase observations, not SQL execution plans.
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
connections, not players, rooms, games, messages or WebSocket sessions. Their
5xx share uses Envoy's response classes (`envoy_cluster_upstream_rq_xx`) and
latency is Envoy's upstream time to the backend
(`envoy_cluster_upstream_rq_time`, milliseconds), not browser latency.
Socket.IO is left out of the p95: long-polling holds requests open by design.
Shared
cloudflared data stays on Platform - Edge. MongoDB and Redis have no
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
authoritative for free space. kubelet volume stats report that whole filesystem
for every hostpath claim, so no dashboard or alert reads them. Prometheus keeps
7 days or 8GB of TSDB data on a 10Gi claim, whichever limit is reached first;
Alertmanager keeps silences on a 1Gi claim.

`NodeFilesystemLowSpace` fires below 15% free for 10 minutes and
`NodeFilesystemFillingUp` when the 6-hour trend reaches zero within 3 days for
an hour. `PersistentVolumeNearRequestedSize` fires when a claim's volume has
used more than 90% of its requested size for 30 minutes; the volume keeps
growing into the shared disk, so treat it as an early warning for that disk.
`OpenEBSVolumeScanStale` fires when no volume scan newer than 20 minutes is
scraped for 5 minutes. All four route to the node receiver.

Find the growing consumer first:

```promql
sort_desc(delta((max by (persistentvolume) (openebs_hostpath_volume_used_bytes))[24h:5m]))
kube_persistentvolumeclaim_info{volumename="VOLUME"}
prometheus_tsdb_storage_blocks_bytes{namespace="monitoring"}
pg_database_size_bytes{namespace="ankilabs"}
```

```sh
kubectl get pvc -A
sudo du -sh /var/openebs/local/* | sort -h
```

Loki, MinIO, MongoDB and Redis expose no scraped storage metrics of their own;
their volume usage comes only from the [volume scan](#per-volume-usage). Do not
delete volume directories by hand: remove data through the owning application,
or lower its retention and let it compact.

### Per-volume usage

The `volume-usage` sidecar in each node-exporter pod (kube-prometheus-stack
release values, `prometheus-node-exporter.sidecars`) runs `du -skx` on every
`/var/openebs/local/pvc-*` directory every 5 minutes at the lowest CPU and I/O
priority. It writes `openebs-hostpath.prom` atomically into an in-memory
directory that node-exporter's textfile collector reads:

| Metric | Meaning |
| --- | --- |
| `openebs_hostpath_volume_used_bytes{persistentvolume}` | Disk space allocated to the volume directory |
| `openebs_hostpath_volume_scan_errors` | Directories `du` could not fully read in the last scan |
| `openebs_hostpath_volume_scan_duration_seconds` | Duration of the last scan |
| `openebs_hostpath_volume_scan_timestamp_seconds` | Unix time the last scan finished |

Dashboards join the volume name to its claim through kube-state-metrics, whose
`volumename` label names the bound volume:

```promql
max by (namespace, persistentvolumeclaim) (
  max by (persistentvolume) (openebs_hostpath_volume_used_bytes)
  * on (persistentvolume) group_left (namespace, persistentvolumeclaim)
  max by (namespace, persistentvolumeclaim, persistentvolume) (
    label_replace(kube_persistentvolumeclaim_info, "persistentvolume", "$1", "volumename", "(.+)")
  )
)
```

Application dashboards filter `kube_persistentvolumeclaim_info` by their own
namespace, so they never show another application's volumes.

Caveats:

- Values are up to 5 minutes old, plus the scrape interval. Short bursts
  between scans are not seen.
- Sizes are allocated blocks, as `df` and kubelet count them for real
  filesystems: sparse files count only written blocks, and each small file at
  least one block. `du` counts a file hard-linked inside one volume once.
- `du` walks every file of every volume, so each scan costs metadata I/O that
  grows with the file count; the scan duration tile shows it. The idle I/O class
  takes effect only with an I/O scheduler that supports it (BFQ), not with
  `none`, the usual NVMe default.
- A directory `du` could not fully read still reports what it read, so its
  value can be too low while `openebs_hostpath_volume_scan_errors` is above 0.
- The sidecar runs as root with only the `DAC_READ_SEARCH` capability (read
  any file, no write or ownership changes), on a read-only mount of
  `/var/openebs/local` and a read-only root filesystem. It shares the
  node-exporter pod's host network and host PID namespaces.
- Directories without a claim (released volumes) appear in Total PVC used and
  Volumes measured, but not in the per-claim panels.

If the scan tiles are stale, empty or report errors, read the sidecar log and
the current file. The textfile collector reports its own read failures as
`node_textfile_scrape_error`:

```sh
kubectl -n monitoring get pods -l app.kubernetes.io/name=prometheus-node-exporter
kubectl -n monitoring logs <node-exporter pod> -c volume-usage
kubectl -n monitoring exec <node-exporter pod> -c volume-usage -- cat /run/textfile/openebs-hostpath.prom
```

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
