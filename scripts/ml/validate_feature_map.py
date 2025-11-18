from __future__ import annotations

import json
import sys
from pathlib import Path

VALID_TRANSFORMS = {"identity", "log1p", "abs", "ratio", "diff"}


def validate_map(path: Path) -> list[str]:
    errs: list[str] = []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        return [f"{path}: invalid JSON: {e}"]
    if not isinstance(data, dict):
        return [f"{path}: root must be an object"]
    for name, spec in data.items():
        if not isinstance(spec, dict):
            errs.append(f"{path}:{name}: spec must be an object")
            continue
        t = str(spec.get("transform", "identity"))
        if t not in VALID_TRANSFORMS:
            errs.append(f"{path}:{name}: invalid transform '{t}'")
        imp = spec.get("importance", 100)
        try:
            imp = int(imp)
        except Exception:
            errs.append(f"{path}:{name}: importance must be int")
        if t in {"ratio", "diff"}:
            s1 = spec.get("src1")
            s2 = spec.get("src2")
            if not s1 or not s2:
                errs.append(f"{path}:{name}: ratio/diff requires src1 and src2")
        else:
            # single source must have csv_col (defaulting to feature name is acceptable in loader,
            # but schema recommends explicit mapping for clarity)
            if "csv_col" not in spec:
                errs.append(f"{path}:{name}: missing csv_col for single-input transform {t}")
    return errs


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("Usage: validate_feature_map.py <file1> [<file2> ...]")
        return 2
    all_errs: list[str] = []
    for p in argv[1:]:
        errs = validate_map(Path(p))
        all_errs.extend(errs)
    if all_errs:
        for e in all_errs:
            print(e)
        return 1
    print("OK: feature map(s) valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
