"""Scan for remaining bare exceptions in codebase.

Quick script to identify files with bare 'except:' statements.
"""
import re
from pathlib import Path
from collections import defaultdict

def scan_bare_exceptions(root_dir='.'):
    """Scan for bare exceptions in Python files."""
    pattern = re.compile(r'^\s+except:\s*$', re.MULTILINE)
    
    results = defaultdict(int)
    files_with_bare = []
    
    root = Path(root_dir)
    exclude_dirs = {'.venv', 'venv', '__pycache__', 'node_modules', '.git'}
    
    for py_file in root.rglob('*.py'):
        # Skip excluded directories
        if any(excluded in py_file.parts for excluded in exclude_dirs):
            continue
        
        try:
            content = py_file.read_text(encoding='utf-8', errors='ignore')
            matches = pattern.findall(content)
            
            if matches:
                count = len(matches)
                category = str(py_file.parts[0]) if len(py_file.parts) > 0 else 'root'
                results[category] += count
                files_with_bare.append((py_file, count))
        except Exception as e:
            print(f"Warning: Could not read {py_file}: {e}")
    
    return results, files_with_bare

if __name__ == '__main__':
    print("=" * 80)
    print("BARE EXCEPTION SCAN")
    print("=" * 80)
    
    results, files = scan_bare_exceptions()
    
    total = sum(results.values())
    
    print(f"\nTotal bare exceptions: {total}")
    print(f"\nBy directory:")
    for category, count in sorted(results.items(), key=lambda x: x[1], reverse=True):
        print(f"  {category}: {count}")
    
    if files:
        print(f"\nFiles with bare exceptions ({len(files)} files):")
        for file_path, count in sorted(files, key=lambda x: x[1], reverse=True)[:20]:
            print(f"  {count:4d} - {file_path}")
        
        if len(files) > 20:
            print(f"  ... and {len(files) - 20} more files")
    else:
        print("\n✅ No bare exceptions found in codebase!")
    
    # Active codebase summary
    active_count = results.get('src', 0) + results.get('scripts', 0)
    print(f"\n{'='*80}")
    print(f"Active Codebase (src + scripts): {active_count} bare exceptions")
    print(f"{'='*80}")
