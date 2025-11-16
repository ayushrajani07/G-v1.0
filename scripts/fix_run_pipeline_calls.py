"""Fix run_pipeline() calls with extra None arguments.

Pattern to fix: run_pipeline(params, providers, None, None, metrics=...) 
Should be: run_pipeline(params, providers, csv_sink=None, metrics=...)
"""
import re
from pathlib import Path

def fix_run_pipeline_calls(content):
    """Fix run_pipeline calls with double None positional args."""
    # Pattern: run_pipeline(arg1, arg2, None, None, metrics=
    pattern = r'run_pipeline\(([^,]+),\s*([^,]+),\s*None,\s*None,\s*metrics='
    replacement = r'run_pipeline(\1, \2, csv_sink=None, metrics='
    
    new_content = re.sub(pattern, replacement, content)
    return new_content != content, new_content

def main():
    print("=" * 80)
    print("FIXING run_pipeline() CALL SIGNATURES")
    print("=" * 80)
    
    test_dir = Path('tests')
    fixed_files = []
    
    for test_file in test_dir.rglob('*.py'):
        try:
            content = test_file.read_text(encoding='utf-8')
            changed, new_content = fix_run_pipeline_calls(content)
            
            if changed:
                test_file.write_text(new_content, encoding='utf-8')
                rel_path = test_file.relative_to('.')
                print(f"✓ Fixed: {rel_path}")
                fixed_files.append(str(rel_path))
        except Exception as e:
            print(f"✗ Error in {test_file}: {e}")
    
    print(f"\n{'='*80}")
    print(f"Fixed {len(fixed_files)} files")
    print(f"{'='*80}")
    
    if fixed_files:
        for f in fixed_files:
            print(f"  - {f}")

if __name__ == '__main__':
    main()
