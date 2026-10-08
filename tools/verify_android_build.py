"""Verify GitHub-built Android test reports and distributable archives."""
import argparse
import json
import os
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def require(condition, message):
    if not condition:
        raise ValueError(message)


def verify_tests(build):
    reports = []
    by_variant = {}
    for variant in ("Debug", "Release"):
        task = f"test{variant}UnitTest"
        variant_reports = sorted((build / "test-results" / task).glob("TEST-*.xml"))
        require(variant_reports, f"Android {variant} unit test XML reports are missing")
        reports.extend(variant_reports)
        by_variant[task] = 0
    counts = dict.fromkeys(("tests", "failures", "errors", "skipped"), 0)
    for path in reports:
        suite = ET.parse(path).getroot()
        cases = list(suite.iter("testcase"))
        total = int(suite.get("tests", "0"))
        by_variant[path.parent.name] += total
        require(total > 0 and total == len(cases), f"Empty or inconsistent test report: {path}")
        for key in counts:
            count = int(suite.get(key, "0"))
            require(count >= 0, f"Invalid {key} count: {path}")
            counts[key] += count
        require(not any(case.find(tag) is not None for case in cases for tag in ("failure", "error", "skipped")),
                f"Failed, errored or unexpectedly skipped Android test: {path}")
    require(all(total >= 26 for total in by_variant.values()),
            f"At least 26 Android tests per variant required: {by_variant}")
    require(counts["failures"] == counts["errors"] == counts["skipped"] == 0,
            f"Android tests did not all pass: {counts}")
    return {**counts, "reports": len(reports), "tests_by_variant": by_variant}


def verify_lint(build):
    warnings = {}
    for variant in ("debug", "release"):
        path = build / "reports" / f"lint-results-{variant}.xml"
        require(path.is_file(), f"Android lint XML report is missing: {path}")
        issues = list(ET.parse(path).getroot().iter("issue"))
        require(not any(issue.get("severity", "").lower() in ("error", "fatal") for issue in issues),
                f"Android lint reported an error or fatal issue: {path}")
        warnings[variant] = len(issues)
    return {"errors": 0, "issues_by_variant": warnings}


def verify_archive(path, kind):
    require(path.is_file() and path.suffix.lower() == f".{kind}", f"Missing or invalid {kind.upper()}: {path}")
    fixture_names = {fixture.name.lower() for fixture in (ROOT / "tests" / "fixtures").rglob("*") if fixture.is_file()}
    fixture_names.add("pairing_vector.json")
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        require(names, f"Empty Android archive: {path}")
        for name in names:
            parts = name.replace("\\", "/").lower().split("/")
            require(parts[-1] not in fixture_names,
                    f"Test fixture included in Android archive: {path}: {name}")
            require(not any(part in ("fixture", "fixtures", "test-fixtures", "test_fixtures") for part in parts),
                    f"Fixture directory included in Android archive: {path}: {name}")
            require(not parts[-1].endswith((".jks", ".keystore")),
                    f"Private signing store included in Android archive: {path}: {name}")
    return {"path": str(path), "type": kind, "fixtures_and_private_keys_excluded": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-dir", type=Path, default=ROOT / "android" / "app" / "build")
    parser.add_argument("--apk", action="append", type=Path, default=[])
    parser.add_argument("--aab", action="append", type=Path, default=[])
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    require(os.environ.get("GITHUB_ACTIONS") == "true", "Android artifacts must be built and verified by GitHub Actions")
    require(args.apk or args.aab, "Provide at least one --apk or --aab to verify")
    report = {"tests": verify_tests(args.build_dir), "lint": verify_lint(args.build_dir),
              "archives": [verify_archive(path, kind) for kind, paths in (("apk", args.apk), ("aab", args.aab)) for path in paths],
              "commit": os.environ.get("GITHUB_SHA", ""),
              "run_url": f"https://github.com/{os.environ.get('GITHUB_REPOSITORY', '')}/actions/runs/{os.environ.get('GITHUB_RUN_ID', '')}"}
    encoded = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(encoded, encoding="utf-8", newline="\n")
    print(encoded, end="")


if __name__ == "__main__":
    main()
