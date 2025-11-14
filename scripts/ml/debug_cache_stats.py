import urllib.request, urllib.parse, json, sys
base = sys.argv[1] if len(sys.argv)>1 else 'http://127.0.0.1:9500'
prefix = sys.argv[2] if len(sys.argv)>2 else 'json|'
url = f"{base.rstrip('/')}/api/ml/_debug/cache_stats?prefix={urllib.parse.quote(prefix)}&detail=true"
try:
    with urllib.request.urlopen(url, timeout=6) as r:
        data = r.read().decode('utf-8')
        print(data)
except Exception as e:
    print({'error': str(e)})
