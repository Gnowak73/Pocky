#!/usr/bin/env python3
"""Generate the paper's sparse (u,v) grid values."""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Generate paper-style sqrt(|u|) grid values.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--grid-size", type=int, default=39, choices=[21, 39], help="Grid size per axis.")
    p.add_argument("--output", default="uv_grid.npz", help="Output .npz path.")
    return p.parse_args()


def paper_grid_vals(size: int) -> np.ndarray:
    base = [0.0] + [i / 10.0 for i in range(1, 11)]
    if size == 39:
        base += [i / 100.0 for i in range(15, 100, 10)]
    base = sorted(set(base))
    pos = np.array(base, dtype=float)
    neg = -pos[1:][::-1]
    return np.concatenate([neg, pos])


def uv_grid(size: int) -> tuple[np.ndarray, np.ndarray]:
    sqrt_vals = paper_grid_vals(size)
    u_vals = np.sign(sqrt_vals) * (np.abs(sqrt_vals) ** 2)
    v_vals = u_vals.copy()
    return u_vals, v_vals


def main() -> int:
    args = parse_args()
    u_vals, v_vals = uv_grid(args.grid_size)
    out = Path(args.output)
    np.savez_compressed(out, u_vals=u_vals, v_vals=v_vals)
    print(f"Saved {out} (len={len(u_vals)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
