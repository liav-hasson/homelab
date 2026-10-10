# Node memory budget

Single node, 16 GiB (see the spec's CD requirements). Update this table whenever a component is added or resized.
Values are what the manifests in this repository declare; "-" means nothing is declared.

| Component | Request | Limit | Declared in |
|---|---|---|---|
| **AnkiLabs** | | | |
| postgres | 2 GiB | 4 GiB | `k8s/apps/ankilabs/postgres/release.yaml` |
| api-gateway | 96 MiB | 192 MiB | `k8s/apps/ankilabs/api-gateway/release.yaml` |
| frontend | 32 MiB | 64 MiB | `k8s/apps/ankilabs/frontend/release.yaml` |
| dictionary-lookup | 128 MiB | 256 MiB | `k8s/apps/ankilabs/dictionary-lookup/release.yaml` |
| sentence-lookup | 128 MiB | 256 MiB | `k8s/apps/ankilabs/sentence-lookup/release.yaml` |
| **quizlabs** (kept for now) | | | |
| mongodb | 1 GiB | 2 GiB | `k8s/apps/quizlabs/stateful/mongodb/values.yaml` |
| quiz-backend | 256 MiB | 512 MiB | `quiz-backend/values.yaml` |
| quiz-multiplayer | 256 MiB | 512 MiB | `quiz-multiplayer/values.yaml` |
| quiz-frontend | 128 MiB | 256 MiB | `quiz-frontend/values.yaml` |
| redis | 128 MiB | 256 MiB | `stateful/redis/values.yaml` |
| **Platform** | | | |
| flux controllers (6) | 6 x 64 MiB | 6 x 1 GiB | `k8s/flux-system/gotk-components.yaml` |
| cloudflared (2 replicas) | 2 x 64 MiB | 2 x 128 MiB | `k8s/platform/cloudflare/values.yaml` |
| prometheus | 200 MiB | - | `kube-prometheus-stack/release.yaml` |
| grafana, loki, minio, promtail, kube-state-metrics, node-exporter, prometheus-operator | - | - | chart defaults |
| envoy gateway and proxy, openebs | - | - | chart defaults |

**Declared requests:** about 4.9 GiB (AnkiLabs 2.4, quizlabs 1.8, platform 0.7). **Declared AnkiLabs limits:** about
4.7 GiB, almost all of it postgres.

**Gap:** the platform components marked "-" declare no requests or limits, so their share of the remaining ~11 GiB is
unbudgeted. Set them from measured usage (`kubectl top pods -A`) before the frontend and the later AI services are added.

Postgres sizing: `shared_buffers` 1 GiB and `maintenance_work_mem` 512 MiB sit inside the 4 GiB limit together with
`/dev/shm` (512 MiB). Publishing a dictionary or importing a corpus is the heavy moment (index builds, sorting 20M rows);
run it while nothing else is being changed.
