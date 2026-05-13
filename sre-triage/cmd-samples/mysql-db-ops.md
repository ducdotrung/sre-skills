# MySQL DB Operations

## RDS Endpoints Reference

| Env | Host | Port |
|---|---|---|
| prod (write) | `{your-cluster-prefix}-prod.***.ap-northeast-1.rds.amazonaws.com` | 3306 |
| prod (read) | `{your-cluster-prefix}-prod-read-only.***.ap-northeast-1.rds.amazonaws.com` | 3306 |
| staging (write) | `{your-cluster-prefix}-mysql-stag.***.ap-northeast-1.rds.amazonaws.com` | 3306 |
| staging (read) | `{your-cluster-prefix}-stag-read-only.***.ap-northeast-1.rds.amazonaws.com` | 3306 |
| uat | `{your-cluster-prefix}-uat.***.ap-northeast-1.rds.amazonaws.com` | 3306 |
| dev | `{your-cluster-prefix}-dev.***.ap-northeast-1.rds.amazonaws.com` | 3306 |
| migration | `migration-db.***.ap-northeast-1.rds.amazonaws.com` | 3306 |

## Connect

```bash
# Prod
mysql -uadmin -h {your-cluster-prefix}-prod.***.ap-northeast-1.rds.amazonaws.com -P 3306 -p

# Staging
mysql -uadmin -h {your-cluster-prefix}-mysql-stag.***.ap-northeast-1.rds.amazonaws.com -P 3306 -p

# UAT
mysql -uadmin -h {your-cluster-prefix}-uat.***.ap-northeast-1.rds.amazonaws.com -P 3306 -p

# Dev
mysql -uadmin -h {your-cluster-prefix}-dev.***.ap-northeast-1.rds.amazonaws.com -P 3306 -p
```

---

## Create New Database in Existing Instance

> ⚠️ **Default rule:** Always CREATE DATABASE in the existing RDS instance via SQL.
> Only provision a new RDS instance if the ticket explicitly says "create new RDS instance" or "new DB instance".

### Service account + full access (standard new app DB)

```sql
-- Run as admin on the target RDS instance
CREATE DATABASE {db_name};
CREATE USER '{app_name}'@'10.10.%.%' IDENTIFIED BY '{strong-password}';
GRANT ALL PRIVILEGES ON `{db_name}`.* TO `{app_name}`@`10.10.%.%`;
FLUSH PRIVILEGES;
SHOW GRANTS FOR `{app_name}`@`10.10.%.%`;
```

### Staging/Prod service account pattern (with awsdms_control)

```sql
CREATE USER '{app_name}'@'10.%.%.%' IDENTIFIED BY '{strong-password}';
GRANT USAGE ON *.* TO `{app_name}`@`10.%.%.%`;
GRANT ALL PRIVILEGES ON `{db_name}`.* TO `{app_name}`@`10.%.%.%`;
GRANT ALL PRIVILEGES ON `awsdms_control`.* TO '{app_name}'@'10.%.%.%';
FLUSH PRIVILEGES;
```

### Grant read-only access to an existing DB (DMS/Metabase pattern)

```sql
GRANT SELECT ON `{db_name}`.* TO `dms`@`10.%.%.%`;
GRANT SELECT ON `{db_name}`.* TO `metabase`@`10.%.%.%`;
```

### Human dev user — full access

```sql
CREATE USER '{username}'@'10.10.%.%' IDENTIFIED BY '{strong-password}';
GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, DROP, REFERENCES, INDEX, ALTER, LOCK TABLES ON `{db_name}`.* TO `{username}`@`10.10.%.%`;
SHOW GRANTS FOR `{username}`@`10.10.%.%`;
```

### Human dev user — read-only

```sql
CREATE USER '{username}'@'10.10.%.%' IDENTIFIED BY '{strong-password}';
GRANT SELECT ON `{db_name}`.* TO `{username}`@`10.10.%.%`;
```

### Revoke and update grants

```sql
REVOKE ALL PRIVILEGES ON `{db_name}`.* FROM `{username}`@`10.10.%.%`;
-- then re-grant as needed
GRANT SELECT ON `{db_name}`.* TO `{username}`@`10.10.%.%`;
FLUSH PRIVILEGES;
```

---

## Dump / Backup

### Full database dump (prod)

```bash
mysqldump -uadmin -p \
  -h {your-cluster-prefix}-prod-read-only.***.ap-northeast-1.rds.amazonaws.com \
  -P 3306 \
  --routines --triggers --events --single-transaction --set-gtid-purged=OFF \
  {db_name} > {ticket_id}-backup.sql
```

### Schema only

```bash
mysqldump -uadmin -p \
  -h {your-cluster-prefix}-prod-read-only.***.ap-northeast-1.rds.amazonaws.com \
  -P 3306 \
  --no-data --routines --triggers --events --set-gtid-purged=OFF \
  {db_name} > schema_only_{db_name}.sql
```

### Partial dump (specific table with WHERE)

```bash
mysqldump -uadmin -p \
  -h {your-cluster-prefix}-prod-read-only.***.ap-northeast-1.rds.amazonaws.com \
  -P 3306 \
  --no-create-info --complete-insert --skip-extended-insert \
  --where="id > {min_id}" \
  {db_name} {table_name} > {ticket_id}-{table_name}.sql
```

### Restore

```bash
# From sql file
mysql -u{service_user} -h {rds_host} -P 3306 --database={db_name} -p < {file}.sql

# Apply schema only to staging
mysql -u{service_user} -p -h {your-cluster-prefix}-mysql-stag.***.ap-northeast-1.rds.amazonaws.com {db_name} < schema_only_{db_name}.sql
```

### Export query result to CSV

```bash
mysql -uadmin -h {rds_host} -P 3306 -p \
  -e "SELECT * FROM {table} WHERE {condition}" {db_name} > {ticket_id}.csv
```

---

## Admin Queries

### Show max connections

```sql
SHOW VARIABLES LIKE "max_connections";
SET GLOBAL max_connections = 151;
```

### Connection breakdown by user

```sql
SELECT user, host, count(*) AS connection_count
FROM information_schema.processlist
GROUP BY user;
```

### Show grants for a user

```sql
SELECT user, host FROM mysql.user;
SHOW GRANTS FOR `{username}`@`10.10.%.%`;
```

### Check auto_increment value

```sql
SELECT TABLE_NAME, AUTO_INCREMENT
FROM information_schema.TABLES
WHERE TABLE_SCHEMA = '{db_name}';
```

### Slow queries (top 10)

```sql
SELECT DIGEST_TEXT
FROM performance_schema.events_statements_summary_by_digest
ORDER BY SUM_TIMER_WAIT DESC
LIMIT 10;
```
