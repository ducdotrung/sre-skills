# PostgreSQL DB Operations

## RDS Endpoints Reference

| Env       | Host                                                                    | Port |
| --------- | ----------------------------------------------------------------------- | ---- |
| prod      | `{your-cluster-prefix}-postgres-prod.***.ap-northeast-1.rds.amazonaws.com` | 5432 |
| staging   | `cheecast-postgres-stag.***.ap-northeast-1.rds.amazonaws.com`  | 5432 |
| uat       | `{your-cluster-prefix}-postgre-uat.***.ap-northeast-1.rds.amazonaws.com`   | 5432 |
| dev       | `{your-cluster-prefix}-postgre-dev.***.ap-northeast-1.rds.amazonaws.com`   | 5432 |
| dify-prod | `dify-prod.***.ap-northeast-1.rds.amazonaws.com`               | 5432 |
| dify-stag | `dify-stag.***.ap-northeast-1.rds.amazonaws.com`               | 5432 |
| dify-uat  | `dify-uat.***.ap-northeast-1.rds.amazonaws.com`                | 5432 |

## Connect

```bash
# Prod
psql --host={your-cluster-prefix}-postgres-prod.***.ap-northeast-1.rds.amazonaws.com \
  --port=5432 --username=postgres

# Staging
psql --host=cheecast-postgres-stag.***.ap-northeast-1.rds.amazonaws.com \
  --port=5432 --username=postgres

# UAT
psql --host={your-cluster-prefix}-postgre-uat.***.ap-northeast-1.rds.amazonaws.com \
  --port=5432 --username=postgres

# Dev
psql --host={your-cluster-prefix}-postgre-dev.***.ap-northeast-1.rds.amazonaws.com \
  --port=5432 --username=postgres
```

---

## Create New Database in Existing Instance

> ⚠️ **Default rule:** Always CREATE DATABASE in the existing RDS instance via SQL.
> Only provision a new RDS instance if the ticket explicitly says "create new RDS instance" or "new DB instance".

### Standard pattern: role + user + database

```sql
-- Connect as postgres admin, then:
CREATE USER {app_name} WITH PASSWORD '{strong-password}';
CREATE ROLE {app_name}_role;
GRANT {app_name}_role TO {app_name};
CREATE DATABASE {app_name} OWNER {app_name}_role;
\c {app_name}
GRANT USAGE ON SCHEMA public TO {app_name}_role;
GRANT ALL ON ALL TABLES IN SCHEMA public TO {app_name}_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO {app_name}_role;
ALTER SCHEMA public OWNER TO {app_name}_role;
\q
```

### Simple pattern (app owns its own DB directly)

```sql
CREATE USER {app_name} WITH PASSWORD '{strong-password}';
CREATE DATABASE {app_name} OWNER {app_name};
\c {app_name}
GRANT USAGE ON SCHEMA public TO {app_name};
GRANT ALL ON ALL TABLES IN SCHEMA public TO {app_name};
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO {app_name};
```

### Add pgvector extension (for AI/embedding apps)

```sql
\c {db_name}
CREATE EXTENSION vector;
```

### Add read-only role for a database

```sql
CREATE ROLE {app_name}_read_role;
\c {db_name}
GRANT USAGE ON SCHEMA public TO {app_name}_read_role;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO {app_name}_read_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO {app_name}_read_role;
```

### Grant read-only access to existing user

```sql
GRANT {app_name}_read_role TO {username};
-- or direct pg built-in:
GRANT pg_read_all_data TO {username};
```

### Grant readwrite role to human dev user

```sql
CREATE USER {username} WITH PASSWORD '{strong-password}';
GRANT {app_name}_readwrite_role TO {username};
-- Role must already have schema grants via above pattern
```

### Revoke and reassign

```sql
REVOKE {role} FROM {username};
-- Change password
ALTER USER {username} WITH PASSWORD '{new-password}';
-- Rename user
ALTER USER {old_name} RENAME TO {new_name};
```

---

## Dump / Backup

### Full database dump (custom format, recommended for pg_restore)

```bash
pg_dump -h {rds_host} -p 5432 -U {username} \
  -Fc -b -v -f {db_name}.dump -d {db_name}
```

### Schema only

```bash
pg_dump -h {rds_host} -p 5432 -U postgres \
  -d {db_name} -s -f schema_only_{db_name}.sql
```

### Restore

```bash
# From custom format dump
pg_restore -v -h {rds_host} -U {username} \
  -d {db_name} -j 2 {db_name}.dump

# From plain SQL file
psql --host={rds_host} --port=5432 --username={username} < {file}.sql
```

### Sync schema prod → staging

```bash
# 1. Dump schema from prod
pg_dump -h {your-cluster-prefix}-postgres-prod.***.ap-northeast-1.rds.amazonaws.com \
  -p 5432 -U postgres -d {db_name} -s -f schema_only_{db_name}.sql

# 2. Apply to staging
psql -h cheecast-postgres-stag.***.ap-northeast-1.rds.amazonaws.com \
  -U {app_name} -d {db_name} -f schema_only_{db_name}.sql
```

---

## Admin Queries

### Connection count

```sql
SHOW max_connections;
SELECT count(*) AS session_count FROM pg_stat_activity;
SELECT datname AS database_name, COUNT(*) AS total_connections
FROM pg_stat_activity GROUP BY datname ORDER BY total_connections DESC;
```

### Kill idle connections on a database

```sql
SELECT pg_terminate_backend(pid)
FROM pg_stat_activity
WHERE datname = '{db_name}' AND state = 'idle' AND pid != pg_backend_pid();
```

### List databases and owners

```sql
SELECT d.datname AS "Name",
  pg_catalog.pg_get_userbyid(d.datdba) AS "Owner"
FROM pg_catalog.pg_database d ORDER BY 1;
```

### List roles and members

```sql
\du
SELECT r.rolname AS member
FROM pg_auth_members m
JOIN pg_roles r ON m.member = r.oid
WHERE m.roleid = (SELECT oid FROM pg_roles WHERE rolname = '{role_name}');
```

### Table sizes

```sql
SELECT table_name,
  pg_size_pretty(pg_total_relation_size(quote_ident(table_name))),
  pg_total_relation_size(quote_ident(table_name))
FROM information_schema.tables
WHERE table_schema = 'public'
ORDER BY 3 DESC;
```

### Check which databases a user has access to

```sql
SELECT d.datname AS database_name,
  pg_catalog.array_to_string(d.datacl, E'\n') AS access_privileges
FROM pg_catalog.pg_database d
WHERE EXISTS (
  SELECT 1 FROM pg_catalog.pg_authid r
  WHERE r.rolname = '{username}' AND r.oid = ANY (d.datacl)
) OR d.datdba = (SELECT oid FROM pg_catalog.pg_authid WHERE rolname = '{username}')
ORDER BY database_name;
```
