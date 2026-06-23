# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

A Python spacecraft simulation platform for **algorithm research & demonstration**: scenario authoring, run control, async command injection, 3D situational display, full replay, and external-system integration. The engine is a Python re-implementation of the **《AForce原子模型仿真建模规范V3.0》** (AForce Atomic-Model Simulation Spec). The codebase is Chinese-first — comments, `display_name`s, scenario fields, and UI text are in Chinese; preserve that when editing.

> Git repository with a GitHub remote (`origin` → `github.com/fcsGitHub/spacecraft-sim`). `main` is the default branch — branch off it for feature work, and `git` history/diffs are reliable. Commit or push only when the user asks.

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

Every model subclasses **`SimModel`** (`simcore/model.py`) and is one of three **kinds** (`model_kind`): **atomic** (`AtomicModel` — leaf models: orbit/thruster/attitude/payload/camera), **composite** (`CompositeModel` in `simcore/composite.py` — an ordered child chain; a satellite is a `SatelliteCompositeModel`), or **adjudication** (`AdjudicationModel` — engine-level neutral global referees, e.g. `adjud.proximity` / `adjud.photo`). All three share the five interfaces — `sim_init` / `sim_ctr_response` / `sim_dir_response` / `sim_advance` / `sim_end` — plus an extension `sim_restore` for replay/checkpoint recovery. Return convention: `0` = OK, non-zero = error. All inter-model data flows through the **seven frozen-dataclass param types** in `simcore/params.py` (Attribute / CtrInput / DirInput / RTInput / RTOutput / KeyOutput / MROutput). Models additionally communicate over a deterministic in-memory **publish-subscribe bus** (`simcore/bus.py`): `sim_advance` returns `messages`, and `BusMessage` is an internal transport type (*not* one of the seven params) stamped with a global `seq` by the engine — declare topics via the `subscribes` / `publishes` class attributes. Model-specific payloads ride inside the `data`/`params` `Mapping` fields — the envelopes themselves are immutable. When adding capabilities, extend within this five-interface / seven-param (+ bus) shape rather than inventing parallel mechanisms.

### Step data flow (two-phase, decoupling matters)

`engine.step()` runs in **two phases**. **Phase 1 (`_advance_entities`)**: every composite entity advances its **component chain** in order (e.g. thruster→orbit→attitude→payload, built by `build_satellite` in `simcore/composite.py`) and may **publish bus messages**. Within an entity, an upstream component's output is merged into the next component's `rt_in.upstream`; within a `CompositeModel` each child only receives the bus messages whose topics it `subscribes` to. **Phase 2 (`_advance_adjuds`)**: adjudication models read **this-step** entity states plus the messages just published in phase 1, then emit verdicts (key outputs and/or their own messages) — e.g. `adjud.photo` consumes a `camera.photo_request` and replies with `camera.photo_result`.

Determinism comes from **deferring delivery by one step**. Across entities a model reads others only via **last-step snapshots** (`ctx.entity_snapshot()` / `rt_in.env["entities"]`), never live state. All bus messages published this step (entity *and* adjudication) are collected into `self._inbox` via `_route_to_entities` and delivered to their subscribers **next** step — so an adjudication verdict reaches the originating entity one step later (the camera sees `camera.photo_result` the step after the request). This one-step lag — for cross-entity reads, adjudication results, and bus traffic alike — keeps stepping order-independent and the run **bit-reproducible** (same scenario + seed + command sequence). Don't introduce direct cross-entity reads of current-step state or same-step message delivery; it breaks determinism.

### Model registration & discovery

Subclass `AtomicModel` (or `AdjudicationModel` for a neutral global referee), set `model_type` (globally-unique key like `"orbit.j2"`) + metadata (`attribute_schema` / `ctr_commands` / `dir_commands`, and optionally `subscribes` / `publishes` bus topics), decorate with `@register_model`. Built-ins live in `simcore/models/` (auto-discovered via `discover_builtin_models()`). External models load with **no repo changes** from `backend/data/models/` or `SCSIM_MODEL_DIRS` (os.pathsep-separated). Adjudication models are enabled **per-scenario** through the `adjudications:` section (a list of `{type, params}` — validated in `scenario.py` against the registry's `model_kind`); absent that section, the engine defaults to a single `adjud.proximity`. The class metadata (now including `model_kind` / `subscribes` / `publishes`) surfaces automatically at `GET /api/models`, which drives the frontend scenario forms and command panels — so adding a model needs no frontend edits.

### Prediction = clone the engine, never re-derive dynamics

`simcore/predict.py` (`GET /api/simulation/predict`) forward-runs a **sandbox clone** of the live engine: fresh `SimulationEngine(scenario)` → `init()` → `restore_mr(snapshot_mr())` → `rng.setstate(...)` → `step(0.0)` to refresh the state frame → re-`schedule_command()` the `pending_commands()`. This makes prediction faithful to the *exact same* component chain, J2 dynamics, in-flight burns, and future scheduled commands — including any custom/extended models. **Never** re-implement orbit propagation in JS for "where it will be"; clone and step. The async path captures engine state synchronously on the main thread (`capture_state`) then runs `run_prediction` in a worker thread to avoid racing the advance loop. Very long horizons coarsen the internal step (bounded by `MAX_PREDICT_STEPS`); `orbits.propagate` still substeps internally so orbit accuracy holds.

## Conventions & gotchas

- **`design/` is the UI authority; `frontend/` is the wired implementation.** `design/` holds the original static prototype (the visual source of truth, incl. `仿真态势页.html` etc.); `frontend/` is the production version hooked to the API. They share token/CSS/JS filenames but **differ** — when changing UI, match `design/` as the reference and edit `frontend/`. Don't assume the two files are interchangeable.
- **Units:** km / km·s⁻¹ / degrees / seconds at every boundary (frontend ↔ API ↔ model I/O). Orbit integration is **SI (meters) internally** — conversions live at the `orbits.py` edge. Keep external surfaces in km.
- **Frontend is buildless** — pure static HTML/JS served by FastAPI; Three.js is vendored in `frontend/vendor/`. No bundler, no `npm`.
- **Scenario validation is shared-rule** — `simcore/scenario.py` mirrors the frontend's validation so JSON/YAML scenarios validate identically on both sides. Changing scenario shape means updating both.
- **Satellite has two independent grouping fields:** `group` (编组, functional — 观测星组/非合作目标…, drives left-list grouping) and `faction` (阵营, allegiance — 红方/蓝方/中立, drives 3D color). They are *not* interchangeable. Adding/renaming such a field means touching the full chain in lockstep: `params.EntityInfo` → `scenario.SatelliteDef` + validation → `engine` (`_build_entities`/upstream/`entity_infos`) → `server/defaults.py` **and** `frontend/shared/store.js` (`sat()` + `validate()`) → `scenario-editor.js` form → `situation-scene.js`/`situation-panels.js` display.
- **Performance contracts** (don't regress when touching the hot loop): osculating element conversion is cached on `ELEMENTS_REFRESH_S` (10 sim-s; force-refreshed during burns / after dir-reset / data recovery); sub-satellite GMST uses epoch + Earth-rotation-rate linear recursion (equivalent to the full formula, avoids per-step `datetime`); WS frames are serialized **once** for all clients; proximity/re-entry alerts use hysteresis to prevent event floods.
- **Test data isolation:** API tests set `os.environ["SCSIM_DATA_DIR"] = tempfile.mkdtemp(...)` **before importing `server.main`** (see `tests/test_api.py` top) so they never touch real `data/`. Preserve that ordering in any new API test. `tests/conftest.py` calls `discover_builtin_models()` and exposes the `scenario_dict` fixture (a two-satellite scenario matching the frontend default).
