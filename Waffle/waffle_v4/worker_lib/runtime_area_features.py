"""Runtime EM active-area features for WAFFLE trigger guards."""

from __future__ import annotations

from typing import Dict, List, Tuple

import numpy as np


def _largest_connected_component(mask: np.ndarray) -> np.ndarray:
    h, w = mask.shape
    visited = np.zeros_like(mask, dtype=bool)
    best: List[Tuple[int, int]] = []
    for y in range(h):
        for x in range(w):
            if visited[y, x] or not mask[y, x]:
                continue
            stack = [(y, x)]
            visited[y, x] = True
            comp: List[Tuple[int, int]] = []
            while stack:
                cy, cx = stack.pop()
                comp.append((cy, cx))
                for ny in range(max(0, cy - 1), min(h - 1, cy + 1) + 1):
                    for nx in range(max(0, cx - 1), min(w - 1, cx + 1) + 1):
                        if not visited[ny, nx] and mask[ny, nx]:
                            visited[ny, nx] = True
                            stack.append((ny, nx))
            if len(comp) > len(best):
                best = comp
    out = np.zeros_like(mask, dtype=bool)
    for y, x in best:
        out[y, x] = True
    return out


def em_active_area_features(
    em_map: np.ndarray,
    active_threshold: float = 1.0e43,
) -> Dict[str, float]:
    arr = np.asarray(em_map, dtype=np.float64)
    if arr.size == 0 or not np.isfinite(arr).any():
        return {
            "em_active_area_fraction": 0.0,
            "em_largest_component_fraction": 0.0,
        }
    arr = np.where(np.isfinite(arr), arr, 0.0)
    mask = arr >= float(active_threshold)
    active_pixels = int(np.sum(mask))
    total_pixels = int(mask.size)
    if active_pixels <= 0 or total_pixels <= 0:
        return {
            "em_active_area_fraction": 0.0,
            "em_largest_component_fraction": 0.0,
        }
    largest = _largest_connected_component(mask)
    largest_pixels = int(np.sum(largest))
    return {
        "em_active_area_fraction": float(active_pixels / total_pixels),
        "em_largest_component_fraction": float(largest_pixels / total_pixels),
    }


__all__ = ["em_active_area_features"]
