TUI package layout and why
==========================

Purpose: capture the split so future changes stay consistent and we do not
rebuild the same glue in multiple places.

Top-level rule
--------------
- `core` owns the Bubble Tea loop: model, Init/Update/View, mode routing, and all state mutation in response to tea messages.
- Other packages define narrow state structs and helpers for their domain, but do not route tea messages or change modes themselves.

Bubble Tea loop (how the cycle runs)
------------------------------------
The program runs a loop of message → Update → View. Messages are empty interfaces used to
transfer data. These interfaces hold the data of a pointer to a type and a pointer to a value. We
only care about the type. We make structs which we wrap as messages to create types of messages, which may 
be used to route behaviors. We schedule these messages by returning a function that schedules to message along with
a copy of the mutated model after processing. After processing one message, we render a string output that is drawn
on the TUI in question. We cannot mutate the model while viewing. Instead of using pointers and mutate the model
internally while updating, we pass a mutated copy to create testable state transfers and avoid hidden side 
effects of writing onto the same data (especially if we are rendering and processing multiple things at once).
This keeps the update cycle easy to follow and deterministic: given the same input message and the same starting
model value, Update returns the same next model value. View takes a copy of this model for rendering. So, any mutations
done to a state in View will NOT persist throughout the program. View only renders. We keep a global frame count 
for animations instead of calling them per event to make the logic easier. This is okay, since for 64 bit systems, an
integer will take up 8 bytes of memory and have a max value of 2^63 - 1. At 12.5 frames per second (the FPS of this
program as of now), this would require 9.22e18 seconds or 2.92e11 years. And I am confident that no computer will be
running this program nonstop for that long. For a 32 bit system, it would be about 5.4 years, which is still beyond
reason.

Packages
--------
- `config`: reads/writes `.vars.env` and finds repo-level assets from the built binary path. IO only, no UI.
- `utils`: shared helpers (clamp, gradients, mouse hit mapping, atomic save). No state.
- `chrome`: presentation primitives. Renders menu + cache submenu, summary box, status bar, logo. Holds `LogoState` (lines/colored/block width) and logo colorizing. No Bubble Tea routing; it takes data and returns strings.
- `flares`: flare domain + domain UI. Holds state for wavelength editor, flare filters, flare selector (table + spinner), and cache (rows, filters, viewport). Includes flare loader cmd, cache IO/filtering, date validation, and render helpers. Domain-first: these types make sense even without the Bubble Tea loop.
- `core`: the orchestrator. `Model` embeds the domain/chrome states, owns mode, frame counters, and dimensions. Per-mode update files handle keys/mouse and delegate to `flares`/`chrome` to do work or render. `view.go` stitches chrome + domain views together. This is where message routing, model mutation, tick scheduling, and top-level view assembly live.

File sizing
-----------
- Keep related state + handlers together (e.g., `update_wavelength.go`, `update_flare_filters.go`). Avoid 600+ line blobs and tiny one-function files unless shared.
- Render helpers live with their concept: chrome rendering in `chrome`, flare selection rendering in `flares`, Bubble Tea wiring in `core`.

When adding new features
------------------------
- If it is Bubble Tea orchestration → `core` (new mode handler or view composition).
- If it is flare data/query/cache/selection → `flares` (state + helpers + view for that flow).
- If it is pure look/feel or common logic → `chrome` or `utils`.
- If it is external config/IO → `config`.
