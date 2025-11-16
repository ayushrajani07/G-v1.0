"""Comprehensive test fixer for remaining API signature issues.

Fixes:
1. run_unified_collectors() with both positional influx and keyword metrics
2. Other common API mismatches
"""
import re
from pathlib import Path
import subprocess

def fix_run_unified_collectors_calls(content):
    """Fix run_unified_collectors calls with influx positional + metrics keyword."""
    # Pattern: run_unified_collectors(params, prov, csv, influx, metrics=metrics, ...)
    pattern = r'run_unified_collectors\(([^,]+),\s*([^,]+),\s*([^,]+),\s*([^,]+),\s*metrics='
    replacement = r'run_unified_collectors(\1, \2, \3, metrics='
    
    new_content = re.sub(pattern, replacement, content)
    return new_content != content, new_content

def fix_test_file(file_path):
    """Apply all fixes to a test file."""
    content = file_path.read_text(encoding='utf-8')
    original = content
    
    changed, content = fix_run_unified_collectors_calls(content)
    
    if content != original:
        return True, content
    return False, original

def main():
    print("=" * 80)
    print("COMPREHENSIVE TEST API FIXER")
    print("=" * 80)
    
    test_dir = Path('tests')
    fixed_files = []
    
    for test_file in test_dir.rglob('*.py'):
        try:
            changed, new_content = fix_test_file(test_file)
            
            if changed:
                test_file.write_text(new_content, encoding='utf-8')
                print(f"✓ Fixed: {test_file.relative_to('.')}")
                fixed_files.append(str(test_file.relative_to('.')))
        except Exception as e:
            print(f"✗ Error in {test_file}: {e}")
    
    print(f"\n{'='*80}")
    print(f"Fixed {len(fixed_files)} files")
    print(f"{'='*80}")
    
    if fixed_files:
        print("\nFixed files:")
        for f in fixed_files[:20]:
            print(f"  - {f}")
        if len(fixed_files) > 20:
            print(f"  ... and {len(fixed_files) - 20} more")

if __name__ == '__main__':
    main()
