from tests.test_ann_auto_tune_candidates import (
    test_pick_prefers_smallest_meeting_constraints,
    test_pick_fallback_to_largest_when_none_valid,
)

def main():
    test_pick_prefers_smallest_meeting_constraints()
    test_pick_fallback_to_largest_when_none_valid()
    print('OK')

if __name__ == '__main__':
    main()
