import sys, urllib.parse, urllib.request, json

def probe(port: int, now_ms: int):
    base = f'http://127.0.0.1:{port}'
    params = {
        'index':'NIFTY','expiry_tag':'this_week','offset':'0',
        'window':'60','k':'15','mode':'auto','bucket_ms':'60000',
        'calibrate':'false','no_cache':'true','date_str':'2025-11-04',
        'horizon_minutes':'60','now_override_ms':str(now_ms)
    }
    url = f"{base}/api/ml/path_forecast_json?{urllib.parse.urlencode(params)}"
    try:
        with urllib.request.urlopen(url, timeout=6) as resp:
            print('port', port, 'status', getattr(resp, 'status', 0))
            print('X-Gen-Ms', resp.getheader('X-Gen-Ms'))
            print('X-Gen-Iso', resp.getheader('X-Gen-Iso'))
            print('X-Override-Requested', resp.getheader('X-Override-Requested'))
            print('X-Query-Now-Keys', resp.getheader('X-Query-Now-Keys'))
            data = resp.read().decode('utf-8', errors='replace')
            try:
                arr = json.loads(data)
                print('len', len(arr), 'first', (arr[0].get('time') if arr else None))
            except Exception:
                print('data_head', data[:200])
    except Exception as e:
        print('port', port, 'error', e)

if __name__ == '__main__':
    now = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    for p in (9500, 8003):
        probe(p, now)
