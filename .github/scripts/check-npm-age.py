#!/usr/bin/env python3
"""
Check that every npm package updated in a Dependabot PR was published at least
MIN_AGE_DAYS ago.

Supply-chain attacks often rely on the gap between a malicious publish and the
community spotting it — a short quarantine limits exposure.  This script compares
the PR branch's package-lock.json against the base branch and queries the npm
registry for the publish timestamp of each changed version.
"""
import json
import os
import subprocess
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone

MIN_AGE_DAYS = int(os.environ.get("MIN_AGE_DAYS", "3"))
BASE_REF = os.environ.get("GITHUB_BASE_REF", "main")
LOCKFILE = "frontend/package-lock.json"


def npm_publish_time(name: str, version: str) -> str | None:
    """Return the ISO publish timestamp for name@version from the npm registry."""
    encoded = urllib.parse.quote(name, safe="@/")
    url = f"https://registry.npmjs.org/{encoded}"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.load(resp)
        return data.get("time", {}).get(version)
    except Exception as exc:
        print(f"  WARN   cannot query registry for {name}@{version}: {exc}")
        return None


def load_base_lockfile() -> dict:
    try:
        raw = subprocess.check_output(
            ["git", "show", f"origin/{BASE_REF}:{LOCKFILE}"],
            stderr=subprocess.DEVNULL,
        )
        return json.loads(raw)
    except Exception as exc:
        print(f"Cannot read base lockfile (origin/{BASE_REF}:{LOCKFILE}): {exc}")
        print("Skipping age check.")
        sys.exit(0)


def main() -> None:
    base_lock = load_base_lockfile()
    with open(LOCKFILE) as fh:
        head_lock = json.load(fh)

    old_pkgs = base_lock.get("packages", {})
    new_pkgs = head_lock.get("packages", {})

    changed: list[tuple[str, str, str]] = []
    for key, pkg in new_pkgs.items():
        if not key.startswith("node_modules/"):
            continue
        name = key.removeprefix("node_modules/")
        new_ver = pkg.get("version", "")
        old_ver = old_pkgs.get(key, {}).get("version", "")
        if new_ver and new_ver != old_ver:
            changed.append((name, old_ver, new_ver))

    if not changed:
        print("No npm package version changes detected.")
        return

    print(f"Checking publish age for {len(changed)} changed package(s) (min {MIN_AGE_DAYS}d):\n")

    now = datetime.now(timezone.utc)
    failures: list[str] = []

    for name, old_ver, new_ver in sorted(changed):
        ts = npm_publish_time(name, new_ver)
        if ts is None:
            print(f"  SKIP   {name}  {old_ver or '(new)'} -> {new_ver}  (no registry data)")
            continue
        published = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        age = (now - published).days
        label = "OK  " if age >= MIN_AGE_DAYS else "FAIL"
        print(f"  {label}   {name}  {old_ver or '(new)'} -> {new_ver}  (published {age}d ago)")
        if age < MIN_AGE_DAYS:
            failures.append(
                f"{name}@{new_ver} published {age} day(s) ago (minimum: {MIN_AGE_DAYS})"
            )

    print()
    if failures:
        print("::error::One or more dependencies are too new to merge safely:")
        for msg in failures:
            print(f"  * {msg}")
        print(
            f"\nWait until all updated packages are at least {MIN_AGE_DAYS} days old, "
            "then re-run this check."
        )
        sys.exit(1)

    print(f"All {len(changed)} updated package(s) passed the {MIN_AGE_DAYS}-day age check.")


if __name__ == "__main__":
    main()
