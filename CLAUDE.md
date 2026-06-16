# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

A Python spacecraft simulation platform for **algorithm research & demonstration**: scenario authoring, run control, async command injection, 3D situational display, full replay, and external-system integration. The engine is a Python re-implementation of the **《AForce原子模型仿真建模规范V3.0》** (AForce Atomic-Model Simulation Spec). The codebase is Chinese-first — comments, `display_name`s, scenario fields, and UI text are in Chinese; preserve that when editing.

> Not a git repository. There is no version control here — do not rely on `git` for history or diffs.

## Commands

All commands run from `backend/`:

```bash
pip install -r requirements.txt
python -m uvicorn server.main:app --host 127.0.0.1 --port 8000   # dev server → http://127.0.0.1:8000/
python -m pytest tests/ -q                                       # full suite (~113 tests)
python -m pytest tests/test_orbits.py -q                         # one file
python -m pytest tests/test_engine.py::TestStep::test_xyz -q     # one test (Class::method)
```

Type checking uses **pyright** (config: `pyrightconfig.json`, `standard` mode, `extraPaths: ["backend"]`). There is no committed linter/formatter config; user rules prefer black/ruff but nothing enforces it here.

Docker: `docker compose up -d --build` (port 8000, data volume `scsim-data`, host `./models` mounted for custom models). Tests in-container: `docker run --rm -e SCSIM_DATA_DIR=/tmp/d spacecraft-sim python -m pytest tests/ -q`.

## Architecture

Two layers, deliberately decoupled:

- **`backend/simcore/`** — the engine core. **Depends on no web framework** and is usable as a standalone scripting library (see the `simcore/__init__.py` docstring for the script-only entry point). Treat this as the stable API surface.
- **`backend/server/`** — a thin FastAPI layer (REST + WebSocket + static-file hosting) wrapping `simcore`. `runtime.py` owns the async advance loop, speed control, the asyncio command queue, and WS broadcast.

The README has the full module table, the AForce↔Python interface mapping, the REST/WS endpoint list, and the custom-model authoring guide — read it before deep work on either layer.

### The AForce spec is the central design constraint

Every model is an **`AtomicModel`** (`simcore/model.py`) with five interfaces — `sim_init` / `sim_ctr_response` / `sim_dir_response` / `sim_advance` / `sim_end` — plus an extension `sim_restore` for replay/checkpoint recovery. Return convention: `0` = OK, non-zero = error. All inter-model data flows through the **seven frozen-dataclass param types** in `simcore/params.py` (Attribute / CtrInput / DirInput / RTInput / RTOutput / KeyOutput / MROutput). Model-specific payloads ride inside the `data`/`params` `Mapping` fields — the envelopes themselves are immutable. When adding capabilities, extend within this five-interface / seven-param shape rather than inventing parallel mechanisms.

### Step data flow (decoupling matters)

`engine.step()` → `_advance_all()` advances each entity's **component chain** in order (e.g. thruster→orbit→attitude→payload from `assembly.py`). Within an entity, an upstream component's output is merged into the next component's `rt_in.upstream`. Across entities, a model reads other entities only via **last-step snapshots** (`ctx.entity_snapshot()` / `rt_in.env["entities"]`) — never live state. This snapshot indirection is what keeps stepping order-independent and the run **deterministic** (same scenario + seed + command sequence → bit-reproducible). Don't introduce direct cross-entity reads of current-step state; it breaks determinism.

### Model registration & discovery

Subclass `AtomicModel`, set `model_type` (globally-unique key like `"orbit.j2"`) + metadata (`attribute_schema` / `ctr_commands` / `dir_commands`), decorate with `@register_model`. Built-ins live in `simcore/models/` (auto-discovered via `discover_builtin_models()`). External models load with **no repo changes** from `backend/data/models/` or `SCSIM_MODEL_DIRS` (os.pathsep-separated). The class metadata surfaces automatically at `GET /api/models`, which drives the frontend scenario forms and command panels — so adding a model needs no frontend edits.

## Conventions & gotchas

- **`design/` is the UI authority; `frontend/` is the wired implementation.** `design/` holds the original static prototype (the visual source of truth, incl. `仿真态势页.html` etc.); `frontend/` is the production version hooked to the API. They share token/CSS/JS filenames but **differ** — when changing UI, match `design/` as the reference and edit `frontend/`. Don't assume the two files are interchangeable.
- **Units:** km / km·s⁻¹ / degrees / seconds at every boundary (frontend ↔ API ↔ model I/O). Orbit integration is **SI (meters) internally** — conversions live at the `orbits.py` edge. Keep external surfaces in km.
- **Frontend is buildless** — pure static HTML/JS served by FastAPI; Three.js is vendored in `frontend/vendor/`. No bundler, no `npm`.
- **Scenario validation is shared-rule** — `simcore/scenario.py` mirrors the frontend's validation so JSON/YAML scenarios validate identically on both sides. Changing scenario shape means updating both.
- **Performance contracts** (don't regress when touching the hot loop): osculating element conversion is cached on `ELEMENTS_REFRESH_S` (10 sim-s; force-refreshed during burns / after dir-reset / data recovery); sub-satellite GMST uses epoch + Earth-rotation-rate linear recursion (equivalent to the full formula, avoids per-step `datetime`); WS frames are serialized **once** for all clients; proximity/re-entry alerts use hysteresis to prevent event floods.
- **Test data isolation:** API tests set `os.environ["SCSIM_DATA_DIR"] = tempfile.mkdtemp(...)` **before importing `server.main`** (see `tests/test_api.py` top) so they never touch real `data/`. Preserve that ordering in any new API test. `tests/conftest.py` calls `discover_builtin_models()` and exposes the `scenario_dict` fixture (a two-satellite scenario matching the frontend default).
