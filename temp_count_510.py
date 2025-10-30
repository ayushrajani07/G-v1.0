from pathlib import Path
import re

p = Path('src')
pattern = re.compile(r'^\s+from src\.', re.MULTILINE)

results = {}
for f in p.rglob('*.py'):
    if f.is_file():
        try:
            content = f.read_text(encoding='utf-8', errors='ignore')
            count = len(pattern.findall(content))
            if count > 0:
                results[str(f)] = count
        except:
            pass

total = sum(results.values())
eliminated = 539 - total

print(f"Total late imports: {total}")
print(f"Eliminated: {eliminated} of 539 ({eliminated/539*100:.1f}%)")
print(f"\nFiles with 5-10 imports ({len([k for k, v in results.items() if 5 <= v <= 10])} files):")

five_to_ten = sorted([(v, k) for k, v in results.items() if 5 <= v <= 10], reverse=True)
for count, path in five_to_ten:
    print(f"  {count} - {path}")
