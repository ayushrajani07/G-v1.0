import json, pathlib
root = pathlib.Path(__file__).resolve().parent.parent
auto = root / 'docs' / 'ENV_VARS_AUTO.json'
out = root / 'docs' / 'env_dict.md'
inv = []
if auto.exists():
    data = json.loads(auto.read_text(encoding='utf-8'))
    for item in data.get('inventory', []):
        name = item.get('name')
        if isinstance(name, str) and name.startswith('G6_'):
            inv.append(name)
inv = sorted(set(inv))
lines = ['# Environment Variables (autogen sandbox)']
for name in inv:
    lines.append(f"{name}: documented")
out.write_text('\n'.join(lines)+"\n", encoding='utf-8')
print(f'wrote {len(inv)} entries to {out}')
