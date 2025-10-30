import json, urllib.request

URL='http://127.0.0.1:3002/api/ds/query'

# Probe payload for Grafana Infinity using camelCase options and explicit columns mapping
PAYLOAD={
  "queries":[{
    "refId":"A",
    "datasource":{"type":"yesoreyeram-infinity-datasource","uid":"INFINITY"},
    "type":"json",
    "queryType":"json",
    "source":"url",
    "url":"http://127.0.0.1:9500/api/live_csv?index=NIFTY&expiry_tag=this_week&offset=0",
    "method":"GET",
    "format":"timeseries",
    # Root is a JSON array of objects
    "jsonOptions":{"root_is_array": True},
    # Time column (epoch ms) + one numeric series
    "columns":[
      {"selector":"ts","type":"timestamp_epoch","text":"ts"},
      {"selector":"index_price","type":"number","text":"NIFTY Index"}
    ],
    # Explicit URL params
    "urlOptions": {"method":"GET","params": [
      {"key": "limit", "value": "2000"},
      {"key":"include_index","value":"1"}
    ]}
  }],
  # Optional range block (helps Grafana resolve macros if present)
  "range": {"from":"1970-01-01T00:00:00Z","to":"2099-01-01T00:00:00Z"}
}

req=urllib.request.Request(URL,data=json.dumps(PAYLOAD).encode('utf-8'),headers={'Content-Type':'application/json'})
with urllib.request.urlopen(req, timeout=20) as resp:
    body=resp.read().decode('utf-8')
print(body)
