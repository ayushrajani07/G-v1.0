import sys
sys.path.insert(0, r'c:\Users\Asus\Desktop\g6_reorganized')
from src.metrics.generated import m_metrics_spec_hash_info, m_metric_duplicates_total_labels
from src.metrics.cardinality_guard import registry_guard, _rg_metrics

m = m_metrics_spec_hash_info()
print('metric exists:', m is not None)
print('in _rg_metrics:', 'g6_metrics_spec_hash_info' in _rg_metrics, 'keys=', len(_rg_metrics))
# read before
c = m_metric_duplicates_total_labels('g6_metrics_spec_hash_info')
print('dup child exists:', c is not None)
print('child type:', type(c))
print('has inc:', hasattr(c, 'inc'))
val_before = None
if c is not None:
    try:
        val_before = c._value.get()
    except Exception as e:
        print('before read err:', e)
print('before:', val_before)
# duplicate register
r = registry_guard._register('gauge','g6_metrics_spec_hash_info','dup test',[],1)
print('register returned existing?', r is m)
# manual inc for sanity
if c is not None:
    try:
        c.inc()
        v_after_manual = c._value.get()
        print('after manual inc:', v_after_manual)
    except Exception as e:
        print('manual inc error:', e)
# read after
c2 = m_metric_duplicates_total_labels('g6_metrics_spec_hash_info')
val_after = None
if c2 is not None:
    try:
        val_after = c2._value.get()
    except Exception as e:
        print('after read err:', e)
print('after:', val_after, 'same child object?', c2 is c)
