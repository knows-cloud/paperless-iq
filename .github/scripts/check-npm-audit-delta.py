#!/usr/bin/env python3
"""
Fail a PR only for npm advisories it *introduces*, not for ones already on the
base branch.

Why this exists
---------------
A plain `npm audit --audit-level=low` in the PR job asks "does the world
currently contain any advisory against our tree?".  That answer changes without
anyone touching the repo: when GHSA-2v37-7h3g-55p8 (nanoid) was published on
2026-08-08, every open PR went red at once — twelve of them, including the one
that carried the fix.  Worse, the audit step ran before tsc/eslint/i18n, so an
unrelated advisory suppressed all type and lint signal for six days.

The question a *PR gate* should ask is "does this change make us worse?".  That
is what this script checks: it audits the base lockfile and the head lockfile,
and fails only on advisories present in head but absent in base.

This is not a relaxation.  A PR that pulls in a vulnerable package is still
blocked immediately and at any severity.  Advisories that already affect main
are handled by the scheduled sweep (.github/workflows/audit-sweep.yml), which
catches them within a day instead of waiting for someone to open a PR.

Mirrors the base-vs-head approach of check-npm-age.py.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

BASE_REF = os.environ.get("GITHUB_BASE_REF", "main")
FRONTEND = "frontend"
LOCKFILE = f"{FRONTEND}/package-lock.json"
MANIFEST = f"{FRONTEND}/package.json"


def git_show(path: str) -> str | None:
    """Return the contents of path on the base branch, or None if unavailable."""
    try:
        return subprocess.check_output(
            ["git", "show", f"origin/{BASE_REF}:{path}"],
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except subprocess.CalledProcessError:
        return None


def audit(directory: str) -> dict | None:
    """Run `npm audit --json` in directory and return the parsed report."""
    proc = subprocess.run(
        ["npm", "audit", "--json", "--package-lock-only", "--audit-level=low"],
        cwd=directory,
        capture_output=True,
        text=True,
        check=False,
    )
    # npm audit exits 1 when it finds anything, so the exit code is not an error
    # signal here — only unparseable output is.
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        print(f"  WARN   could not parse npm audit output in {directory}")
        if proc.stderr:
            print(f"  WARN   stderr: {proc.stderr.strip()[:500]}")
        return None


def advisory_keys(report: dict) -> dict[tuple[str, object], dict]:
    """
    Flatten an audit report into {(package, advisory_id): info}.

    `via` entries are either a dict (a real advisory) or a string (the name of
    another package through which this one is affected).  Only dicts carry an
    advisory identity, so string entries are skipped — the packages they point
    at appear as their own top-level entries anyway.
    """
    out: dict[tuple[str, object], dict] = {}
    for name, vuln in (report.get("vulnerabilities") or {}).items():
        for via in vuln.get("via") or []:
            if not isinstance(via, dict):
                continue
            key = (name, via.get("source") or via.get("url") or via.get("title"))
            out[key] = {
                "package": name,
                "severity": via.get("severity") or vuln.get("severity") or "unknown",
                "title": via.get("title") or "(no title)",
                "url": via.get("url") or "",
                "range": via.get("range") or vuln.get("range") or "",
            }
    return out


def build_base_tree(tmp: str) -> bool:
    """Materialise the base branch's frontend manifest + lockfile into tmp."""
    manifest = git_show(MANIFEST)
    lockfile = git_show(LOCKFILE)
    if manifest is None or lockfile is None:
        return False
    with open(os.path.join(tmp, "package.json"), "w") as fh:
        fh.write(manifest)
    with open(os.path.join(tmp, "package-lock.json"), "w") as fh:
        fh.write(lockfile)
    return True


def report_failures(new: dict[tuple[str, object], dict]) -> None:
    print("::error::This PR introduces new npm advisories:")
    for info in sorted(new.values(), key=lambda i: (i["severity"], i["package"])):
        print(f"  * [{info['severity']}] {info['package']} {info['range']}")
        print(f"      {info['title']}")
        if info["url"]:
            print(f"      {info['url']}")
    print(
        "\nThese advisories are not present on the base branch, so this change "
        "introduces them.\nUpdate the offending dependency, or pull in a fixed "
        "version, before merging."
    )


def main() -> None:
    if shutil.which("npm") is None:
        print("npm not found; skipping audit delta check.")
        return

    head_report = audit(FRONTEND)
    if head_report is None:
        print("::error::Could not audit the PR branch — failing closed.")
        sys.exit(1)
    head = advisory_keys(head_report)

    if not head:
        print("No npm advisories on this branch at all. Nothing to compare.")
        return

    with tempfile.TemporaryDirectory() as tmp:
        if not build_base_tree(tmp):
            # No base to diff against (new file, shallow clone, renamed path).
            # Fail closed: treat every advisory as introduced.  Being strict on
            # the rare unknown is the safe direction for a security gate.
            print(
                f"::warning::Cannot read {MANIFEST}/{LOCKFILE} on origin/{BASE_REF}; "
                "treating all advisories as new."
            )
            report_failures(head)
            sys.exit(1)

        base_report = audit(tmp)

    if base_report is None:
        print("::error::Could not audit the base branch — failing closed.")
        sys.exit(1)
    base = advisory_keys(base_report)

    new = {k: v for k, v in head.items() if k not in base}
    pre_existing = len(head) - len(new)

    print(
        f"npm advisories — base: {len(base)}, head: {len(head)}, "
        f"introduced by this PR: {len(new)}"
    )
    if pre_existing:
        print(
            f"  ({pre_existing} pre-existing advisory/advisories carried over from "
            f"{BASE_REF} — these are tracked by the daily audit sweep, not by this gate.)"
        )
    print()

    if new:
        report_failures(new)
        sys.exit(1)

    print("No new advisories introduced by this PR.")


if __name__ == "__main__":
    main()
