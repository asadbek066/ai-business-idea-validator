"""Fail a CI build when tracked files contain recognizable secret literals."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

PATTERNS = (
    ("OpenAI-style token", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
    ("Google API key", re.compile(r"\bAIza[0-9A-Za-z_-]{20,}\b")),
    ("GitHub token", re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b")),
    ("Slack token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b")),
    (
        "private key",
        re.compile(r"-----BEGIN (?:RSA|OPENSSH|EC|DSA|PGP) PRIVATE KEY-----"),
    ),
)


def tracked_paths() -> list[Path]:
    output = subprocess.check_output(["git", "ls-files", "-z"])
    return [Path(raw) for raw in output.decode().split("\0") if raw]


def main() -> int:
    findings = 0
    for path in tracked_paths():
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for line_number, line in enumerate(text.splitlines(), start=1):
            for label, pattern in PATTERNS:
                if pattern.search(line):
                    print(f"{path}:{line_number}: {label} pattern detected")
                    findings += 1
    if findings:
        print(f"Secret scan failed with {findings} finding(s); values were not printed.")
        return 1
    print("Secret scan passed: no recognizable credential literals found.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
