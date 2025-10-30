"""
Build Analytics Dashboard from scratch with proper Infinity datasource configuration.
"""
import json
from pathlib import Path

BASE_URL = "http://127.0.0.1:9500/api/live_csv"

def _build_exclude_by_keep_fields(keep_fields):
    """Build excludeByName dict - keep only specified fields, exclude everything else."""
    # Always exclude time variants
    exclude = {
        "time_str": True,
        "time": True,
        "time_epoch_s": True
    }
    
    if not keep_fields:
        # No specific keep_fields - just exclude time variants
        return exclude
    
    # All possible data fields
    all_fields = [
        "ce", "pe", "tp", "avg_tp", "index_price",
        "ce_iv", "pe_iv", 
        "ce_delta", "pe_delta",
        "ce_theta", "pe_theta",
        "ce_vega", "pe_vega",
        "ce_gamma", "pe_gamma",
        "ce_rho", "pe_rho"
    ]
    
    # Exclude all fields not in keep_fields
    for field in all_fields:
        if field not in keep_fields:
            exclude[field] = True
    
    return exclude

def create_target(ref_id, index, expiry_var, include_params=None):
    """Create a properly configured Infinity datasource target - matching overlays pattern.
    
    Args:
        include_params: Additional query parameters (e.g., "include_iv=true&include_greeks=true")
    """
    base_url = f"{BASE_URL}?index={index}&expiry_tag=${expiry_var}&offset=$offset"
    if include_params:
        base_url += f"&{include_params}"
    
    return {
        "datasource": {
            "type": "yesoreyeram-infinity-datasource",
            "uid": "INFINITY"
        },
        "format": "table",
        "parser": "backend",
        "refId": ref_id,
        "source": "url",
        "type": "json",
        "url": base_url,
        "url_options": {
            "method": "GET"
        }
    }

def create_timeseries_panel(panel_id, title, grid_pos, targets, overrides=None, keep_fields=None):
    """Create a timeseries panel with proper transformations.
    
    Args:
        keep_fields: List of field names to keep. If None, keeps all fields except time variants.
    """
    panel = {
        "datasource": {
            "type": "yesoreyeram-infinity-datasource",
            "uid": "INFINITY"
        },
        "fieldConfig": {
            "defaults": {
                "color": {"mode": "palette-classic"},
                "custom": {
                    "axisBorderShow": False,
                    "axisCenteredZero": False,
                    "axisColorMode": "text",
                    "axisLabel": "",
                    "axisPlacement": "auto",
                    "barAlignment": 0,
                    "drawStyle": "line",
                    "fillOpacity": 0,
                    "gradientMode": "none",
                    "hideFrom": {"legend": False, "tooltip": False, "viz": False},
                    "insertNulls": False,
                    "lineInterpolation": "linear",
                    "lineWidth": 2,
                    "pointSize": 5,
                    "scaleDistribution": {"type": "linear"},
                    "showPoints": "never",
                    "spanNulls": False,
                    "stacking": {"group": "A", "mode": "none"},
                    "thresholdsStyle": {"mode": "off"}
                },
                "mappings": [],
                "thresholds": {
                    "mode": "absolute",
                    "steps": [
                        {"color": "green", "value": None},
                        {"color": "red", "value": 80}
                    ]
                },
                "unit": "short"
            },
            "overrides": overrides or []
        },
        "gridPos": grid_pos,
        "id": panel_id,
        "options": {
            "legend": {
                "calcs": [],
                "displayMode": "list",
                "placement": "bottom",
                "showLegend": True
            },
            "tooltip": {
                "mode": "multi",
                "sort": "none"
            }
        },
        "targets": targets,
        "title": title,
        "transformations": [
            {
                "id": "convertFieldType",
                "options": {
                    "conversions": [
                        {
                            "dateFormat": "epoch_ms",
                            "destinationType": "time",
                            "targetField": "ts"
                        }
                    ]
                }
            },
            {
                "id": "organize",
                "options": {
                    "excludeByName": _build_exclude_by_keep_fields(keep_fields),
                    "indexByName": {},
                    "renameByName": {}
                }
            },
            {
                "id": "prepareTimeSeries",
                "options": {
                    "format": "multi"
                }
            }
        ],
        "type": "timeseries"
    }
    return panel

def create_row_panel(panel_id, title, y_pos):
    """Create a row panel."""
    return {
        "collapsed": False,
        "gridPos": {"h": 1, "w": 24, "x": 0, "y": y_pos},
        "id": panel_id,
        "panels": [],
        "title": title,
        "type": "row"
    }

def main():
    # Load base structure
    base_path = Path(r"c:\GrafanaData\dashboards_live\analytics_base.json")
    with open(base_path, 'r', encoding='utf-8-sig') as f:
        dashboard = json.load(f)
    
    panels = []
    panel_id = 1
    y_pos = 0
    
    # Row 1: Index Prices
    panels.append(create_row_panel(panel_id, "Index prices", y_pos))
    panel_id += 1
    y_pos += 1
    
    # Panel: NS Index Price
    targets = [
        create_target("NS1", "NIFTY", "expiry_ns"),
        create_target("NS2", "SENSEX", "expiry_ns")
    ]
    overrides = [
        {
            "matcher": {"id": "byFrameRefID", "options": "NS2"},
            "properties": [
                {"id": "custom.axisPlacement", "value": "right"},
                {"id": "custom.axisLabel", "value": "SENSEX"}
            ]
        }
    ]
    panels.append(create_timeseries_panel(
        panel_id,
        "NIFTY + SENSEX – Index Price",
        {"h": 8, "w": 12, "x": 0, "y": y_pos},
        targets,
        overrides=overrides,
        keep_fields=["index_price"]
    ))
    panel_id += 1
    
    # Panel: BF Index Price
    targets = [
        create_target("BF1", "BANKNIFTY", "expiry_bf"),
        create_target("BF2", "FINNIFTY", "expiry_bf")
    ]
    overrides = [
        {
            "matcher": {"id": "byFrameRefID", "options": "BF2"},
            "properties": [
                {"id": "custom.axisPlacement", "value": "right"},
                {"id": "custom.axisLabel", "value": "FINNIFTY"}
            ]
        }
    ]
    panels.append(create_timeseries_panel(
        panel_id,
        "BANKNIFTY + FINNIFTY – Index Price",
        {"h": 8, "w": 12, "x": 12, "y": y_pos},
        targets,
        overrides=overrides,
        keep_fields=["index_price"]
    ))
    panel_id += 1
    y_pos += 8
    
    # Row 2: Implied Volatility
    panels.append(create_row_panel(panel_id, "Implied Volatility (IV)", y_pos))
    panel_id += 1
    y_pos += 1
    
    # Panel: NS IV
    targets = [
        create_target("A", "NIFTY", "expiry_ns", include_params="include_iv=true"),
        create_target("B", "SENSEX", "expiry_ns", include_params="include_iv=true")
    ]
    overrides = [
        {
            "matcher": {"id": "byFrameRefID", "options": "B"},
            "properties": [
                {"id": "custom.axisPlacement", "value": "right"},
                {"id": "custom.axisLabel", "value": "SENSEX IV"}
            ]
        }
    ]
    panels.append(create_timeseries_panel(
        panel_id,
        "NIFTY + SENSEX | $expiry_ns | $offset – IV (CE/PE)",
        {"h": 8, "w": 12, "x": 0, "y": y_pos},
        targets,
        overrides=overrides,
        keep_fields=["ce_iv", "pe_iv"]
    ))
    panel_id += 1
    
    # Panel: BF IV
    targets = [
        create_target("C", "BANKNIFTY", "expiry_bf", include_params="include_iv=true"),
        create_target("D", "FINNIFTY", "expiry_bf", include_params="include_iv=true")
    ]
    overrides = [
        {
            "matcher": {"id": "byFrameRefID", "options": "D"},
            "properties": [
                {"id": "custom.axisPlacement", "value": "right"},
                {"id": "custom.axisLabel", "value": "FINNIFTY IV"}
            ]
        }
    ]
    panels.append(create_timeseries_panel(
        panel_id,
        "BANKNIFTY + FINNIFTY | $expiry_bf | $offset – IV (CE/PE)",
        {"h": 8, "w": 12, "x": 12, "y": y_pos},
        targets,
        overrides=overrides,
        keep_fields=["ce_iv", "pe_iv"]
    ))
    panel_id += 1
    y_pos += 8
    
    # Row 3: Greeks – NS pair
    panels.append(create_row_panel(panel_id, "Greeks – NS pair", y_pos))
    panel_id += 1
    y_pos += 1
    
    # Greeks for NS: Delta, Theta, Vega, Gamma, Rho
    greeks = ["delta", "theta", "vega", "gamma", "rho"]
    greek_configs = [
        ("delta", 12, 0),  # Full width for first two
        ("theta", 12, 12),
        ("vega", 8, 0),    # Three panels on next row
        ("gamma", 8, 8),
        ("rho", 8, 16)
    ]
    
    for i, (greek, w, x) in enumerate(greek_configs):
        targets = [
            create_target(f"A{i+1}", "NIFTY", "expiry_ns", include_params="include_greeks=true"),
            create_target(f"B{i+1}", "SENSEX", "expiry_ns", include_params="include_greeks=true")
        ]
        
        # For Delta, Gamma, Rho: separate Y-axis by instrument type (CE left, PE right)
        # For Theta, Vega: keep index-based separation (NIFTY left, SENSEX right)
        if greek in ["delta", "gamma", "rho"]:
            overrides = [
                {
                    "matcher": {"id": "byName", "options": f"pe_{greek}"},
                    "properties": [
                        {"id": "custom.axisPlacement", "value": "right"},
                        {"id": "custom.axisLabel", "value": f"PE {greek.title()}"}
                    ]
                }
            ]
        else:
            overrides = [
                {
                    "matcher": {"id": "byFrameRefID", "options": f"B{i+1}"},
                    "properties": [
                        {"id": "custom.axisPlacement", "value": "right"},
                        {"id": "custom.axisLabel", "value": f"SENSEX {greek.title()}"}
                    ]
                }
            ]
        
        if i == 2:  # Start new row after theta
            y_pos += 6
        
        h = 6
        panels.append(create_timeseries_panel(
            panel_id,
            f"NIFTY + SENSEX | $expiry_ns | $offset – {greek.title()} (CE/PE)",
            {"h": h, "w": w, "x": x, "y": y_pos},
            targets,
            overrides=overrides,
            keep_fields=[f"ce_{greek}", f"pe_{greek}"]
        ))
        panel_id += 1
    
    y_pos += 6
    
    # Row 4: Greeks – BF pair
    panels.append(create_row_panel(panel_id, "Greeks – BF pair", y_pos))
    panel_id += 1
    y_pos += 1
    
    # Greeks for BF: Delta, Theta, Vega, Gamma, Rho
    for i, (greek, w, x) in enumerate(greek_configs):
        targets = [
            create_target(f"C{i+1}", "BANKNIFTY", "expiry_bf", include_params="include_greeks=true"),
            create_target(f"D{i+1}", "FINNIFTY", "expiry_bf", include_params="include_greeks=true")
        ]
        
        # For Delta, Gamma, Rho: separate Y-axis by instrument type (CE left, PE right)
        # For Theta, Vega: keep index-based separation (BANKNIFTY left, FINNIFTY right)
        if greek in ["delta", "gamma", "rho"]:
            overrides = [
                {
                    "matcher": {"id": "byName", "options": f"pe_{greek}"},
                    "properties": [
                        {"id": "custom.axisPlacement", "value": "right"},
                        {"id": "custom.axisLabel", "value": f"PE {greek.title()}"}
                    ]
                }
            ]
        else:
            overrides = [
                {
                    "matcher": {"id": "byFrameRefID", "options": f"D{i+1}"},
                    "properties": [
                        {"id": "custom.axisPlacement", "value": "right"},
                        {"id": "custom.axisLabel", "value": f"FINNIFTY {greek.title()}"}
                    ]
                }
            ]
        
        if i == 2:  # Start new row after theta
            y_pos += 6
        
        h = 6
        panels.append(create_timeseries_panel(
            panel_id,
            f"BANKNIFTY + FINNIFTY | $expiry_bf | $offset – {greek.title()} (CE/PE)",
            {"h": h, "w": w, "x": x, "y": y_pos},
            targets,
            overrides=overrides,
            keep_fields=[f"ce_{greek}", f"pe_{greek}"]
        ))
        panel_id += 1
    
    # Set panels
    dashboard["panels"] = panels
    
    # Save dashboard
    output_path = Path(r"c:\GrafanaData\dashboards_live\analytics.json")
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(dashboard, f, indent=2)
    
    print(f"✅ Created analytics dashboard with {len(panels)} panels")
    print(f"   - Index prices: 2 panels")
    print(f"   - IV charts: 2 panels")
    print(f"   - NS Greeks: 5 panels")
    print(f"   - BF Greeks: 5 panels")
    print(f"   - Total data panels: {len([p for p in panels if p['type'] != 'row'])}")
    print(f"\n📁 Saved to: {output_path}")

if __name__ == "__main__":
    main()
