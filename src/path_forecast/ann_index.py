from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

try:
    import numpy as np  # type: ignore
except Exception:  # pragma: no cover - numpy expected via pandas dep
    np = None  # type: ignore

try:
    import hnswlib  # type: ignore
    HAS_HNSWLIB = True
except Exception:  # pragma: no cover
    hnswlib = None  # type: ignore
    HAS_HNSWLIB = False


@dataclass
class AnnParams:
    space: str = "cosine"  # 'cosine' or 'l2'
    M: int = 16
    ef_construction: int = 200
    ef_search: int = 64


class AnnIndex:
    """Lightweight ANN adapter with optional hnswlib and numpy fallback.

    - If hnswlib is available, uses HNSW index.
    - Otherwise falls back to brute-force numpy distances (sufficient for tests/prototypes).
    """

    def __init__(self, dim: int, params: Optional[AnnParams] = None) -> None:
        self.dim = int(dim)
        self.params = params or AnnParams()
        self._index = None
        self._vectors = None
        self._count = 0
        if HAS_HNSWLIB:
            space = "cosine" if self.params.space == "cosine" else "l2"
            self._index = hnswlib.Index(space=space, dim=self.dim)

    def fit(self, vectors) -> None:
        if np is None:
            raise RuntimeError("AnnIndex requires numpy (available via pandas dependency)")
        X = np.asarray(vectors, dtype=np.float32)
        if X.ndim != 2 or X.shape[1] != self.dim:
            raise ValueError(f"vectors shape must be (n,{self.dim})")
        n = X.shape[0]
        if HAS_HNSWLIB and self._index is not None:
            self._index.init_index(max_elements=n, ef_construction=self.params.ef_construction, M=self.params.M)
            self._index.add_items(X)
            self._index.set_ef(self.params.ef_search)
            self._count = n
        else:
            # fallback: store vectors for brute-force search
            self._vectors = X
            self._count = n

    def query(self, vec, k: int) -> Tuple[list[int], list[float]]:
        if np is None:
            raise RuntimeError("AnnIndex requires numpy (available via pandas dependency)")
        v = np.asarray(vec, dtype=np.float32).reshape(1, -1)
        if v.shape[1] != self.dim:
            raise ValueError(f"query dim must be {self.dim}")
        k = max(1, min(int(k), self._count or 1))
        if HAS_HNSWLIB and self._index is not None:
            labels, dists = self._index.knn_query(v, k=k)
            return list(map(int, labels[0])), list(map(float, dists[0]))
        # brute force fallback
        assert self._vectors is not None, "Index not fitted"
        X = self._vectors
        if self.params.space == "cosine":
            # cosine distance = 1 - cos_sim
            xv = X
            a = v / (np.linalg.norm(v, axis=1, keepdims=True) + 1e-8)
            b = xv / (np.linalg.norm(xv, axis=1, keepdims=True) + 1e-8)
            sim = (b @ a.T).ravel()
            dist = 1.0 - sim
        else:
            diff = X - v
            dist = np.sqrt(np.sum(diff * diff, axis=1))
        order = np.argsort(dist)
        sel = order[:k]
        return list(map(int, sel)), list(map(float, dist[sel]))


def zscore_window(x):
    if np is None:
        raise RuntimeError("AnnIndex requires numpy")
    x = np.asarray(x, dtype=np.float32)
    if x.size == 0:
        return x
    m = float(np.mean(x))
    sd = float(np.std(x, ddof=1)) if x.size > 1 else 1.0
    if sd <= 0:
        return np.zeros_like(x)
    return (x - m) / sd
