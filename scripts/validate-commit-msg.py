#!/usr/bin/env python3
"""Validate Conventional Commits format on a commit message.

Used as a `commit-msg` git hook. Reads the message file path from argv[1]
and exits 0 if valid, 1 if not.

Spec: https://www.conventionalcommits.org/en/v1.0.0/

Format::

    <type>[optional scope][!]: <description>
    [optional body]
    [optional footer(s)]

Types allowed (project-defined): feat, fix, docs, style, refactor, test,
chore, build, ci, perf, revert, plus Revert for revert commits.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path


# type(scope)!: subject
HEADER_RE = re.compile(
    r"^(?P<type>[a-zA-Z]+)"
    r"(?:\((?P<scope>[^)]+)\))?"
    r"(?P<breaking>!)?"
    r": "
    r"(?P<subject>.+)$"
)

ALLOWED_TYPES = {
    "feat", "fix", "docs", "style", "refactor", "test", "chore",
    "build", "ci", "perf", "revert",
}

# Recognised footer tokens (Conventional Commits spec)
FOOTER_TOKENS = {
    "BREAKING CHANGE", "BREAKING-CHANGE",
    "Closes", "Closed", "Fixes", "Fixed", "Resolves", "Resolved",
    "Refs", "Ref",
    "Co-authored-by", "Signed-off-by", "Reviewed-by",
}


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: validate-commit-msg.py <commit-msg-file>", file=sys.stderr)
        return 1
    msg_path = Path(argv[1])
    raw = msg_path.read_text(encoding="utf-8")

    # Strip comments (lines starting with #) and collapse blank lines
    lines = [l for l in raw.splitlines() if not l.startswith("#")]
    while lines and lines[0].strip() == "":
        lines.pop(0)
    while lines and lines[-1].strip() == "":
        lines.pop()
    if not lines:
        print("commit-msg: empty message", file=sys.stderr)
        return 1

    subject = lines[0].strip()

    # Revert commits have their own shape — accept them as-is
    if subject.lower().startswith("revert "):
        return 0

    m = HEADER_RE.match(subject)
    if not m:
        print(
            f"commit-msg: subject doesn't match Conventional Commits format\n"
            f"  got: {subject!r}\n"
            f"  expected: <type>(<scope>): <subject>\n"
            f"  allowed types: {', '.join(sorted(ALLOWED_TYPES))}",
            file=sys.stderr,
        )
        return 1

    t = m.group("type").lower()
    if t not in ALLOWED_TYPES:
        print(
            f"commit-msg: unknown type {t!r}\n"
            f"  allowed: {', '.join(sorted(ALLOWED_TYPES))}",
            file=sys.stderr,
        )
        return 1

    subj = m.group("subject")
    if len(subject) > 72:
        print(
            f"commit-msg: subject too long ({len(subject)} > 72 chars)\n"
            f"  {subject!r}",
            file=sys.stderr,
        )
        return 1
    if subj.endswith("."):
        print(
            f"commit-msg: subject should not end with a period\n"
            f"  {subject!r}",
            file=sys.stderr,
        )
        return 1
    if subj != subj.strip():
        print(
            f"commit-msg: subject has leading/trailing whitespace\n"
            f"  {subject!r}",
            file=sys.stderr,
        )
        return 1

    # Body: if present, lines must be wrapped at 72 chars
    # Footer: lines must start with `<token>: ` or `<token> #`
    body = lines[1:]
    if body:
        # Look for BREAKING CHANGE / Refs / Closes / etc.
        for line in body:
            if len(line) > 100:
                print(
                    f"commit-msg: body/footer line too long ({len(line)} > 100 chars):\n"
                    f"  {line!r}",
                    file=sys.stderr,
                )
                return 1
            # Footer check: if line starts with a known token, must have ": "
            # But allow blank lines and "On-commit" notes from git revert.
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith("Revert ") or stripped.startswith("This reverts "):
                continue
            for token in FOOTER_TOKENS:
                if stripped.startswith(token + ":") or stripped.startswith(token + " #"):
                    break
            else:
                # Not a recognised footer — could be body text, that's fine
                continue

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))