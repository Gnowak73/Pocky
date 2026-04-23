"""Runtime visibility sampling for WAFFLE.

This module contains only the sparse DFT visibility calculation used by WAFFLE.
Batch conversion, FITS loading, and command-line utilities live in ``Vis``.
"""

from __future__ import annotations

import numpy as np


def sample_visibilities(
    img: np.ndarray,
    u_vals: np.ndarray,
    v_vals: np.ndarray,
    pixel_arcsec: float,
    x0: float,
    y0: float,
    log_scale: bool,
    complex_mode: bool,
    normalize: bool,
    remove_dc: bool,
) -> np.ndarray:
    img = np.asarray(img, dtype=float)
    img = np.squeeze(img)
    if img.ndim != 2:
        raise ValueError(f"Expected 2D image, got shape {img.shape}")
    img = np.nan_to_num(img, nan=0.0, posinf=0.0, neginf=0.0)
    ny, nx = img.shape
    if ny == 0 or nx == 0:
        raise ValueError(f"Invalid image shape {img.shape}")
    if normalize:
        total = float(img.sum())
        if total != 0.0:
            img = img / total
    x = (np.arange(nx) - (nx - 1) / 2.0) * pixel_arcsec
    y = (np.arange(ny) - (ny - 1) / 2.0) * pixel_arcsec
    ex = np.exp(2j * np.pi * (u_vals[:, None] * (x[None, :] - x0)))
    ey = np.exp(2j * np.pi * (v_vals[:, None] * (y[None, :] - y0)))
    # V(u,v) = sum_y sum_x I(y,x) * exp(2pi i (u(x-x0)+v(y-y0))) * dx*dy
    vuv = (ex @ img.T @ ey.T).T * (pixel_arcsec * pixel_arcsec)  # (Nv, Nu)
    vuv = vuv.T  # (Nu, Nv)
    if remove_dc:
        iu0 = int(np.argmin(np.abs(u_vals)))
        iv0 = int(np.argmin(np.abs(v_vals)))
        vuv[iu0, iv0] = 0.0 + 0.0j
    if complex_mode:
        return vuv
    mag = np.abs(vuv)
    if log_scale:
        mag = np.log1p(mag)
    return mag

__all__ = ["sample_visibilities"]
