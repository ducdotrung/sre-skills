# EKS / kubectl Operations

## kubeconfig Setup

```bash
# Prod
aws eks update-kubeconfig --region ap-northeast-1 \
  --name {prod-cluster-name} \
  --kubeconfig ~/.kube/config-prod

# Staging
aws eks update-kubeconfig --region ap-northeast-1 \
  --name {staging-cluster-name} \
  --kubeconfig ~/.kube/config-staging

# UAT / Dev (shared cluster)
aws eks update-kubeconfig --region ap-northeast-1 \
  --name {uat-cluster-name} \
  --kubeconfig ~/.kube/config
```

---

## Pod Operations

### Exec into a pod

```bash
kubectl -n {namespace} exec -it {pod-name} -c {container-name} -- bash
```

### View logs

```bash
kubectl logs -n {namespace} {pod-name} --tail=100
kubectl logs -n {namespace} {pod-name} --previous --tail=100
kubectl logs -n {namespace} -l app={app-name} --tail=100 --follow
```

### Restart a deployment

```bash
kubectl rollout restart deployment/{app-name} -n {namespace}
kubectl rollout status deployment/{app-name} -n {namespace}
```

### Force delete a stuck pod

```bash
kubectl delete pod {pod-name} --grace-period=0 --force --namespace {namespace}
```

### Scale deployment (temporary, dev/uat only)

```bash
kubectl scale deployment {app-name} --replicas={n} -n {namespace}
```

### Get pods wide (with node placement)

```bash
kubectl get pods -n {namespace} -o wide
kubectl get pods -n {namespace} -l app={app-name} -o wide
kubectl get pods -n {namespace} -o wide --field-selector spec.nodeName={node-name}
```

---

## ExternalSecret / ESO Resync

```bash
# Force ESO to re-read from Secrets Manager
kubectl annotate externalsecret {app-name} \
  force-sync=$(date +%s) --overwrite -n {namespace}

# Then restart the app
kubectl rollout restart deployment/{app-name} -n {namespace}
```

---

## ArgoCD

### Login

```bash
kubectl -n argocd-prod get secret argocd-initial-admin-secret \
  -o jsonpath="{.data.password}" | base64 -d; echo

argocd login argocd.{yourcompany}.ai
```

### Sync and wait

```bash
argocd app sync {app-name}-{env}
argocd app wait {app-name}-{env} --health --timeout 180
argocd app get {app-name}-{env}
```

### Rollback

```bash
argocd app rollback {app-name}-{env}
```

---

## Node Operations

### Cordon (stop scheduling new pods)

```bash
kubectl cordon {node-name}
```

### Drain (evict all pods, then safe to terminate)

```bash
kubectl drain {node-name} \
  --ignore-daemonsets \
  --delete-emptydir-data \
  --grace-period=30 \
  --timeout=300s
```

### Remove a single node from its ASG (prod node scale-down)

```bash
NODE="ip-10-30-XX-XX.ap-northeast-1.compute.internal"

# Get EC2 instance ID
INSTANCE=$(kubectl get node $NODE -o jsonpath='{.spec.providerID}' | cut -d'/' -f5)

# Get ASG name
ASG=$(aws autoscaling describe-auto-scaling-instances \
  --instance-ids $INSTANCE \
  --query 'AutoScalingInstances[0].AutoScalingGroupName' \
  --output text)

# Put into standby (decrements desired count)
aws autoscaling enter-standby \
  --instance-ids $INSTANCE \
  --auto-scaling-group-name $ASG \
  --should-decrement-desired-capacity

# Drain node
kubectl drain $NODE --ignore-daemonsets --delete-emptydir-data --grace-period=30 --timeout=300s

# Terminate instance
aws ec2 terminate-instances --instance-ids $INSTANCE

# Remove from cluster
kubectl delete node $NODE
```

---

## Ingress / NLB Debug

### Check NLB listener certificates

```bash
LB_ARN=$(aws elbv2 describe-load-balancers \
  --names {lb-name} \
  --region ap-northeast-1 \
  --query 'LoadBalancers[0].LoadBalancerArn' \
  --output text)

LISTENER_ARN=$(aws elbv2 describe-listeners \
  --load-balancer-arn $LB_ARN \
  --region ap-northeast-1 \
  --query 'Listeners[?Port==`443`].ListenerArn' \
  --output text)

# List current certs
aws elbv2 describe-listener-certificates \
  --listener-arn $LISTENER_ARN \
  --region ap-northeast-1 \
  --query 'Certificates[*].CertificateArn'

# Add cert
aws elbv2 add-listener-certificates \
  --listener-arn $LISTENER_ARN \
  --certificates CertificateArn={cert-arn} \
  --region ap-northeast-1
```

### Remove finalizers from stuck resources

```bash
kubectl patch service {service-name} -n {namespace} \
  -p '{"metadata":{"finalizers":[]}}' --type=merge

kubectl patch gateway {gateway-name} -n {namespace} \
  -p '{"metadata":{"finalizers":[]}}' --type=merge
```

---

## Helm / Helmfile

### Stuck release — force upgrade

```bash
helm upgrade --install {release} {chart} \
  -n {namespace} \
  -f values.yml \
  --version {version} \
  --history-max 20 \
  --timeout 15m \
  --wait

# Delete orphaned helm secrets before retry
kubectl delete secret -n {namespace} -l owner=helm,name={release}
```

### Helmfile apply

```bash
helmfile diff .
helmfile apply .
```
