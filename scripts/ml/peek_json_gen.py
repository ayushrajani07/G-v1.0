import urllib.parse, urllib.request, sys

base = 'http://127.0.0.1:9500'
params = {
    'index':'NIFTY','expiry_tag':'this_week','offset':'0',
    'window':'60','k':'15','mode':'auto','bucket_ms':'60000',
    'calibrate':'false','no_cache':'true','date_str':'2025-11-04',
    'horizon_minutes':'60','now_override_ms':str(sys.argv[1] if len(sys.argv)>1 else '0')
}
url = f"{base}/api/ml/path_forecast_json?{urllib.parse.urlencode(params)}"
with urllib.request.urlopen(url, timeout=10) as resp:
    print('status', getattr(resp, 'status', 0))
    print('X-Gen-Ms', resp.getheader('X-Gen-Ms'))
    print('X-Gen-Iso', resp.getheader('X-Gen-Iso'))
    print('X-Override-Requested', resp.getheader('X-Override-Requested'))
    print('X-Query-Now-Keys', resp.getheader('X-Query-Now-Keys'))
    data = resp.read().decode('utf-8')
    # print first item time
    try:
        import json
        arr = json.loads(data)
        if isinstance(arr, list) and arr:
            print('first-time', arr[0].get('time'))
    except Exception:
        pass
