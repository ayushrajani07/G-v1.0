"""Fix remaining test failures systematically.

This script identifies and fixes common patterns in failing tests:
1. Remove influx_sink references
2. Fix DummyCtx and similar mock objects
3. Update API signatures
"""
import subprocess
import re
from pathlib import Path

def get_failing_tests():
    """Get list of failing test files."""
    result = subprocess.run(
        ['python', '-m', 'pytest', '--tb=no', '-q'],
        capture_output=True,
        text=True
    )
    
    failures = []
    for line in result.stdout.split('\n'):
        if line.startswith('FAILED'):
            test_path = line.split()[1].split('::')[0]
            if test_path not in failures:
                failures.append(test_path)
    
    return failures

def fix_influx_references(file_path):
    """Remove influx_sink references from test files."""
    content = file_path.read_text(encoding='utf-8')
    original = content
    
    # Pattern 1: self.influx_sink = influx_sink (undefined variable)
    content = re.sub(r'\s+self\.influx_sink\s*=\s*influx_sink\s*\n', '\n', content)
    
    # Pattern 2: influx_sink parameter in __init__ without default
    content = re.sub(
        r'def __init__\(self,\s*([^)]*?),\s*influx_sink\s*([,)])',
        r'def __init__(self, \1\2',
        content
    )
    
    # Pattern 3: influx=... assignments
    content = re.sub(r',\s*influx\s*=\s*[^,\)]+', '', content)
    
    return content != original, content

def main():
    print("=" * 80)
    print("FIXING REMAINING TEST FAILURES")
    print("=" * 80)
    
    failing_tests = get_failing_tests()
    print(f"\nFound {len(failing_tests)} failing test files")
    
    fixed_count = 0
    for test_file in failing_tests:
        file_path = Path(test_file)
        if not file_path.exists():
            continue
        
        changed, new_content = fix_influx_references(file_path)
        
        if changed:
            file_path.write_text(new_content, encoding='utf-8')
            print(f"✓ Fixed: {test_file}")
            fixed_count += 1
    
    print(f"\n{'='*80}")
    print(f"Fixed {fixed_count} test files")
    print(f"{'='*80}")
    
    # Re-run tests to check progress
    print("\nRe-running tests...")
    result = subprocess.run(
        ['python', '-m', 'pytest', '--tb=no', '-q'],
        capture_output=True,
        text=True
    )
    
    # Count results
    passed = result.stdout.count(' passed')
    failed = result.stdout.count('FAILED')
    
    print(f"\nTest Results:")
    print(f"  Passed: {passed}")
    print(f"  Failed: {failed}")

if __name__ == '__main__':
    main()
