import math
from typing import List

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
