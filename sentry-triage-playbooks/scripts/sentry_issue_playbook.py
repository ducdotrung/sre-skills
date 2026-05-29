#!/usr/bin/env python3
"""Fetch recent Sentry issues, classify them, and write a Markdown playbook."""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


CLASS_KEYWORDS = {
    "client-disconnect": [
        "broken pipe",
        "clientabortexception",
        "connection prematurely closed",
        "prematurecloseexception",
    ],
    "availability": [
        "5xx",
        "500",
        "502",
        "503",
        "504",
        "crash",
        "gateway",
        "service unavailable",
        "unavailable",
        "worker failed",
    ],
    "dependency": [
        "503",
        "feignexception$internalservererror",
        "feignexception$serviceunavailable",
        "httpconnectionpool",
        "connection refused",
        "database",
        "dns",
        "ecconn",
        "external",
        "kafka",
        "network",
        "postgres",
        "queue",
        "redis",
        "s3",
        "storage",
        "third party",
        "upstream",
    ],
    "auth-permission": [
        "401",
        "403",
        "csrf",
        "forbidden",
        "permission",
        "signature",
        "token",
        "unauthorized",
    ],
    "data-integrity": [
        "duplicatekeyexception",
        "nullpointerexception",
        "sqlexception",
        "cannot be null",
        "constraint",
        "corrupt",
        "deserial",
        "invariant",
        "migration",
        "missing field",
        "parse",
        "schema",
        "serializ",
    ],
    "input-validation": [
        "404",
        "notfound",
        "400",
        "bad request",
        "invalid",
        "malformed",
        "typeerror",
        "validation",
        "valueerror",
    ],
    "frontend-client": [
        "browser",
        "chunk",
        "client",
        "hydration",
        "javascript",
        "resizeobserver",
        "sourcemap",
        "source map",
        "webpack",
    ],
    "performance-timeout": [
        "deadline",
        "lock wait",
        "memory",
        "oom",
        "overload",
        "rate limit",
        "slow",
        "throttle",
        "timeout",
        "timed out",
    ],
}


def env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    return value if value not in (None, "") else default


def iso_now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def normalize_base_url(value: str) -> str:
    base = value.strip().rstrip("/")
    if not re.match(r"^https?://", base):
        base = "https://" + base
    return base


class SentryClient:
    def __init__(self, base_url: str, token: str):
        self.base_url = normalize_base_url(base_url)
        self.token = token
        self.auth_mode = "bearer"

    def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        return self._request("GET", path, params=params)

    def _request(
        self, method: str, path: str, params: dict[str, Any] | None = None
    ) -> Any:
        url = self.base_url + path
        if params:
            query = urllib.parse.urlencode(params, doseq=True)
            url = f"{url}?{query}"
        request = urllib.request.Request(url, method=method)
        request.add_header("Accept", "application/json")
        self._add_auth(request)
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                body = response.read().decode("utf-8")
                return json.loads(body) if body else None
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403) and self.auth_mode == "bearer":
                self.auth_mode = "basic"
                return self._request(method, path, params)
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Sentry API {exc.code} for {url}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Could not reach Sentry API at {url}: {exc}") from exc

    def _add_auth(self, request: urllib.request.Request) -> None:
        if self.auth_mode == "basic":
            raw = f"{self.token}:".encode("utf-8")
            request.add_header(
                "Authorization", "Basic " + base64.b64encode(raw).decode("ascii")
            )
        else:
            request.add_header("Authorization", f"Bearer {self.token}")


def discover_org(client: SentryClient) -> str:
    orgs = client.get("/api/0/organizations/")
    if not isinstance(orgs, list) or not orgs:
        raise RuntimeError("Set SENTRY_ORG; organization discovery returned no results.")
    slug = orgs[0].get("slug") or orgs[0].get("id")
    if not slug:
        raise RuntimeError("Set SENTRY_ORG; organization discovery had no slug.")
    return str(slug)


def parse_projects(value: str | None) -> list[str]:
    if not value:
        return ["-1"]
    return [item.strip() for item in value.split(",") if item.strip()]


def resolve_projects(client: SentryClient, org: str, specs: list[str]) -> list[str]:
    if not specs or specs == ["-1"]:
        return ["-1"]
    if all(spec == "-1" or spec.isdigit() for spec in specs):
        return specs

    projects = client.get(f"/api/0/organizations/{urllib.parse.quote(org)}/projects/")
    if not isinstance(projects, list):
        raise RuntimeError("Unexpected Sentry projects response; expected a JSON list.")
    by_slug_or_name: dict[str, str] = {}
    for project in projects:
        project_id = str(project.get("id") or "")
        for key in (project.get("slug"), project.get("name"), project_id):
            if key:
                by_slug_or_name[str(key).lower()] = project_id

    resolved: list[str] = []
    missing: list[str] = []
    for spec in specs:
        if spec == "-1" or spec.isdigit():
            resolved.append(spec)
            continue
        project_id = by_slug_or_name.get(spec.lower())
        if project_id:
            resolved.append(project_id)
        else:
            missing.append(spec)
    if missing:
        known = ", ".join(sorted(key for key in by_slug_or_name if not key.isdigit())[:25])
        raise RuntimeError(f"Unknown Sentry project(s): {', '.join(missing)}. Known: {known}")
    return resolved


def fetch_issues(
    client: SentryClient,
    org: str,
    stats_period: str,
    query: str,
    projects: list[str],
    environment: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    params: dict[str, Any] = {
        "query": query,
        "statsPeriod": stats_period,
        "sort": "freq",
        "limit": min(limit, 100),
        "project": projects,
        "expand": ["owners"],
    }
    if environment:
        params["environment"] = [environment]
    issues = client.get(f"/api/0/organizations/{urllib.parse.quote(org)}/issues/", params)
    if not isinstance(issues, list):
        raise RuntimeError("Unexpected Sentry issues response; expected a JSON list.")
    return issues[:limit]


def issue_text(issue: dict[str, Any]) -> str:
    project = issue.get("project") or {}
    metadata = issue.get("metadata") or {}
    fields = [
        issue.get("title"),
        issue.get("culprit"),
        issue.get("level"),
        project.get("platform"),
        project.get("slug"),
        metadata.get("type"),
        metadata.get("value"),
        metadata.get("title"),
    ]
    return " ".join(str(v).lower() for v in fields if v)


def int_field(issue: dict[str, Any], *names: str) -> int:
    for name in names:
        value = issue.get(name)
        if value is None:
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return 0


def classify(issue: dict[str, Any]) -> tuple[str, str]:
    text = issue_text(issue)
    for word in CLASS_KEYWORDS["client-disconnect"]:
        if word in text:
            return "client-disconnect", f"matched '{word}'"
    if "javascript" in text or "browser" in text:
        for word in CLASS_KEYWORDS["frontend-client"]:
            if word in text:
                return "frontend-client", f"matched '{word}'"
    best_class = "unknown"
    best_hits: list[str] = []
    for class_name, keywords in CLASS_KEYWORDS.items():
        hits = [word for word in keywords if word in text]
        if len(hits) > len(best_hits):
            best_class = class_name
            best_hits = hits
    if best_hits:
        return best_class, "matched " + ", ".join(f"'{hit}'" for hit in best_hits[:3])
    if issue.get("level") == "fatal":
        return "availability", "fatal issue level"
    return "unknown", "no strong keyword match"


def priority(issue: dict[str, Any], issue_class: str) -> str:
    count = int_field(issue, "count")
    users = int_field(issue, "userCount", "users")
    level = str(issue.get("level") or "").lower()
    if issue_class == "client-disconnect":
        if count >= 2000 or users >= 100:
            return "P2"
        return "P3"
    if issue_class == "availability" and (count >= 1000 or users >= 50):
        return "P0"
    if issue_class in {"dependency", "performance-timeout"} and (count >= 500 or users >= 20):
        return "P0"
    if count >= 100 or users >= 10 or (
        level == "fatal"
        and issue_class in {"availability", "performance-timeout", "dependency"}
    ):
        return "P1"
    if count >= 50 or users >= 5 or issue_class in {"auth-permission", "data-integrity"}:
        return "P2"
    return "P3"


def summarize_issue(issue: dict[str, Any]) -> dict[str, Any]:
    issue_class, reason = classify(issue)
    project = issue.get("project") or {}
    metadata = issue.get("metadata") or {}
    title = issue.get("title") or metadata.get("title") or metadata.get("type") or "Untitled"
    return {
        "id": issue.get("id"),
        "shortId": issue.get("shortId"),
        "title": title,
        "project": project.get("slug") or project.get("name"),
        "platform": project.get("platform"),
        "class": issue_class,
        "classificationReason": reason,
        "priority": priority(issue, issue_class),
        "count": int_field(issue, "count"),
        "userCount": int_field(issue, "userCount", "users"),
        "level": issue.get("level"),
        "firstSeen": issue.get("firstSeen"),
        "lastSeen": issue.get("lastSeen"),
        "permalink": issue.get("permalink"),
        "culprit": issue.get("culprit"),
    }


def split_csv(value: str | None) -> set[str]:
    if not value:
        return set()
    return {item.strip() for item in value.split(",") if item.strip()}


def load_ignore_rules(path_value: str | None) -> list[dict[str, Any]]:
    if not path_value:
        return []
    path = Path(path_value)
    if not path.exists():
        raise RuntimeError(f"SENTRY_IGNORE_FILE does not exist: {path}")
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return list(data.get("ignore", []))
    raise RuntimeError("Ignore file must be a JSON object with 'ignore' or a JSON list.")


def rule_active(rule: dict[str, Any], now: dt.datetime) -> bool:
    until = rule.get("until")
    if not until:
        return True
    try:
        parsed = dt.datetime.fromisoformat(str(until).replace("Z", "+00:00"))
    except ValueError:
        return True
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed > now


def ignore_reason(item: dict[str, Any], rules: list[dict[str, Any]], env_ids: set[str]) -> str | None:
    labels = {str(item.get("id") or ""), str(item.get("shortId") or "")}
    if labels & env_ids:
        return "matched SENTRY_IGNORE_IDS"

    text = " ".join(
        str(value).lower()
        for value in (
            item.get("title"),
            item.get("project"),
            item.get("class"),
            item.get("culprit"),
            item.get("shortId"),
            item.get("id"),
        )
        if value
    )
    now = dt.datetime.now(dt.timezone.utc)
    for rule in rules:
        if not rule_active(rule, now):
            continue
        if rule.get("id") and str(rule["id"]) != str(item.get("id")):
            continue
        if rule.get("shortId") and str(rule["shortId"]) != str(item.get("shortId")):
            continue
        if rule.get("project") and str(rule["project"]).lower() != str(item.get("project")).lower():
            continue
        if rule.get("class") and str(rule["class"]) != str(item.get("class")):
            continue
        title_contains = rule.get("titleContains")
        if title_contains and str(title_contains).lower() not in text:
            continue
        return str(rule.get("reason") or "matched ignore rule")
    return None


def apply_ignores(
    issues: list[dict[str, Any]], rules: list[dict[str, Any]], env_ids: set[str]
) -> list[dict[str, Any]]:
    for item in issues:
        reason = ignore_reason(item, rules, env_ids)
        item["ignored"] = bool(reason)
        item["ignoreReason"] = reason
    return issues


def load_latest_snapshot(output_dir: Path, current_json: Path) -> dict[str, Any] | None:
    snapshots = sorted(output_dir.glob("sentry-issues-*.json"))
    snapshots.extend(sorted((output_dir / "snapshots").glob("sentry-issues-*.json")))
    snapshots = [path for path in snapshots if path != current_json]
    if not snapshots:
        return None
    with snapshots[-1].open("r", encoding="utf-8") as handle:
        return json.load(handle)


def compare_counts(current: list[dict[str, Any]], previous: dict[str, Any] | None) -> str:
    if not previous:
        return "No previous snapshot found for comparison."
    previous_by_id = {str(item.get("id")): item for item in previous.get("issues", [])}
    deltas = []
    for item in current:
        prev = previous_by_id.get(str(item.get("id")))
        if not prev:
            continue
        delta = int(item["count"]) - int(prev.get("count") or 0)
        deltas.append((abs(delta), delta, item))
    if not deltas:
        return "No overlapping issues found in the previous snapshot."
    deltas.sort(reverse=True, key=lambda row: row[0])
    lines = ["Largest count changes versus previous snapshot:"]
    for _, delta, item in deltas[:10]:
        sign = "+" if delta >= 0 else ""
        lines.append(f"- {sign}{delta}: {item['shortId'] or item['id']} {item['title']}")
    return "\n".join(lines)


def class_counts(items: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        counts[item["class"]] = counts.get(item["class"], 0) + 1
    return dict(sorted(counts.items(), key=lambda pair: (-pair[1], pair[0])))


def safe_name(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip())
    return cleaned.strip("-")[:120] or "issue"


def danger_assessment(item: dict[str, Any]) -> tuple[str, str]:
    issue_class = item["class"]
    count = int(item["count"])
    users = int(item["userCount"])
    title = str(item.get("title") or "").lower()
    if item["priority"] == "P0":
        return (
            "high",
            "High volume or broad service-failure signal. Treat as user-impacting until disproven.",
        )
    if issue_class in {"dependency", "performance-timeout"} and count >= 100:
        return (
            "medium-high",
            "Dependency or timeout failures can cascade into user-visible errors and retry storms.",
        )
    if issue_class == "client-disconnect":
        return (
            "low",
            "Usually caused by caller disconnects; dangerous only if correlated with latency or gateway resets.",
        )
    if issue_class == "input-validation" or "404" in title or "400" in title:
        return (
            "medium",
            "Likely contract or bad-input failure. Dangerous if it blocks a core workflow or affects many users.",
        )
    if issue_class in {"auth-permission", "data-integrity"}:
        return (
            "medium-high",
            "Can indicate access drift or data consistency risk even at lower volume.",
        )
    if users >= 5 or count >= 50:
        return ("medium", "Non-trivial volume; review before suppressing.")
    return ("low", "Limited evidence of broad impact from the issue list alone.")


def suggested_action(item: dict[str, Any]) -> list[str]:
    issue_class = item["class"]
    title = str(item.get("title") or "")
    actions = [
        "Open the latest Sentry event and inspect stack trace, tags, release, environment, and affected endpoint.",
        "Compare firstSeen/lastSeen with recent deploys, config changes, feature flags, and infrastructure events.",
    ]
    if "CannotCreateTransactionException" in title or "JDBC Connection" in title:
        actions.extend(
            [
                "Check DB health, connection pool saturation, slow queries, and active transaction count at the incident time.",
                "Look for retry amplification from callers and reduce concurrency or disable the triggering job if the pool is exhausted.",
            ]
        )
    elif "asset-service" in title and ("500" in title or "inspection" in title):
        actions.extend(
            [
                "Check asset-service inspection job generation around the same timestamp as DB connection failures.",
                "Verify whether duplicate job generation or batch insert failures are creating retries.",
            ]
        )
    elif issue_class in {"dependency", "performance-timeout"}:
        actions.extend(
            [
                "Check upstream service health, network path, DNS, timeout settings, and retry policy.",
                "If the upstream is optional, degrade gracefully or disable the integration temporarily.",
            ]
        )
    elif issue_class == "client-disconnect":
        actions.extend(
            [
                "Hold notification unless backend latency, gateway resets, or customer reports increased at the same time.",
                "If accepted as noise, add an ignore rule by class with a documented reason.",
            ]
        )
    elif issue_class == "input-validation":
        actions.extend(
            [
                "Route to the owning feature team as API contract/backlog work unless this blocks a critical user path.",
                "Add request validation or caller-side guardrails so bad requests do not page on-call.",
            ]
        )
    elif issue_class in {"auth-permission", "data-integrity"}:
        actions.extend(
            [
                "Verify recent token, role, schema, or migration changes.",
                "Preserve sample payloads and stop writes if there is any chance of data corruption.",
            ]
        )
    else:
        actions.append("Use MCP or the Sentry UI to fetch sample events before deciding whether to notify users.")
    return actions


def send_recommendation(item: dict[str, Any]) -> tuple[str, str]:
    danger, _ = danger_assessment(item)
    if item.get("ignored"):
        return ("hold", "Matched ignore rules.")
    if item["priority"] == "P0":
        return ("send", "P0 issue. Send to on-call or owning team after attaching this analysis.")
    if danger in {"medium-high", "high"} and int(item["count"]) >= 100:
        return ("review", "Potentially important, but keep in review queue unless P0 policy includes P1.")
    return ("hold", "Keep in report/backlog; do not send as an alert.")


def alert_analysis_markdown(item: dict[str, Any], snapshot: dict[str, Any]) -> str:
    danger, danger_reason = danger_assessment(item)
    decision, decision_reason = send_recommendation(item)
    label = item.get("shortId") or item.get("id") or "issue"
    actions = "\n".join(f"- {action}" for action in suggested_action(item))
    return "\n".join(
        [
            "---",
            f"send_status: {decision}",
            f"priority: {item['priority']}",
            f"danger: {danger}",
            f"project: {item.get('project') or ''}",
            f"issue: {label}",
            "---",
            "",
            f"# Alert Analysis: {label}",
            "",
            "## Decision",
            "",
            f"- Recommendation: `{decision}`",
            f"- Reason: {decision_reason}",
            "",
            "## What It Is",
            "",
            f"- Title: {item.get('title') or ''}",
            f"- Class: `{item['class']}` ({item.get('classificationReason') or 'no reason recorded'})",
            f"- Project: `{item.get('project') or ''}`",
            f"- Level: `{item.get('level') or ''}`",
            f"- Count in {snapshot['statsPeriod']}: `{item['count']}`",
            f"- Affected users: `{item['userCount']}`",
            f"- First seen: `{item.get('firstSeen') or ''}`",
            f"- Last seen: `{item.get('lastSeen') or ''}`",
            f"- Link: {item.get('permalink') or ''}",
            "",
            "## Danger Assessment",
            "",
            f"- Danger: `{danger}`",
            f"- Why: {danger_reason}",
            "",
            "## Suggested Next Steps",
            "",
            actions,
            "",
            "## Runbook Notes",
            "",
            "- If the owning dev team confirms this is not important, add it to `SENTRY_IGNORE_FILE` with a reason and optional expiry.",
            "- If sent to users/on-call, move this file from `alerts/pending` to `alerts/approved` before a sender job pushes it.",
            "",
        ]
    )


def ensure_output_dirs(output_dir: Path) -> dict[str, Path]:
    dirs = {
        "reports": output_dir / "reports",
        "snapshots": output_dir / "snapshots",
        "pending": output_dir / "alerts" / "pending",
        "approved": output_dir / "alerts" / "approved",
        "sent": output_dir / "alerts" / "sent",
        "ignored": output_dir / "alerts" / "ignored",
        "runbooks": output_dir / "runbooks",
    }
    for path in dirs.values():
        path.mkdir(parents=True, exist_ok=True)
    return dirs


def write_alert_queue(
    snapshot: dict[str, Any], output_dirs: dict[str, Path], stamp: str
) -> list[Path]:
    critical_priorities = set(snapshot.get("criticalPriorities") or ["P0"])
    active = [
        item
        for item in snapshot["issues"]
        if not item.get("ignored") and item["priority"] in critical_priorities
    ]
    written: list[Path] = []
    for item in sorted(active, key=lambda x: (x["priority"], -x["count"])):
        label = safe_name(str(item.get("shortId") or item.get("id") or "issue"))
        path = output_dirs["pending"] / f"{stamp}-{label}.md"
        path.write_text(alert_analysis_markdown(item, snapshot), encoding="utf-8")
        written.append(path)

    index_lines = [
        f"# Pending Alert Queue - {snapshot['statsPeriod']}",
        "",
        f"- Generated: {snapshot['generatedAt']}",
        f"- Critical priorities: {', '.join(snapshot.get('criticalPriorities') or ['P0'])}",
        f"- Pending alert files: {len(written)}",
        "",
    ]
    for path in written:
        index_lines.append(f"- {path.name}")
    index_path = output_dirs["pending"] / f"{stamp}-index.md"
    index_path.write_text("\n".join(index_lines) + "\n", encoding="utf-8")
    written.append(index_path)
    return written


def markdown_report(
    snapshot: dict[str, Any], compare_text: str | None, top: int
) -> str:
    issues = snapshot["issues"]
    active_issues = [item for item in issues if not item.get("ignored")]
    ignored_issues = [item for item in issues if item.get("ignored")]
    by_class = class_counts(active_issues)
    critical_priorities = set(snapshot.get("criticalPriorities") or ["P0", "P1"])
    critical = [item for item in active_issues if item["priority"] in critical_priorities]
    lines = [
        f"# Sentry Issue Playbook - {snapshot['statsPeriod']}",
        "",
        "## Situation",
        "",
        f"- Generated: {snapshot['generatedAt']}",
        f"- Sentry: {snapshot['baseUrl']}",
        f"- Organization: {snapshot['organization']}",
        f"- Query: `{snapshot['query']}`",
        f"- Environment: `{snapshot.get('environment') or 'all'}`",
        f"- Issues fetched: {len(issues)}",
        f"- Ignored issues: {len(ignored_issues)}",
        f"- Critical active issues queued for agent review: {len(critical)}",
        "",
        "## Classification Summary",
        "",
    ]
    if by_class:
        lines.extend(f"- {name}: {count}" for name, count in by_class.items())
    else:
        lines.append("- No issues matched the query.")
    lines.extend(["", "## Critical Issues", ""])
    if critical:
        lines.append(
            "These issues are written to `alerts/pending/` for analysis before any notification is sent."
        )
        lines.append("")
        lines.append("| Priority | Class | Project | Issue | Count | Users | Last Seen |")
        lines.append("| --- | --- | --- | --- | ---: | ---: | --- |")
        for item in sorted(critical, key=lambda x: (x["priority"], -x["count"]))[:top]:
            label = item.get("shortId") or item.get("id") or "issue"
            title = str(item.get("title") or "").replace("|", "\\|")
            lines.append(
                f"| {item['priority']} | {item['class']} | {item.get('project') or ''} | "
                f"{label}: {title} | {item['count']} | {item['userCount']} | {item.get('lastSeen') or ''} |"
            )
    else:
        lines.append("No active P0/P1 issues after ignore rules.")
    lines.extend(
        [
            "",
            "## Analyze Before Send",
            "",
            "- Review the per-issue Markdown files in `alerts/pending/`.",
            "- Send only files whose front matter has `send_status: send` after human or agent approval.",
            "- Move approved files to `alerts/approved/`; `run_send_teams_alerts.sh` pushes only from that folder.",
            "- Move accepted noise to `alerts/ignored/` and add a matching `SENTRY_IGNORE_FILE` rule.",
            "",
            "## Immediate Triage",
            "",
            "- Confirm the top P0/P1 issues are still increasing in the selected window.",
            "- Check the latest deployment, release, feature flag, and infrastructure changes before deep debugging.",
            "- Use Sentry MCP or the Sentry UI for stack traces, sample events, owners, suspect commits, and affected releases.",
            "- Apply reversible mitigations first: rollback, disable feature flag, scale workers, pause noisy job, or isolate failing dependency.",
            "",
            "## Likely Causes",
            "",
        ]
    )
    for name in by_class:
        lines.append(f"- {name}: {cause_for_class(name)}")
    lines.extend(
        [
            "",
        "## Mitigation",
        "",
        "- P0/P1 availability or dependency: rollback recent change, route around failing dependency, increase capacity, or disable the failing path.",
        "- Auth or data integrity: stop the write path if it can corrupt data, preserve samples, and verify token/config/schema changes.",
        "- Client disconnects: suppress or lower alert severity unless correlated with backend latency, gateway resets, or broad user impact.",
        "- 400/404 Feign errors: route to owning feature team as contract/backlog work unless volume or users cross the critical threshold.",
        "- Frontend noise: separate browser-extension/client-only issues from release regressions before paging backend owners.",
        "- Unknown: inspect a sample event and stack trace before assigning ownership.",
            "",
            "## Debugging Path",
            "",
            "- For each P0/P1, inspect latest event, stack trace, tags, release, environment, affected users, and suspect commits.",
            "- Compare firstSeen/lastSeen against deploys and infrastructure changes.",
            "- Group related issues by project, culprit, and dependency before opening tickets.",
            "",
            "## Follow-up Window",
            "",
            "After mitigation, rerun with a smaller window, for example `--hours 4 --compare-to latest`, and verify top issue counts stop increasing.",
            "",
        ]
    )
    if compare_text:
        lines.extend(["## Comparison", "", compare_text, ""])
    if ignored_issues:
        lines.extend(["## Ignored Issues", ""])
        lines.append("| Project | Issue | Class | Count | Reason |")
        lines.append("| --- | --- | --- | ---: | --- |")
        for item in sorted(ignored_issues, key=lambda x: -x["count"])[:top]:
            label = item.get("shortId") or item.get("id") or "issue"
            title = str(item.get("title") or "").replace("|", "\\|")
            reason = str(item.get("ignoreReason") or "").replace("|", "\\|")
            lines.append(
                f"| {item.get('project') or ''} | {label}: {title} | {item['class']} | {item['count']} | {reason} |"
            )
        lines.append("")
    lines.extend(["## Issue Table", ""])
    lines.append(
        "| Priority | Status | Class | Project | Issue | Count | Users | Level | Last Seen | Link |"
    )
    lines.append("| --- | --- | --- | --- | --- | ---: | ---: | --- | --- | --- |")
    for item in sorted(issues, key=lambda x: (x["priority"], -x["count"]))[:top]:
        label = item.get("shortId") or item.get("id") or "issue"
        title = str(item.get("title") or "").replace("|", "\\|")
        link = item.get("permalink") or ""
        issue_cell = f"{label}: {title}"
        status = "ignored" if item.get("ignored") else "active"
        lines.append(
            f"| {item['priority']} | {status} | {item['class']} | {item.get('project') or ''} | "
            f"{issue_cell} | {item['count']} | {item['userCount']} | "
            f"{item.get('level') or ''} | {item.get('lastSeen') or ''} | {link} |"
        )
    lines.append("")
    return "\n".join(lines)


def cause_for_class(class_name: str) -> str:
    return {
        "availability": "critical request path, process crash, failing worker, or broad service outage.",
        "dependency": "upstream service, network, database, cache, queue, or provider instability.",
        "auth-permission": "token rotation, missing role, expired credentials, invalid signature, or access policy drift.",
        "data-integrity": "schema drift, migration issue, malformed persisted data, serialization mismatch, or violated invariant.",
        "input-validation": "bad client payload, missing validation guard, incompatible API contract, or unhandled boundary type.",
        "frontend-client": "browser-specific regression, chunk/release mismatch, hydration bug, source map issue, or extension noise.",
        "performance-timeout": "slow dependency, overloaded workers, lock contention, rate limiting, memory pressure, or undersized capacity.",
        "client-disconnect": "client, gateway, or caller closed the request before the backend completed the response.",
        "unknown": "insufficient issue-list signal; inspect sample events and stack traces.",
    }.get(class_name, "inspect sample events for a grounded hypothesis.")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    window = parser.add_mutually_exclusive_group()
    window.add_argument("--days", type=int, default=None, help="Lookback window in days.")
    window.add_argument("--hours", type=int, default=None, help="Lookback window in hours.")
    parser.add_argument("--stats-period", help="Explicit Sentry statsPeriod, such as 7d or 4h.")
    parser.add_argument("--output-dir", default=env("SENTRY_OUTPUT_DIR", "./sentry-playbooks"))
    parser.add_argument("--limit", type=int, default=int(env("SENTRY_LIMIT", "100") or "100"))
    parser.add_argument("--top", type=int, default=50, help="Rows to include in Markdown table.")
    parser.add_argument(
        "--compare-to",
        choices=["latest", "none"],
        default="none",
        help="Compare current counts to latest prior JSON snapshot.",
    )
    return parser


def main() -> int:
    args = build_arg_parser().parse_args()
    base_url = env("SENTRY_BASE_URL")
    token = env("SENTRY_AUTH_TOKEN")
    if not base_url or not token:
        print("SENTRY_BASE_URL and SENTRY_AUTH_TOKEN are required.", file=sys.stderr)
        return 2

    if args.stats_period:
        stats_period = args.stats_period
    elif args.hours:
        stats_period = f"{args.hours}h"
    else:
        stats_period = f"{args.days or 7}d"

    client = SentryClient(base_url, token)
    org = env("SENTRY_ORG") or discover_org(client)
    query = env("SENTRY_QUERY", "is:unresolved") or "is:unresolved"
    project_specs = parse_projects(env("SENTRY_PROJECTS"))
    projects = resolve_projects(client, org, project_specs)
    environment = env("SENTRY_ENVIRONMENT")

    raw_issues = fetch_issues(
        client=client,
        org=org,
        stats_period=stats_period,
        query=query,
        projects=projects,
        environment=environment,
        limit=args.limit,
    )
    issues = [summarize_issue(issue) for issue in raw_issues]
    issues = apply_ignores(
        issues,
        rules=load_ignore_rules(env("SENTRY_IGNORE_FILE")),
        env_ids=split_csv(env("SENTRY_IGNORE_IDS")),
    )
    output_dir = Path(args.output_dir)
    output_dirs = ensure_output_dirs(output_dir)
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    json_path = output_dirs["snapshots"] / f"sentry-issues-{stats_period}-{stamp}.json"
    md_path = output_dirs["reports"] / f"sentry-playbook-{stats_period}-{stamp}.md"
    snapshot = {
        "generatedAt": iso_now(),
        "baseUrl": normalize_base_url(base_url),
        "organization": org,
        "statsPeriod": stats_period,
        "query": query,
        "projectSpecs": project_specs,
        "projects": projects,
        "environment": environment,
        "criticalPriorities": sorted(split_csv(env("SENTRY_CRITICAL_PRIORITIES", "P0"))),
        "issues": issues,
    }
    with json_path.open("w", encoding="utf-8") as handle:
        json.dump(snapshot, handle, indent=2, sort_keys=True)
        handle.write("\n")

    previous = load_latest_snapshot(output_dir, json_path) if args.compare_to == "latest" else None
    compare_text = compare_counts(issues, previous) if args.compare_to == "latest" else None
    md_path.write_text(markdown_report(snapshot, compare_text, args.top), encoding="utf-8")
    alert_paths = write_alert_queue(snapshot, output_dirs, stamp)
    print(f"Wrote {md_path}")
    print(f"Wrote {json_path}")
    print(f"Wrote {len(alert_paths)} alert queue file(s) under {output_dirs['pending']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
