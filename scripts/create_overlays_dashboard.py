#!/usr/bin/env python3
"""Create expanded Overlays dashboard with all indices"""

import json

def create_panel(index, expiry_var, y_pos):
    """Create a panel for a specific index"""
    return {
        "type": "timeseries",
        "title": f"{index} | ${expiry_var} | Offset: $offset",
        "gridPos": {"h": 12, "w": 24, "x": 0, "y": y_pos},
        "datasource": {
            "type": "yesoreyeram-infinity-datasource",
            "uid": "INFINITY"
        },
        "options": {
            "legend": {
                "showLegend": True,
                "placement": "bottom",
                "displayMode": "list"
            },
            "tooltip": {
                "mode": "multi",
                "sort": "none"
            }
        },
        "fieldConfig": {
            "defaults": {
                "unit": "short",
                "custom": {
                    "lineWidth": 2,
                    "fillOpacity": 0,
                    "showPoints": "never",
                    "axisPlacement": "auto"
                }
            },
            "overrides": [
                {
                    "matcher": {
                        "id": "byRegexp",
                        "options": ".*index_price"
                    },
                    "properties": [
                        {
                            "id": "custom.axisPlacement",
                            "value": "left"
                        },
                        {
                            "id": "custom.axisLabel",
                            "value": "Index"
                        },
                        {
                            "id": "custom.axisSoftMin",
                            "value": 0
                        },
                        {
                            "id": "custom.lineWidth",
                            "value": 1
                        },
                        {
                            "id": "custom.lineStyle",
                            "value": {
                                "dash": [10, 10],
                                "fill": "dash"
                            }
                        },
                        {
                            "id": "color",
                            "value": {
                                "mode": "fixed",
                                "fixedColor": "semi-dark-orange"
                            }
                        }
                    ]
                },
                {
                    "matcher": {
                        "id": "byRegexp",
                        "options": ".*avg_tp.*"
                    },
                    "properties": [
                        {
                            "id": "custom.axisPlacement",
                            "value": "right"
                        },
                        {
                            "id": "custom.lineWidth",
                            "value": 2
                        },
                        {
                            "id": "custom.fillOpacity",
                            "value": 0
                        },
                        {
                            "id": "standard.color.mode",
                            "value": "fixed"
                        }
                    ]
                },
                {
                    "matcher": {
                        "id": "byRegexp",
                        "options": ".*(tp|TP).*"
                    },
                    "properties": [
                        {
                            "id": "custom.axisPlacement",
                            "value": "right"
                        },
                        {
                            "id": "custom.axisLabel",
                            "value": "Premium"
                        }
                    ]
                }
            ]
        },
        "targets": [
            {
                "refId": "LiveCSV",
                "datasource": {
                    "type": "yesoreyeram-infinity-datasource",
                    "uid": "INFINITY"
                },
                "type": "json",
                "source": "url",
                "format": "table",
                "url": f"http://127.0.0.1:9500/api/live_csv?index={index}&expiry_tag=${expiry_var}&offset=$offset",
                "parser": "backend",
                "url_options": {
                    "method": "GET"
                }
            },
            {
                "refId": "MasterOverlay",
                "datasource": {
                    "type": "yesoreyeram-infinity-datasource",
                    "uid": "INFINITY"
                },
                "type": "json",
                "source": "url",
                "format": "table",
                "url": f"http://127.0.0.1:9500/api/overlay?index={index}&expiry_tag=${expiry_var}&offset=$offset",
                "parser": "backend",
                "url_options": {
                    "method": "GET"
                }
            }
        ],
        "transformations": [
            {
                "id": "convertFieldType",
                "options": {
                    "conversions": [
                        {
                            "targetField": "time",
                            "destinationType": "time",
                            "dateFormat": "epoch_ms"
                        }
                    ]
                }
            },
            {
                "id": "organize",
                "options": {
                    "excludeByName": {
                        "ce": True,
                        "pe": True,
                        "ts": True,
                        "time_str": True
                    },
                    "indexByName": {},
                    "renameByName": {
                        "index_price": "Index Price",
                        "tp": "TP (Live)",
                        "avg_tp": "Avg TP (Live)",
                        "tp_mean": "TP Mean (Master)",
                        "tp_ema": "TP EMA (Master)",
                        "avg_tp_mean": "Avg TP Mean (Master)",
                        "avg_tp_ema": "Avg TP EMA (Master)"
                    }
                }
            },
            {
                "id": "prepareTimeSeries",
                "options": {
                    "format": "multi"
                }
            }
        ]
    }

dashboard = {
    "uid": "g6-overlays",
    "title": "Overlays - All Indices",
    "editable": True,
    "schemaVersion": 39,
    "refresh": "15s",
    "tags": ["g6", "overlay", "live", "master"],
    "time": {"from": "now-12h", "to": "now"},
    "timezone": "Asia/Kolkata",
    "templating": {
        "list": [
            {
                "name": "offset",
                "type": "custom",
                "label": "Offset",
                "query": "0,100,-100,200,-200,300,-300",
                "current": {"text": "0", "value": "0"},
                "multi": False,
                "includeAll": False
            },
            {
                "name": "expiry_ns",
                "type": "custom",
                "label": "Expiry (NIFTY/SENSEX)",
                "query": "this_week,next_week,this_month,next_month",
                "current": {"text": "this_week", "value": "this_week"},
                "multi": False,
                "includeAll": False
            },
            {
                "name": "expiry_bf",
                "type": "custom",
                "label": "Expiry (BANKNIFTY/FINNIFTY)",
                "query": "this_month,next_month",
                "current": {"text": "this_month", "value": "this_month"},
                "multi": False,
                "includeAll": False
            }
        ]
    },
    "panels": [
        create_panel("NIFTY", "expiry_ns", 0),
        create_panel("SENSEX", "expiry_ns", 12),
        create_panel("BANKNIFTY", "expiry_bf", 24),
        create_panel("FINNIFTY", "expiry_bf", 36)
    ],
    "timepicker": {
        "refresh_intervals": ["15s", "30s", "1m", "2m", "5m"]
    }
}

# Write to file
output_path = r"C:\GrafanaData\dashboards_live\overlays.json"
with open(output_path, 'w', encoding='utf-8') as f:
    json.dump(dashboard, f, indent=2)

print(f"[OK] Dashboard created: {output_path}")
print("Panels:")
for panel in dashboard["panels"]:
    print(f"  - {panel['title']}")
print(f"\nVariables: offset, expiry_ns, expiry_bf")
