# Utils

## K8s

```bash
# get all pods with count prefix
kubectl get pods -A --no-headers | awk '{print $1}' | sort | uniq -c
```

## Flux

```bash
# Show all Flux objects that are not ready
flux get all -A --status-selector ready=false

# Looking for controller errors
flux logs --all-namespaces --level=error

# Start reconciliation 
flux reconcile kustomization flux-system --with-source

# Access Capacitor UI with port-forwarding
kubectl -n flux-system port-forward svc/capacitor 9000:9000
```