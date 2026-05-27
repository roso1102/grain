import math
from typing import Any, List


def normalize_similarity(value: Any, default: float = 0.0) -> float:
    """
    Sanitizes a similarity value returned by pgvector RPC.

    pgvector can return NaN when query and/or stored vectors are all-zero,
    and Supabase serialises NaN as the *string* ``"NaN"``.  Feeding that
    string into a Python format-code like ``:.2f`` raises a
    ``ValueError``.

    This helper converts ``"NaN"`` (and any other non-float) back to a
    safe default, then clamps the result to ``[0.0, 1.0]``.
    """
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    if math.isnan(v) or math.isinf(v):
        return default
    return max(0.0, min(1.0, v))


def cosine_similarity(v1: List[float], v2: List[float]) -> float:
    """
    Computes the cosine similarity between two float vectors.
    """
    if not v1 or not v2 or len(v1) != len(v2):
        return 0.0
        
    dot_prod = sum(a * b for a, b in zip(v1, v2))
    norm_a = math.sqrt(sum(a * a for a in v1))
    norm_b = math.sqrt(sum(b * b for b in v2))
    
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
        
    return dot_prod / (norm_a * norm_b)
