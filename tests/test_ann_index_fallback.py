import pytest

from src.path_forecast.ann_index import AnnIndex, AnnParams, zscore_window


def test_ann_index_bruteforce_cosine():
    dim = 5
    # Simple vectors with clear nearest neighbor structure
    base = [
        [1,2,3,4,5],
        [2,4,6,8,10],  # scaled version
        [10,9,8,7,6],
        [1,1,1,1,1],
        [5,5,5,5,5],
    ]
    idx = AnnIndex(dim=dim, params=AnnParams(space="cosine"))
    idx.fit(base)
    q = [2,4,6,8,10]
    labels, dists = idx.query(q, k=2)
    # Expect the exact match (vector 1) and close scaled/related (vector 0) depending on normalization
    assert len(labels) == 2
    assert labels[0] in (1,0)
    assert all(isinstance(d, float) for d in dists)


def test_zscore_window_edge_cases():
    assert (zscore_window([])).size == 0  # empty
    single = zscore_window([42])
    assert single.shape == (1,)
    assert single[0] == 0.0  # zero variance

