"""
migrate_to_v1.py

Proof-of-concept migration script for the JSON Schema Test Suite unification project.
Run this from the root of the JSON-Schema-Test-Suite repo:

    python3 migrate_to_v1.py

What it does:
  1. Reads test cases from all per-version directories (draft4 through draft2020-12)
  2. Compares them across versions (ignoring $schema and specification fields)
  3. Assigns correct compatibility strings (matching annotations suite format)
  4. Reports what's already in v1/ and what's missing
  5. Shows exactly what compatibility strings each v1/ file needs
"""

import json
from pathlib import Path
from copy import deepcopy

# ── Version config ────────────────────────────────────────────────────────────
ALL_VERSIONS = ["4", "6", "7", "2019", "2020"]
VERSION_DIR = {
    "4":    "draft4",
    "6":    "draft6",
    "7":    "draft7",
    "2019": "draft2019-09",
    "2020": "draft2020-12",
}

# ── Helpers ───────────────────────────────────────────────────────────────────
def normalize(case):
    """Strip $schema and specification fields for semantic comparison."""
    c = deepcopy(case)
    if isinstance(c.get("schema"), dict):
        c["schema"].pop("$schema", None)
    c.pop("specification", None)
    return c

def cases_equal(a, b):
    return normalize(a) == normalize(b)

def build_compat(versions):
    """
    Build compatibility string matching annotations suite format.
    Examples:
      all versions          -> None       (omit field entirely)
      ["6","7","2019","2020"] -> "6"      (draft6 and above)
      ["7","2019","2020"]   -> "7"        (draft7 and above)
      ["2019","2020"]       -> "2019"     (draft2019-09 and above)
      ["2020"]              -> "=2020"    (only draft2020-12)
      ["4","6","7"]         -> "<=7"      (up to draft7)
      ["4","6"]             -> "<=6"      (up to draft6)
      ["4","7"]             -> "=4,=7"    (non-contiguous)
    """
    if set(versions) == set(ALL_VERSIONS):
        return None
    idx = sorted([ALL_VERSIONS.index(v) for v in versions])
    # Contiguous suffix: e.g. [7, 2019, 2020] -> "7"
    if idx == list(range(idx[0], len(ALL_VERSIONS))):
        return ALL_VERSIONS[idx[0]]
    # Contiguous prefix: e.g. [4, 6, 7] -> "<=7"
    if idx == list(range(0, idx[-1] + 1)):
        return f"<={ALL_VERSIONS[idx[-1]]}"
    # Single version
    if len(versions) == 1:
        return f"={versions[0]}"
    # Non-contiguous
    sorted_v = [ALL_VERSIONS[i] for i in idx]
    return ",".join(f"={v}" for v in sorted_v)

def load_all_versions(tests_dir, filename):
    """Load test cases from every version directory for a given filename."""
    result = {}
    for ver, dirname in VERSION_DIR.items():
        fp = tests_dir / dirname / filename
        if fp.exists():
            result[ver] = json.loads(fp.read_text(encoding="utf-8"))
        else:
            result[ver] = None
    return result

def migrate_file(tests_dir, filename):
    """
    Merge per-version test cases into a unified list with compatibility strings.
    Returns (unified_cases, report_dict)
    """
    version_tests = load_all_versions(tests_dir, filename)

    # Collect all unique descriptions in version order
    seen, all_descs = set(), []
    for ver in ALL_VERSIONS:
        cases = version_tests.get(ver)
        if cases:
            for case in cases:
                d = case["description"]
                if d not in seen:
                    seen.add(d)
                    all_descs.append(d)

    unified = []
    report = {"universal": [], "version_scoped": [], "divergent": []}

    for desc in all_descs:
        instances = {}
        for ver in ALL_VERSIONS:
            cases = version_tests.get(ver)
            if cases:
                for case in cases:
                    if case["description"] == desc:
                        instances[ver] = case
                        break

        present_in = list(instances.keys())
        base = list(instances.values())[0]
        all_same = all(cases_equal(base, c) for c in instances.values())

        if all_same:
            unified_case = normalize(deepcopy(base))
            compat = build_compat(present_in)
            if compat:
                unified_case["compatibility"] = compat
                report["version_scoped"].append({
                    "description": desc,
                    "present_in": present_in,
                    "compatibility": compat
                })
            else:
                report["universal"].append(desc)
            unified.append(unified_case)
        else:
            report["divergent"].append({
                "description": desc,
                "present_in": present_in,
            })
            # Keep separate per-version entries, flagged for manual review
            for ver, case in instances.items():
                c = normalize(deepcopy(case))
                c["compatibility"] = f"={ver}"
                c["description"] = f"{desc} [NEEDS REVIEW - version {ver}]"
                unified.append(c)

    return unified, report


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    repo_root = Path(".")
    tests_dir = repo_root / "tests"
    v1_dir    = tests_dir / "v1"

    # Collect all unique .json filenames across all version directories
    all_files = set()
    for ver, dirname in VERSION_DIR.items():
        d = tests_dir / dirname
        if d.exists():
            for f in d.glob("*.json"):
                all_files.add(f.name)
    all_files = sorted(all_files)

    print(f"Found {len(all_files)} unique test files across all versions\n")

    # ── Summary counters ──────────────────────────────────────────────────────
    total_universal    = 0
    total_scoped       = 0
    total_divergent    = 0
    missing_from_v1    = []
    present_in_v1      = []

    full_report = {}

    for filename in all_files:
        in_v1 = (v1_dir / filename).exists()
        if in_v1:
            present_in_v1.append(filename)
        else:
            missing_from_v1.append(filename)

        unified, report = migrate_file(tests_dir, filename)
        full_report[filename] = {
            "in_v1": in_v1,
            "unified": unified,
            "report": report
        }
        total_universal += len(report["universal"])
        total_scoped    += len(report["version_scoped"])
        total_divergent += len(report["divergent"])

    # ── Print results ─────────────────────────────────────────────────────────
    print("=" * 65)
    print("FILES ALREADY IN v1/ (need compatibility strings added)")
    print("=" * 65)
    for filename in present_in_v1:
        r = full_report[filename]["report"]
        total = len(r["universal"]) + len(r["version_scoped"]) + len(r["divergent"])
        print(f"\n  {filename} ({total} cases)")
        if r["universal"]:
            print(f"    universal (no compat needed):  {len(r['universal'])}")
        if r["version_scoped"]:
            print(f"    version-scoped (compat needed): {len(r['version_scoped'])}")
            for item in r["version_scoped"]:
                print(f"      \"{item['description'][:50]}\"")
                print(f"        versions={item['present_in']}  ->  compatibility=\"{item['compatibility']}\"")
        if r["divergent"]:
            print(f"    DIVERGENT (manual review): {len(r['divergent'])}")
            for item in r["divergent"]:
                print(f"      \"{item['description'][:55]}\"  in={item['present_in']}")

    print("\n" + "=" * 65)
    print("FILES MISSING FROM v1/ (need to be ported in)")
    print("=" * 65)
    for filename in missing_from_v1:
        r = full_report[filename]["report"]
        total = len(r["universal"]) + len(r["version_scoped"]) + len(r["divergent"])
        print(f"\n  {filename} ({total} cases)")
        if r["version_scoped"]:
            for item in r["version_scoped"]:
                print(f"    compat=\"{item['compatibility']}\"  \"{item['description'][:50]}\"")
        if r["divergent"]:
            print(f"    DIVERGENT: {len(r['divergent'])} cases need manual review")

    print("\n" + "=" * 65)
    print("OVERALL SUMMARY")
    print("=" * 65)
    print(f"  Total unique files:              {len(all_files)}")
    print(f"  Already in v1/:                  {len(present_in_v1)}")
    print(f"  Missing from v1/ (need porting): {len(missing_from_v1)}")
    print(f"  Universal test cases:            {total_universal}")
    print(f"  Version-scoped test cases:       {total_scoped}")
    print(f"  Divergent (manual review):       {total_divergent}")

    # ── Write unified output ──────────────────────────────────────────────────
    output_dir = repo_root / "tests" / "v1_migrated"
    output_dir.mkdir(exist_ok=True)
    for filename in all_files:
        unified = full_report[filename]["unified"]
        (output_dir / filename).write_text(
            json.dumps(unified, indent=4, ensure_ascii=False),
            encoding="utf-8"
        )
    print(f"\n  Unified output written to: tests/v1_migrated/")
    print(f"  ({len(all_files)} files)")

    # ── Verify: compare v1_migrated vs existing v1 ───────────────────────────
    print("\n" + "=" * 65)
    print("VERIFICATION: v1_migrated vs existing v1/")
    print("=" * 65)
    mismatches = 0
    for filename in present_in_v1:
        v1_cases    = json.loads((v1_dir / filename).read_text(encoding="utf-8"))
        mig_cases   = json.loads((output_dir / filename).read_text(encoding="utf-8"))
        v1_descs    = {c["description"] for c in v1_cases}
        mig_descs   = {c["description"] for c in mig_cases if "NEEDS REVIEW" not in c["description"]}
        extra_in_mig   = mig_descs - v1_descs
        missing_in_mig = v1_descs - mig_descs
        if extra_in_mig or missing_in_mig:
            mismatches += 1
            print(f"\n  {filename}:")
            if extra_in_mig:
                print(f"    In migrated but not in v1: {extra_in_mig}")
            if missing_in_mig:
                print(f"    In v1 but not in migrated: {missing_in_mig}")
        else:
            print(f"  OK {filename} - all test descriptions match")
    if mismatches == 0:
        print("\n  All files match!")

if __name__ == "__main__":
    main()
