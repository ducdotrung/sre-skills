# Redis Operations

## Server Reference

| Env | Host | Data path | Security Group |
|---|---|---|---|
| dev / uat | `{REDIS_SERVER_DEV_UAT}` | `/data/dev/` or `/data/uat/` | `redis-server-uat` (vpc: uat-ai) |
| staging | `{REDIS_SERVER_STAGING}` | `/data/stag/` | `redis-server-stag` (vpc: staging-ai) |
| prod | `{REDIS_SERVER_PROD}` | `/data/prod/` | `redis-server-prod` (vpc: production-ai) |

## Allowed Port Ranges (from sg.tf)

> If the new port fits inside the current range, **no sg.tf update needed**.
> Only update when the new port exceeds the `to_port` of the relevant security group.

| Env | Redis ports (SG) | redis-exporter ports (SG) |
|---|---|---|
| dev / uat | `6400 – 6550` | `16400 – 16550` |
| staging | `6400 – 6420` | `16400 – 16420` |
| prod | `6400 – 6430` | `16400 – 16430` |

> redis-exporter port formula: `EXPORTER_PORT = 1{EXPOSED_PORT}` — e.g., port `6403` → exporter `16403`.

---

## Folder / File Layout

Each Redis instance lives in its own subfolder:

```
/data/{env}/{env}-{service-name}/
├── redis.yml   # copy of sre-triage/configs/compose/redis.yml
├── .env                        # REDIS_PASSWORD + EXPOSED_PORT
├── data/                       # Redis persistence volume
└── config/                     # redis.conf (optional overrides)
```

Folder name matches the service that will use this Redis, e.g. `dev-llm-agent`, `prod-{your-cluster-prefix}-backend`.

---

## Add New Redis Instance — Step by Step

### 1. Find the next available port on the target server

```bash
# SSH into the Redis server, then:
grep -r "EXPOSED_PORT" /data/{env}/*/.env | sort -t= -k2 -n | tail -5
```

Take the current max port and add 1.

### 2. Create the instance folder

```bash
cd /data/{env}
mkdir {env}-{service-name}
cd {env}-{service-name}
mkdir data config
```

### 3. Create `.env`

```bash
cat > .env <<EOF
REDIS_PASSWORD={strong-password}
EXPOSED_PORT={port}
EOF
```

### 4. Copy the compose file

```bash
cp /path/to/sre-skill/sre-triage/configs/compose/redis.yml .
```

### 5. Start the instance

```bash
docker compose -f redis.yml up -d
docker compose -f redis.yml ps
```

### 6. Verify

```bash
# Test connection (from any internal host)
redis-cli -h {server-ip} -p {port} -a {password} ping
# Expected: PONG
```

### 7. Update sg.tf (only if new port exceeds current SG range)

Check the table above. If the port is within the allowed range, skip this step.

If the port exceeds `to_port`, update `sg.tf` in `github.com/{your-github-org}/terraform`:

```hcl
# In resource "aws_security_group" "redis-server-{env}", update:
{
  from_port = 6400
  to_port   = {new_max_port}          # bump to cover new port
  ...
},
{
  from_port = 16400
  to_port   = 1{new_max_port}         # mirror for redis-exporter
  ...
}
```

Then apply:
```bash
terraform fmt && terraform validate
terraform plan  -target=aws_security_group.redis-server-{env}
terraform apply -target=aws_security_group.redis-server-{env}
```

### 8. Wire up to the app

| Config | Where it goes |
|---|---|
| `REDIS_HOST` = `{server-ip}` | Helm values (`values-{env}.yaml`) or non-secret env in manifest |
| `REDIS_PORT` = `{port}` | Helm values (`values-{env}.yaml`) or non-secret env in manifest |
| `REDIS_PASSWORD` = `{password}` | AWS Secrets Manager: `eks-{cluster-prefix}-{app-name}` |

After updating Secrets Manager, force ESO resync and restart:
```bash
kubectl annotate externalsecret {app-name} force-sync=$(date +%s) --overwrite -n {namespace}
kubectl rollout restart deployment/{app-name} -n {namespace}
```

---

## Docker Compose Template Reference

See `sre-triage/configs/compose/redis.yml`. Key points:
- Redis image: `redis:8.0.3`
- Config mount: `./config:/usr/local/etc/redis` (place custom `redis.conf` here if needed)
- Data persistence: `./data:/data`
- redis-exporter runs alongside, port `1{EXPOSED_PORT}:9121`

---

## Connect / Debug

```bash
# Interactive CLI
redis-cli -h {server-ip} -p {port} -a {password}

# One-shot ping
redis-cli -h {server-ip} -p {port} -a {password} ping

# Scan keys by pattern
redis-cli -h {server-ip} -p {port} -a {password} \
  --scan --pattern "{key-prefix}:*"

# Delete keys matching pattern
redis-cli -h {server-ip} -p {port} -a {password} \
  --scan --pattern "{key-prefix}:*" | \
  xargs redis-cli -h {server-ip} -p {port} -a {password} del

# Check memory / info
redis-cli -h {server-ip} -p {port} -a {password} info memory
redis-cli -h {server-ip} -p {port} -a {password} info server
```

---

## Manage Running Instance

```bash
# Status
docker compose -f redis.yml ps

# Logs
docker compose -f redis.yml logs -f redis

# Restart
docker compose -f redis.yml restart redis

# Stop
docker compose -f redis.yml down
```
