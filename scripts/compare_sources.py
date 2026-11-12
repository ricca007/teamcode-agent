"""Count active C source lines and verify A/B + shared Python byte equality."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FULL = ROOT.parent / "teamcode-agent"
AREAS = [
    "backend/app/interface_registry",
    "backend/app/realtime",
    "backend/app/integration",
    "cli",
    "frontend/src",
]
EXTENSIONS = {".py", ".ts", ".tsx", ".css"}


def counts(root):
    return {
        area: sum(
            len(path.read_text(encoding="utf-8").splitlines())
            for path in (root / area).rglob("*")
            if path.is_file() and path.suffix in EXTENSIONS
        )
        for area in AREAS
    }


def main():
    changed, checked = [], []
    for path in sorted((FULL / "backend/app").rglob("*.py")):
        relative = path.relative_to(FULL)
        if relative.parts[2] in {"interface_registry", "realtime", "integration"}:
            continue
        checked.append(relative.as_posix())
        target = ROOT / relative
        if not target.exists() or target.read_bytes() != path.read_bytes():
            changed.append(relative.as_posix())
    report = {
        "baseline": "full working tree after C bug fixes",
        "counting": "physical lines in .py/.ts/.tsx/.css, including comments and blank lines",
        "full_active_c_lines": counts(FULL),
        "mvp_active_c_lines": counts(ROOT),
        "unchanged_ab_and_shared_python_files": len(checked) - len(changed),
        "changed_ab_files": changed,
        "checked_ab_files": checked,
        "excludes": [
            "tests",
            "docs",
            "dependencies",
            "generated assets",
        ],
    }
    (ROOT / "docs/source-comparison.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "unchanged": len(checked) - len(changed),
                "changed": changed,
                "full_lines": sum(report["full_active_c_lines"].values()),
                "mvp_lines": sum(report["mvp_active_c_lines"].values()),
            }
        )
    )
    if changed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
