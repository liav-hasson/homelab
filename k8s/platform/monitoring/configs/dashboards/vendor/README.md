# Vendored dashboards

Upstream dashboards copied byte for byte. They are provisioned into the
Platform folder with our own dashboards (`../../kustomization.yaml`) but keep
their upstream layout, so the homelab dashboard conventions do not apply to
them (`tests/test_vendored_dashboards.py` checks what still does).

- `flux-cluster.json`: Flux Cluster Stats (uid `flux-cluster`), upstream
  `monitoring/configs/dashboards/cluster.json`
- `flux-control-plane.json`: Flux Control Plane (uid `flux-control-plane`),
  upstream `monitoring/configs/dashboards/control-plane.json`
- Repository: <https://github.com/fluxcd/flux2-monitoring-example>
- Commit: `7ab65dc8b90f7a6751d88f18bbb4e1bee33bf334` (the dashboards last
  changed in `14129216b7e43db91c49bf0cd6b588360e4aa953`)
- Local edits: none. The files are renamed with a `flux-` prefix only, because
  the Platform ConfigMap keys them by file name.

The dashboards select the Prometheus data source through their
`DS_PROMETHEUS` variable, and some queries also name the data source UID
`prometheus`, which is the kube-prometheus-stack default. They read
kube-state-metrics `gotk_resource_info`
(`controllers/kube-prometheus-stack/kube-state-metrics-config.yaml`) and the
Flux controller metrics scraped by `../../podmonitor.yaml`.

## Update

Pick a new upstream commit, replace both files and update the commit above:

```sh
sha=<commit>
base=https://raw.githubusercontent.com/fluxcd/flux2-monitoring-example/$sha/monitoring/configs/dashboards
curl -fsSL "$base/cluster.json" -o flux-cluster.json
curl -fsSL "$base/control-plane.json" -o flux-control-plane.json
```

Then run the monitoring tests and compare the queries with the
kube-state-metrics configuration and the Flux PodMonitor.
