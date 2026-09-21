#!/usr/bin/env python3
"""Validate the lightweight governance files used by humans and agents."""

from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
STATUS_DIR = ROOT / "docs" / "status"
REQUIRED = {
    "workstream",
    "owner",
    "task",
    "status",
    "updated",
    "checkpoint",
    "branch",
    "contract_version",
}
ALLOWED_STATES = {"planned", "in_progress", "blocked", "review", "done"}
EXPECTED = {"model.md", "backend.md", "runtime.md", "integration.md"}
SPEC_FILES = {
    "README.md",
    "REQUIREMENTS.md",
    "OPEN_QUESTIONS.md",
    "TRACEABILITY.md",
}


def frontmatter(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    match = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    if not match:
        raise ValueError("missing YAML frontmatter")
    data: dict[str, str] = {}
    for raw in match.group(1).splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        key, sep, value = raw.partition(":")
        if not sep:
            raise ValueError(f"invalid frontmatter line: {raw}")
        data[key.strip()] = value.strip()
    return data


def main() -> int:
    errors: list[str] = []
    spec_dir = ROOT / "docs" / "spec"
    present_spec = {p.name for p in spec_dir.glob("*.md")}
    for missing in sorted(SPEC_FILES - present_spec):
        errors.append(f"missing specification file: {missing}")

    requirements_path = spec_dir / "REQUIREMENTS.md"
    if requirements_path.exists():
        requirement_text = requirements_path.read_text(encoding="utf-8")
        requirement_ids = re.findall(r"`(REQ-[A-Z0-9-]+)`", requirement_text)
        duplicates = sorted({item for item in requirement_ids if requirement_ids.count(item) > 1})
        if duplicates:
            errors.append(f"duplicate requirement IDs: {duplicates}")
        if not requirement_ids:
            errors.append("no requirement IDs found in specification")

    present = {p.name for p in STATUS_DIR.glob("*.md") if p.name != "README.md"}
    for missing in sorted(EXPECTED - present):
        errors.append(f"missing status file: {missing}")
    for path in sorted(STATUS_DIR.glob("*.md")):
        if path.name == "README.md":
            continue
        try:
            data = frontmatter(path)
        except ValueError as exc:
            errors.append(f"{path.relative_to(ROOT)}: {exc}")
            continue
        missing = REQUIRED - data.keys()
        if missing:
            errors.append(f"{path.relative_to(ROOT)}: missing {sorted(missing)}")
        if data.get("status") not in ALLOWED_STATES:
            errors.append(f"{path.relative_to(ROOT)}: invalid status {data.get('status')!r}")
        if data.get("contract_version") != "v0":
            errors.append(f"{path.relative_to(ROOT)}: unexpected contract version")

    # Construct signatures so the validator does not flag its own source.
    forbidden_patterns = (
        "pv" + "1_",
        "gh" + "p_",
        "github" + "_pat_",
        "BEGIN OPENSSH" + " PRIVATE KEY",
    )
    for path in ROOT.rglob("*"):
        if not path.is_file() or ".git" in path.parts:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for pattern in forbidden_patterns:
            if pattern in text:
                errors.append(f"{path.relative_to(ROOT)}: possible secret pattern {pattern!r}")

    if errors:
        print("Workspace validation: FAIL")
        for error in errors:
            print(f"- {error}")
        return 1
    print("Workspace validation: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
