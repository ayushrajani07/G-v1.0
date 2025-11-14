from tests.test_ann_guard_helper import test_guard_triggers_and_falls_back, test_guard_noop_when_below_threshold
from tests.test_ann_auto_tune_candidates import test_pick_prefers_smallest_meeting_constraints, test_pick_fallback_to_largest_when_none_valid, test_pick_per_mode_uses_mode_columns


def main():
    test_guard_triggers_and_falls_back()
    test_guard_noop_when_below_threshold()
    test_pick_prefers_smallest_meeting_constraints()
    test_pick_fallback_to_largest_when_none_valid()
    test_pick_per_mode_uses_mode_columns()
    print('ALL_SMOKE_TESTS_OK')

if __name__ == '__main__':
    main()
