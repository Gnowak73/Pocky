TUI package layout and why
==========================

Purpose: capture the conceptual split so future changes stay consistent.

Top-level rule
--------------
- `core` owns the Bubble Tea loop: model, Init/Update/View, mode routing, and all state mutation in response to tea messages.
- Other packages define narrow state structs and helpers for their domain, but do not route tea messages or change modes themselves.

Packages
--------
- `config`: reads/writes `.vars.env` and provides `ParentDirFile` to find repo-level assets from the built binary path. IO only, no UI.
- `theme`: shared math/styling helpers (clamp, gradients) used by multiple packages. No state.
- `chrome`: pure presentation primitives and the logo. Renders menu, cache submenu, summary box, status bar, and holds `LogoState` (lines/colored/block width) plus logo colorizing. No Bubble Tea routing; it takes data and returns strings.
- `flares`: flare domain + domain UI. Holds state structs for wavelength editor, flare filters, flare selector (table + spinner), and cache (rows, filters, viewport). Includes flare loader command, cache IO/filtering, date validation, and render helpers for those views. Domain-first: these types make sense even without the Bubble Tea loop.
- `core`: the orchestrator. `Model` embeds the domain/chrome states, owns the current mode, frame counters, and dimensions. Per-mode update files handle keys/mouse and delegate to `flares`/`chrome` to do work or render. `view.go` stitches the chrome + domain views together. Here, we do message routing, model mutations, tick schedule, and work with the top-level view. Feature-specific rendering/data helpers that don't mutate the core model live in their own packages.

File sizing
-----------
- Keep related state + handlers together (e.g., `update_wavelength.go`, `update_flare_filters.go`), avoid 600+ line blobs and avoid tiny one-function files unless shared.
- Render helpers live with their concept: chrome rendering in `chrome`, flare selection rendering in `flares`, Bubble Tea wiring in `core`.

When adding new features
------------------------
- Ask if it’s Bubble Tea orchestration → put in `core` (new mode handler or view composition).
- If it’s about flare data/query/cache/selection → `flares` (state + helpers + view for that flow).
- If it’s purely look/feel or shared styles → `chrome` or `theme`.
- If it’s external config/IO → `config`.
