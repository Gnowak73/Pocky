Event-sequence CNN+GRU (early-warning) overview

Goal
Predict whether a C5+ flare starts within the next 5 minutes using only
pre-flare visibility sequences. This is an early-warning time-series
problem, not a random window classifier.

Data
Inputs are visibility tensors cached per event:
  vis shape: (T_frames, C, Nv, Nu)
  C = wavelengths (94,131,171,193,211)
  Nv=Nu=39 (paper grid)

Indexing uses sliding windows:
  window length = 15 minutes
  stride = 1 minute
  label y(t) = 1 if flare start t0 is in (t, t+5]
  preflare-only = t <= t0 (avoid leakage)

Model
Two-stage temporal model that respects sequence structure:

1) Window encoder
   - For each window, CNN encodes each frame (u,v map) into a feature vector.
   - A GRU runs across frames inside that window to produce a single window embedding.

2) Event sequence model
   - A second GRU runs across window embeddings in chronological order.
   - Output is a probability at each window end time.

This forces the model to learn the temporal build-up rather than a single
static snapshot, which helps reduce the all-positive/all-negative collapse.

Why this helps
Random window training breaks temporal context and makes the model unstable.
Event-sequence training preserves the buildup pattern and prevents leakage
across windows from the same flare.

What to trust
Only trust results when:
  - index built with --preflare-only
  - evaluation is on held-out events (not windows)
  - note: confusion metrics are currently computed per-window, even though splits are per-event

Evaluation details
- Splits are performed by EVENT (train/val/test), so windows from the same event do not mix.
- Metrics/confusion matrix are computed per WINDOW by default.
- If you want event-level metrics, aggregate window predictions (e.g., last window or max).

Commands (typical)
  python ML_FFT/cache_vis_events.py
  python ML_FFT/build_vis_index.py --preflare-only --min-class C5.0
  python ML_FFT/train_vis_cnn_gru.py --device mps
