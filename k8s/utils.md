# Utils

## K8s

```bash
# get all pods with count prefix
kubectl get pods -A --no-headers | awk '{print $1}' | sort | uniq -c
```

## Flux