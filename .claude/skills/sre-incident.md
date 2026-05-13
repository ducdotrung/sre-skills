---
description: Interactive incident debug for live production issues. Runs actual kubectl/aws commands, analyses real output, and suggests fixes — rather than just generating a static guide. Use when an app is down, degraded, or behaving unexpectedly right now.
---

# SRE Incident Debug

Live, interactive debugging of a running incident. Unlike `/sre-triage`, this skill runs real commands and reasons about their output before suggesting the next step.

**Usage:** `/sre-incident [APP] [ENV] [SYMPTOM]`

- `APP` — service name (e.g. `api-backend`, `llm-agent`). Optional — you'll be asked if missing.
- `ENV` — environment: `prod`, `staging`, `uat`, `dev`. Optional.
- `SYMPTOM` — short description of what's wrong (e.g. `CrashLoopBackOff`, `502 errors`, `OOMKilled`). Optional.

---

## Step 1 — Open

**Read `sre-config.md`** (or `sre-config.example`) to load cluster names, namespaces, and observability URLs.

If any of APP / ENV / SYMPTOM are missing, ask for them now in a single prompt:

```
🚨 Incident Debug

App name:   {provided or "?"}
Env:        {provided or "?"}
Symptom:    {provided or "?"}

Please fill in any missing fields before we start.
```

Map ENV → cluster and namespace:

| ENV | Cluster | Namespace |
|---|---|---|
| `prod` | `{PROD_CLUSTER}` from sre-config.md | default or app-specific |
| `staging` | `stag` | `{STAGING_CLUSTER}` | default or app-specific |
| `uat` | `{UAT_CLUSTER}` | `{UAT_NAMESPACE}` |
| `dev` | `{UAT_CLUSTER}` | `{DEV_NAMESPACE}` |

Set kubeconfig context if not already set:
```bash
kubectl config use-context {cluster-name}
# or: aws eks update-kubeconfig --name {cluster-name} --region {AWS_PRIMARY_REGION}
```

---

## Step 2 — Fast triage (run all, interpret together)

Run this initial set of commands in quick succession to get a snapshot. Show output and your interpretation after each group.

### 2a — Pod status

```bash
kubectl get pods -n {namespace} -l app={app-name} --sort-by=.status.startTime
```

Interpret:
- All Running/Ready → pods are healthy; issue is likely upstream or network
- CrashLoopBackOff → app is crashing on startup; proceed to 2b
- Pending → scheduling issue (resources, node selectors, PVCs); proceed to 2d
- OOMKilled (check RESTARTS column + describe) → memory limit; proceed to 2c
- ImagePullBackOff → bad image tag or ECR auth; proceed to 2e

### 2b — Crash / logs

```bash
kubectl logs -n {namespace} -l app={app-name} --tail=100 --prefix
kubectl logs -n {namespace} -l app={app-name} --previous --tail=100 --prefix 2>/dev/null || echo "(no previous logs)"
```

Look for: startup exception, missing env var, connection refused, OOM signal, segfault.

### 2c — Resource pressure

```bash
kubectl top pod -n {namespace} -l app={app-name}
kubectl describe pod -n {namespace} $(kubectl get pod -n {namespace} -l app={app-name} -o name | head -1) | grep -A10 "Limits\|Requests\|OOM\|Last State"
```

### 2d — ArgoCD / deployment state

```bash
argocd app get {app-name}-{env}
argocd app history {app-name}-{env} | head -10
```

Look for: OutOfSync (recent commit changed something), Degraded health, wrong image tag.

### 2e — Recent events

```bash
kubectl get events -n {namespace} --sort-by=.lastTimestamp | tail -20
```

---

## Step 3 — Symptom-specific deep dive

Based on what Step 2 revealed, run the matching playbook below. Run only the one that matches — do not run all.

---

### 🔴 CrashLoopBackOff

```bash
# Full describe of one crashing pod
kubectl describe pod -n {namespace} {pod-name}

# Check if ExternalSecret is synced (common cause: missing/wrong secret)
kubectl get externalsecret -n {namespace} {app-name}
kubectl describe externalsecret -n {namespace} {app-name}

# Check if the secret K8s object exists and has all keys
kubectl get secret -n {namespace} {app-name}-secrets -o jsonpath='{.data}' | python3 -c "import sys,json,base64; [print(k) for k in json.load(sys.stdin)]"
```

Common root causes and fixes:

| Root cause | Signal | Fix |
|---|---|---|
| Missing secret key | `KeyError`, `undefined variable` in logs | Force ESO resync: `kubectl annotate externalsecret {app-name} force-sync=$(date +%s) --overwrite -n {namespace}` |
| Wrong image tag | ImagePullBackOff or wrong binary | Check ArgoCD spec vs ECR: `aws ecr describe-images --repository-name {app-name} --image-ids imageTag={tag}` |
| Bad config / env var | Config parse error in logs | Check Helm values vs Secrets Manager |
| Dependency not ready | `connection refused` to DB/Redis/RabbitMQ | Check dependency pod status |

---

### 🟠 OOMKilled

```bash
kubectl top pod -n {namespace} -l app={app-name}
kubectl top node
kubectl describe node $(kubectl get pod -n {namespace} -l app={app-name} -o jsonpath='{.items[0].spec.nodeName}') | grep -A5 "Allocated resources"
```

Fix: increase memory limit in Helm values and sync:

```bash
# Edit helm/apps/{app-name}/values-{env}.yaml:
# resources:
#   limits:
#     memory: {current + 50%}

# Then commit and sync
argocd app sync {app-name}-{env}
argocd app wait {app-name}-{env} --health --timeout 120
```

---

### 🟡 HTTP 502 / 504 (upstream errors)

```bash
# Check if pods have healthy endpoints
kubectl get endpoints -n {namespace} {app-name}

# Ingress controller logs — filter to this hostname
kubectl logs -n ingress-nginx -l app.kubernetes.io/name=ingress-nginx --tail=200 | grep {app-name}

# Check ingress config
kubectl get ingress -n {namespace} {app-name} -o yaml
```

Common fixes:
- No endpoints → pod not Running; fix the pod first
- Timeout in ingress logs → increase `nginx.ingress.kubernetes.io/proxy-read-timeout` annotation
- 502 from ingress but pod is healthy → check `containerPort` in Helm chart matches `targetPort` in Service

---

### 🔵 Pending pods (scheduling failure)

```bash
kubectl describe pod -n {namespace} {pod-name} | grep -A20 "Events:"
kubectl get nodes -o custom-columns='NAME:.metadata.name,STATUS:.status.conditions[-1].type,CPU:.status.allocatable.cpu,MEM:.status.allocatable.memory'
```

Common fixes:
- Insufficient resources → scale node group or reduce resource requests
- Node selector mismatch → check `nodeSelector` in Helm values vs node labels
- PVC not bound → check PersistentVolumeClaim status

---

### ⚪ App running but degraded / wrong behaviour

```bash
# Check recent ArgoCD deploys
argocd app history {app-name}-{env} | head -5

# Check if config matches expectation
kubectl get configmap -n {namespace} -l app={app-name} -o yaml 2>/dev/null || echo "(no configmap)"
kubectl exec -n {namespace} deploy/{app-name} -- env | sort 2>/dev/null | head -30
```

Also check observability — read URLs from `sre-config.md`:
- Logs: `{LOGS_URL}` → filter `kubernetes.deployment.name: {app-name}`
- Metrics: `{GRAFANA_URL}` → check error rate, latency, saturation
- Traces: `{TRACING_URL}` → find slow or erroring spans

---

## Step 4 — Confirm and fix

After identifying the root cause, present a summary before taking action:

```
🔍 Diagnosis: {1-sentence root cause}

Proposed fix:
  {numbered steps with commands}

Estimated impact: {pod restart / no downtime / brief downtime}
Safe to run now? [y] proceed  [n] stop here
```

Only proceed on `y`. Run fixes using the appropriate tag logic:
- Read-only commands → run immediately
- Restart / resync → ask first (`⚠️ This will restart pods`)
- Helm values change + sync → `⚠️ This will trigger a rolling deploy`

---

## Step 5 — Verify and close

After the fix is applied:

```bash
kubectl rollout status deployment/{app-name} -n {namespace} --timeout=120s
kubectl get pods -n {namespace} -l app={app-name}
```

Check that:
- [ ] All pods are Running/Ready
- [ ] RESTARTS counter is stable (not incrementing)
- [ ] No new error events in `kubectl get events`
- [ ] Smoke test passes (hit the service endpoint or check logs for successful startup)

---

## Step 6 — Save incident report

Write a brief incident report to `output/alerts/{YYYY-MM-DD}-incident-{app-name}-{env}.md`:

```markdown
# Incident: {app-name} on {env} — {YYYY-MM-DD HH:MM UTC}

**Symptom:** {original symptom}
**Root cause:** {diagnosed cause}
**Fix applied:** {what was done}
**Time to resolution:** {approx}
**Verification:** {what confirmed it was fixed}

## Commands run

{list of key commands and their relevant output}

## Follow-up actions

- [ ] {any PR needed for permanent fix, e.g. update Helm values}
- [ ] {any Jira ticket to track}
- [ ] {any post-mortem needed?}
```

<!-- ☁️ To post a Jira comment instead: call addCommentToJiraIssue on the related ticket with the report content. -->

---

## Notes

- **Always read sre-config.md first** — cluster names, namespaces, and observability URLs all come from there.
- **Do not guess resource names** — resolve app name → namespace → cluster from config before running any command.
- **Check ESO first for secret issues** — most CrashLoopBackOff on new deploys are missing or mis-synced secrets.
- **Prefer rolling restarts over delete** — `kubectl rollout restart` is safer than deleting pods manually.
- **Prod caution** — any command that affects pod scheduling on prod gets an explicit confirmation prompt before running.
