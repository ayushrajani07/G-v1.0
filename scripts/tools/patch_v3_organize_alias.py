import json
import re
from pathlib import Path


V3_PATH = Path("grafana/dashboards/generated/analytics_infinity_v3.json")
BACKUP_PATH = V3_PATH.with_suffix(".pre_organize_alias.bak.json")


def extract_index_from_url(url: str) -> str:
    m = re.search(r"index=([^&]+)", url)
    return m.group(1) if m else ""


def ensure_json_options(target: dict) -> None:
    # Normalize to snake_case key that the plugin echoes back
    jo = target.get("json_options") or {}
    if not isinstance(jo, dict):
        jo = {}
    # root_is_not_array = False means the root IS an array
    jo["root_is_not_array"] = False
    target["json_options"] = jo
    # Remove camelCase duplicate to avoid confusion
    target.pop("jsonOptions", None)


def ensure_alias_for_index_price(panel: dict) -> None:
    for t in panel.get("targets", []):
        url = t.get("url", "")
        idx = extract_index_from_url(url)
        if idx:
            t["alias"] = f"{idx} Index"


def ensure_transform_pipeline(panel: dict, keep_fields: list[str]) -> None:
    xf = panel.get("transformations", [])
    # Convert time_str -> time
    have_convert = any(x.get("id") == "convertFieldType" for x in xf)
    if not have_convert:
        xf.insert(0, {
            "id": "convertFieldType",
            "options": {"conversions": [{"targetField": "time_str", "destinationType": "time"}]}
        })
    # Organize fields: pick only the ones we need
    # If an organize already exists, replace its indexByName include list
    org = next((x for x in xf if x.get("id") == "organize"), None)
    organize_options = {
        "excludeByName": {},
        "indexByName": {name: 0 for name in keep_fields},
        "includeByName": {name: True for name in keep_fields},
        "renameByName": {},
    }
    if org:
        org["options"] = organize_options
    else:
        # Insert organize right after convertFieldType
        insert_pos = 1 if xf and xf[0].get("id") == "convertFieldType" else 0
        xf.insert(insert_pos, {"id": "organize", "options": organize_options})

    # Prepare Time Series at the end
    have_prepare = any(x.get("id") == "prepareTimeSeries" for x in xf)
    if not have_prepare:
        xf.append({"id": "prepareTimeSeries", "options": {"timeField": "time_str"}})
    else:
        for x in xf:
            if x.get("id") == "prepareTimeSeries":
                x["options"] = {"timeField": "time_str"}
                break

    panel["transformations"] = xf


def main() -> None:
    data = json.loads(V3_PATH.read_text(encoding="utf-8"))
    BACKUP_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")

    for panel in data.get("panels", []):
        # Normalize json_options for all targets
        for t in panel.get("targets", []):
            ensure_json_options(t)

        title = panel.get("title", "").lower()
        if "index price" in title:
            # Keep only time + index_price
            ensure_alias_for_index_price(panel)
            ensure_transform_pipeline(panel, ["time_str", "index_price"])
        elif " iv " in f" {title} ":  # crude contains check around ' iv '
            ensure_transform_pipeline(panel, ["time_str", "ce_iv", "pe_iv"])
        elif "delta" in title:
            ensure_transform_pipeline(panel, ["time_str", "ce_delta", "pe_delta"])
        elif "gamma" in title:
            ensure_transform_pipeline(panel, ["time_str", "ce_gamma", "pe_gamma"])
        elif "theta" in title:
            ensure_transform_pipeline(panel, ["time_str", "ce_theta", "pe_theta"])
        elif "vega" in title:
            ensure_transform_pipeline(panel, ["time_str", "ce_vega", "pe_vega"])
        elif "rho" in title:
            ensure_transform_pipeline(panel, ["time_str", "ce_rho", "pe_rho"])

    V3_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"Patched: {V3_PATH} (backup at {BACKUP_PATH})")


if __name__ == "__main__":
    main()
