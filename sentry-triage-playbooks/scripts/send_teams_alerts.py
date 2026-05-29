#!/usr/bin/env python3
"""Send approved Sentry alert analyses to a Microsoft Teams channel webhook."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import shutil
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


def env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    return value if value not in (None, "") else default


def iso_now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_timestamp(value: str) -> dt.datetime | None:
    text = (value or "").strip()
    if not text:
        return None
    try:
        parsed = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def parse_front_matter(raw: str) -> tuple[dict[str, str], str]:
    if not raw.startswith("---\n"):
        return {}, raw
    end = raw.find("\n---\n", 4)
    if end < 0:
        return {}, raw
    block = raw[4:end]
    body = raw[end + 5 :]
    meta: dict[str, str] = {}
    for line in block.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        meta[key.strip()] = value.strip()
    return meta, body


def extract_bullet(body: str, label: str) -> str | None:
    pattern = re.compile(rf"^-\s*{re.escape(label)}:\s*(.+)$", re.MULTILINE)
    match = pattern.search(body)
    if not match:
        return None
    value = match.group(1).strip()
    value = value.replace("`", "")
    return value


def extract_steps(body: str, limit: int = 3) -> list[str]:
    section = re.search(
        r"^##\s+Suggested Next Steps\s*$([\s\S]*?)(?:^##\s+|\Z)", body, re.MULTILINE
    )
    if not section:
        return []
    lines = section.group(1).splitlines()
    steps: list[str] = []
    for line in lines:
        text = line.strip()
        if text.startswith("- "):
            steps.append(text[2:].strip())
        if len(steps) >= limit:
            break
    return steps


def extract_count_value(body: str) -> str:
    match = re.search(r"^-\s*Count in [^:]+:\s*(.+)$", body, re.MULTILINE)
    if not match:
        return ""
    return match.group(1).strip().replace("`", "")


def parse_alert(path: Path) -> dict[str, Any]:
    raw = path.read_text(encoding="utf-8")
    meta, body = parse_front_matter(raw)
    title = extract_bullet(body, "Title") or "(no title)"
    issue_class = extract_bullet(body, "Class") or "unknown"
    link = extract_bullet(body, "Link") or ""
    steps = extract_steps(body)
    return {
        "path": path,
        "meta": meta,
        "body": body,
        "issue": meta.get("issue") or path.stem,
        "priority": meta.get("priority") or "P3",
        "danger": meta.get("danger") or "low",
        "project": meta.get("project") or "",
        "send_status": (meta.get("send_status") or "").lower(),
        "title": title,
        "class": issue_class,
        "count": extract_count_value(body),
        "users": extract_bullet(body, "Affected users") or "",
        "first_seen": extract_bullet(body, "First seen") or "",
        "last_seen": extract_bullet(body, "Last seen") or "",
        "decision": extract_bullet(body, "Recommendation") or "",
        "decision_reason": extract_bullet(body, "Reason") or "",
        "steps": steps,
        "link": link,
    }


def priority_color(priority: str) -> str:
    return {
        "P0": "E81123",
        "P1": "F7630C",
        "P2": "FFB900",
        "P3": "107C10",
    }.get(priority.upper(), "666666")


def build_message_card(alert: dict[str, Any]) -> dict[str, Any]:
    facts = [
        {"name": "Issue", "value": alert["issue"]},
        {"name": "Priority", "value": alert["priority"]},
        {"name": "Danger", "value": alert["danger"]},
    ]
    if alert["project"]:
        facts.append({"name": "Project", "value": alert["project"]})
    if alert["class"]:
        facts.append({"name": "Class", "value": alert["class"]})
    if alert["count"]:
        facts.append({"name": "Count", "value": alert["count"]})
    if alert["users"]:
        facts.append({"name": "Users", "value": alert["users"]})
    if alert["last_seen"]:
        facts.append({"name": "Last Seen", "value": alert["last_seen"]})

    lines = [
        f"**{alert['title']}**",
        "",
        f"Decision: `{alert['decision'] or alert['send_status'] or 'send'}`",
    ]
    if alert["decision_reason"]:
        lines.append(f"Reason: {alert['decision_reason']}")

    if alert["steps"]:
        lines.extend(["", "Suggested next steps:"])
        lines.extend(f"- {step}" for step in alert["steps"])

    card: dict[str, Any] = {
        "@type": "MessageCard",
        "@context": "https://schema.org/extensions",
        "summary": f"Sentry alert {alert['issue']}",
        "text": f"Sentry Alert [{alert['priority']}] {alert['issue']}: {alert['title']}",
        "themeColor": priority_color(alert["priority"]),
        "title": f"Sentry Alert [{alert['priority']}] {alert['issue']}",
        "sections": [
            {
                "facts": facts,
                "markdown": True,
                "text": "\n".join(lines),
            }
        ],
    }
    if alert["link"]:
        card["potentialAction"] = [
            {
                "@type": "OpenUri",
                "name": "Open in Sentry",
                "targets": [{"os": "default", "uri": alert["link"]}],
            }
        ]
    return card


def send_teams(webhook_url: str, payload: dict[str, Any], timeout: int) -> str:
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(webhook_url, data=data, method="POST")
    request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Teams webhook HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Could not reach Teams webhook: {exc}") from exc


def move_sent(path: Path, sent_dir: Path) -> Path:
    sent_dir.mkdir(parents=True, exist_ok=True)
    destination = sent_dir / path.name
    if destination.exists():
        suffix = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        destination = sent_dir / f"{path.stem}-{suffix}{path.suffix}"
    shutil.move(str(path), str(destination))
    return destination


def write_receipt(destination: Path, alert: dict[str, Any], webhook_response: str) -> None:
    receipt = {
        "sentAt": iso_now(),
        "issue": alert["issue"],
        "priority": alert["priority"],
        "project": alert["project"],
        "sourceFile": str(alert["path"]),
        "sentFile": str(destination),
        "webhookResponse": webhook_response[:500],
    }
    receipt_path = destination.with_suffix(destination.suffix + ".receipt.json")
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def approved_files(approved_dir: Path) -> list[Path]:
    if not approved_dir.exists():
        return []
    return sorted(path for path in approved_dir.glob("*.md") if path.is_file())


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default=env("SENTRY_OUTPUT_DIR", "./sentry-playbooks"))
    parser.add_argument("--approved-dir", help="Override approved alert directory")
    parser.add_argument("--sent-dir", help="Override sent alert directory")
    parser.add_argument("--limit", type=int, default=0, help="Maximum approved files to process (0 = all)")
    parser.add_argument("--dry-run", action="store_true", help="Render payloads without sending or moving files")
    return parser


def main() -> int:
    args = build_arg_parser().parse_args()
    root = Path(args.output_dir)
    approved_dir = Path(args.approved_dir) if args.approved_dir else root / "alerts" / "approved"
    sent_dir = Path(args.sent_dir) if args.sent_dir else root / "alerts" / "sent"

    webhook_url = env("TEAMS_WEBHOOK_URL")
    timeout = int(env("TEAMS_TIMEOUT", "15") or "15")
    max_age_hours = int(env("TEAMS_MAX_LAST_SEEN_AGE_HOURS", "0") or "0")
    now_utc = dt.datetime.now(dt.timezone.utc)

    files = approved_files(approved_dir)
    if args.limit > 0:
        files = files[: args.limit]

    if not files:
        print(f"No approved alert files found in {approved_dir}")
        return 0

    if not args.dry_run and not webhook_url:
        print("TEAMS_WEBHOOK_URL is required unless --dry-run is used.", file=sys.stderr)
        return 2

    processed = 0
    skipped = 0
    for path in files:
        alert = parse_alert(path)
        if not alert["meta"]:
            skipped += 1
            print(f"SKIP {path.name}: no front matter")
            continue
        if alert["send_status"] != "send":
            skipped += 1
            print(f"SKIP {path.name}: send_status={alert['send_status'] or 'missing'}")
            continue
        if max_age_hours > 0 and alert["last_seen"]:
            seen_at = parse_timestamp(alert["last_seen"])
            if seen_at and now_utc - seen_at > dt.timedelta(hours=max_age_hours):
                skipped += 1
                print(
                    f"SKIP {path.name}: last_seen older than {max_age_hours}h ({alert['last_seen']})"
                )
                continue

        payload = build_message_card(alert)
        if args.dry_run:
            print(f"DRY-RUN {path.name}")
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            processed += 1
            continue

        response = send_teams(webhook_url or "", payload, timeout)
        destination = move_sent(path, sent_dir)
        write_receipt(destination, alert, response)
        print(f"SENT {path.name} -> {destination}")
        processed += 1

    print(f"Processed={processed} Skipped={skipped} ApprovedScanned={len(files)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
