from src.metrics.generated import m_metrics_spec_hash_info, m_metric_duplicates_total_labels
from src.metrics.cardinality_guard import registry_guard

m = m_metrics_spec_hash_info()
print('metric exists:', m is not None)
# read before
c = m_metric_duplicates_total_labels('g6_metrics_spec_hash_info')
print('dup child exists:', c is not None)
val_before = None
if c is not None:
    try:
        val_before = c._value.get()
    except Exception:
        pass
print('before:', val_before)
# duplicate register
registry_guard._register('gauge','g6_metrics_spec_hash_info','dup test',[],1)
# read after
c2 = m_metric_duplicates_total_labels('g6_metrics_spec_hash_info')
val_after = None
if c2 is not None:
    try:
        val_after = c2._value.get()
    except Exception:
        pass
print('after:', val_after)
print('same child object?', c2 is c)
