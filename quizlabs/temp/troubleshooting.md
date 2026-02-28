# Homelab Deployment Troubleshooting Notes

**Cluster info**: kubeadm single-node cluster (Ubuntu 24.04, Calico eBPF, containerd).

---

## 1. CoreDNS forwarding to unreachable stub resolver

**Symptom:** All pods failed to resolve external DNS names.

**Root cause:** CoreDNS was configured with `forward . /etc/resolv.conf`,
which resolved to `127.0.0.53` (the systemd-resolved stub listener).
That address is only reachable from the host network namespace, not from
inside container/pod network namespaces.

**Fix:** Patched the CoreDNS ConfigMap to forward to public resolvers:
```
forward . 1.1.1.1 8.8.8.8
```

---

## 2. iptables FORWARD chain dropping all pod traffic

**Symptom:** Even after fixing DNS, pods had zero external connectivity.
Cloudflare tunnel pods couldn't reach the Cloudflare edge, and all
outbound connections from pods timed out.

**Root cause:** The iptables FORWARD chain had a default policy of DROP.
This was set by Docker (which was installed on the host before Kubernetes).
Docker adds its own FORWARD rules for its bridge network, but those rules
don't cover Kubernetes pod traffic.

Calico was running in eBPF dataplane mode (`linuxDataplane: BPF`), with
kube-proxy disabled. In eBPF mode, Calico handles packet forwarding
entirely in eBPF programs attached to network interfaces — it does NOT
create iptables rules for pod traffic. So even though Calico was healthy,
no iptables FORWARD rules existed for pod-to-external traffic, and the
DROP policy silently discarded every forwarded packet.

In contrast, Calico's standard iptables dataplane would have inserted
ACCEPT rules in the FORWARD chain for pod traffic, making this a non-issue.

**Diagnosis steps:**
```bash
# Confirmed pods couldn't reach anything external
kubectl exec -n cloudflare <pod> -- wget -O- --timeout=5 https://example.com
# → timeout

# Checked iptables
sudo iptables -L FORWARD -v -n
# → policy DROP, only Docker bridge rules present

# Tested with ACCEPT
sudo iptables -P FORWARD ACCEPT
# → pods immediately regained connectivity
```

**Fix:** Set FORWARD policy to ACCEPT and created a systemd oneshot
service to persist it across reboots:
```
/etc/systemd/system/calico-forward-fix.service
/etc/iptables-calico-fix.sh
```

**Why this matters for Calico eBPF:** If you run Calico in eBPF mode on a
host that previously had Docker installed (or anything else that sets
FORWARD to DROP), you must ensure the FORWARD chain allows traffic.
Calico eBPF bypasses iptables entirely, so it won't fix the policy for you.

---

## 3. Cloudflare tunnel invalid secret

**Symptom:** Tunnel connected to Cloudflare edge but got
"Unauthorized: Invalid tunnel secret".

**Root cause:** The SOPS-encrypted `credentials.json` secret had the full
base64 connector token in the `secret` field, but it should only contain
the TunnelSecret (`"s"` field from the decoded token JSON), since the
template splits the token into separate `AccountTag`, `TunnelID`, and
`TunnelSecret` fields.

**Fix:** Decoded the connector token, extracted just the `"s"` value, and
re-encrypted the SOPS secret.

---

## 4. MongoDB authentication failure due to special characters in URI

**Symptom:** Backend pods got "Authentication failed" connecting to MongoDB,
even though the password was correct (verified with manual mongosh login).

**Root cause:** The generated password contained `+` and `=` characters.
The backend constructs a MongoDB connection URI like:
`mongodb://root:<password>@mongodb...` — the `+` and `=` are URI-special
characters that corrupt the connection string when not percent-encoded.

**Fix:** Regenerated the password as hex-only (alphanumeric, no special
characters) and updated it in MongoDB, the mongodb secret, and the
quiz-backend secret.

---

## 5. Envoy Gateway service name hash causing DNS lookup failures

**Symptom:** Cloudflare tunnel logs showed "no such host" for
`envoy-platform-quiz-gateway.envoy-gateway-system.svc.cluster.local`.

**Root cause:** Envoy Gateway auto-generates the data-plane proxy Service
with a hash suffix: `envoy-<namespace>-<gateway-name>-<hash>`, where
the hash is `sha256("<namespace>/<name>")[:8]`. For our Gateway
(`platform/quiz-gateway`), this produced
`envoy-platform-quiz-gateway-8dff7555`.

The Cloudflare tunnel config referenced the unhashed name.

**Fix:** Created an `EnvoyProxy` custom resource that explicitly sets the
Service name to `envoy-gateway-proxy` and type to `ClusterIP`. Linked it
to the `GatewayClass` via `spec.parametersRef`. Updated the Cloudflare
tunnel ingress to use the stable name.
