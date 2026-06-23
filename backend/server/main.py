"""空间飞行器仿真系统 — FastAPI 应用入口。

启动：cd backend && python -m uvicorn server.main:app --port 8000
前端：http://127.0.0.1:8000/
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import yaml
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from simcore import (
    ScenarioError,
    delete_recording,
    discover_builtin_models,
    list_models,
    list_recordings,
    load_recording,
    validate_scenario,
)
from simcore.recorder import RecorderError
from simcore.perception import fog_recording
from simcore.registry import load_models_from_dir
from server.defaults import default_scenario
from server.external import ExternalConfigStore, FramePusher, test_system
from server.runtime import RuntimeError_, SimulationRunner

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("scsim.server")

BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_DIR = BACKEND_DIR.parent
# SCSIM_DATA_DIR 环境变量可重定向数据目录（测试隔离用）
DATA_DIR = Path(os.environ.get("SCSIM_DATA_DIR", str(BACKEND_DIR / "data")))
RECORDINGS_DIR = DATA_DIR / "recordings"
SCENARIO_PATH = DATA_DIR / "scenario.json"
EXTERNAL_CONFIG_PATH = DATA_DIR / "external_config.json"
EXTERNAL_MODELS_DIR = DATA_DIR / "models"
FRONTEND_DIR = PROJECT_DIR / "frontend"


def load_external_models() -> None:
    """加载外部模型目录：data/models/ 与 SCSIM_MODEL_DIRS（os.pathsep 分隔多个）。

    单个目录加载失败仅记录日志，不阻断服务启动。
    """
    dirs = [EXTERNAL_MODELS_DIR]
    dirs += [
        Path(p.strip())
        for p in os.environ.get("SCSIM_MODEL_DIRS", "").split(os.pathsep)
        if p.strip()
    ]
    for directory in dirs:
        if not directory.is_dir():
            continue
        try:
            count = load_models_from_dir(directory)
            if count:
                logger.info("外部模型目录 %s 新增注册 %d 个模型", directory, count)
        except Exception:
            logger.exception("外部模型目录加载失败: %s", directory)


# ---------- 场景持久化 ----------

def read_scenario_file() -> dict[str, Any]:
    if SCENARIO_PATH.is_file():
        try:
            return json.loads(SCENARIO_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            logger.exception("场景文件损坏，使用默认场景")
    data = default_scenario()
    write_scenario_file(data)
    return data


def write_scenario_file(data: dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SCENARIO_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------- 应用与全局对象 ----------

runner = SimulationRunner(recordings_dir=str(RECORDINGS_DIR))
external_store: ExternalConfigStore
pusher: FramePusher


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global external_store, pusher
    discover_builtin_models()
    load_external_models()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
    read_scenario_file()  # 确保默认场景存在
    external_store = ExternalConfigStore(EXTERNAL_CONFIG_PATH)
    pusher = FramePusher(external_store)
    runner.set_push_hook(pusher.push)
    logger.info("已注册原子模型: %s", [m["model_type"] for m in list_models()])
    yield
    runner.stop_loop()
    await pusher.close()


app = FastAPI(title="空间飞行器仿真系统", version="1.0.0", lifespan=lifespan)


# ---------- 请求模型 ----------

class StepRequest(BaseModel):
    dt: float = Field(default=10.0, gt=0, le=3600)


class SpeedRequest(BaseModel):
    speed: float = Field(gt=0, le=3600)


class ThresholdRequest(BaseModel):
    km: float = Field(gt=0, le=100000)


class CommandRequest(BaseModel):
    tpl: str
    target: str
    params: dict[str, Any] = Field(default_factory=dict)
    when: str = Field(default="now", pattern="^(now|later)$")
    delay: float = Field(default=0.0, ge=0)


class SnapshotRequest(BaseModel):
    note: str = ""


class RollbackRequest(BaseModel):
    tag: str


class ImportRequest(BaseModel):
    text: str
    fmt: str = Field(default="auto", pattern="^(auto|json|yaml)$")


# ---------- 基础 ----------

@app.get("/api/health")
async def health() -> dict[str, Any]:
    return {"ok": True, "service": "spacecraft-sim", "state": runner.state}


@app.get("/api/models")
async def models() -> list[dict[str, Any]]:
    return list_models()


# ---------- 场景 ----------

@app.get("/api/scenario")
async def get_scenario() -> dict[str, Any]:
    data = read_scenario_file()
    errors, warnings = validate_scenario(data)
    return {"data": data, "errors": errors, "warnings": warnings}


@app.put("/api/scenario")
async def put_scenario(data: dict[str, Any]) -> dict[str, Any]:
    """保存场景草稿（允许暂存未通过校验的编辑态，校验结果随响应返回）。"""
    if not isinstance(data, dict) or "meta" not in data or "satellites" not in data:
        raise HTTPException(400, "场景结构不完整：缺少 meta 或 satellites")
    write_scenario_file(data)
    errors, warnings = validate_scenario(data)
    return {"saved": True, "errors": errors, "warnings": warnings}


@app.post("/api/scenario/validate")
async def validate_scenario_api(data: dict[str, Any]) -> dict[str, Any]:
    errors, warnings = validate_scenario(data)
    return {"errors": errors, "warnings": warnings}


@app.post("/api/scenario/import")
async def import_scenario(req: ImportRequest) -> dict[str, Any]:
    """导入 JSON/YAML 文本为当前场景（须通过校验）。"""
    try:
        from simcore import load_scenario

        scenario = load_scenario(req.text, fmt=req.fmt)
    except ScenarioError as exc:
        raise HTTPException(400, detail={"errors": exc.errors}) from exc
    write_scenario_file(scenario.raw)
    return {"saved": True, "name": scenario.name}


@app.get("/api/scenario/export")
async def export_scenario(fmt: str = "json"):
    data = read_scenario_file()
    if fmt == "yaml":
        text = yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
        return PlainTextResponse(text, media_type="application/x-yaml")
    return PlainTextResponse(json.dumps(data, ensure_ascii=False, indent=2),
                             media_type="application/json")


# ---------- 仿真控制 ----------

@app.get("/api/simulation/status")
async def sim_status() -> dict[str, Any]:
    return runner.status_payload()


@app.post("/api/simulation/load")
async def sim_load(data: dict[str, Any] | None = None) -> dict[str, Any]:
    scenario_dict = data if data else read_scenario_file()
    try:
        runner.load(scenario_dict)
    except ScenarioError as exc:
        raise HTTPException(400, detail={"errors": exc.errors}) from exc
    await runner.broadcast_status()
    await runner.broadcast_frame_now()
    return runner.status_payload()


@app.post("/api/simulation/start")
async def sim_start() -> dict[str, Any]:
    try:
        runner.start()
    except RuntimeError_ as exc:
        raise HTTPException(409, str(exc)) from exc
    await runner.broadcast_status()
    return runner.status_payload()


@app.post("/api/simulation/pause")
async def sim_pause() -> dict[str, Any]:
    runner.pause()
    await runner.broadcast_status()
    return runner.status_payload()


@app.post("/api/simulation/reset")
async def sim_reset() -> dict[str, Any]:
    try:
        runner.reset()
    except (RuntimeError_, ScenarioError) as exc:
        raise HTTPException(409, str(exc)) from exc
    await runner.broadcast_status()
    await runner.broadcast_frame_now()
    return runner.status_payload()


@app.post("/api/simulation/step")
async def sim_step(req: StepRequest) -> dict[str, Any]:
    try:
        await runner.step_once(req.dt)
    except RuntimeError_ as exc:
        raise HTTPException(409, str(exc)) from exc
    return runner.status_payload()


@app.post("/api/simulation/speed")
async def sim_speed(req: SpeedRequest) -> dict[str, Any]:
    try:
        runner.set_speed(req.speed)
    except RuntimeError_ as exc:
        raise HTTPException(400, str(exc)) from exc
    await runner.broadcast_status()
    return runner.status_payload()


@app.post("/api/simulation/alert-threshold")
async def sim_alert_threshold(req: ThresholdRequest) -> dict[str, Any]:
    try:
        runner.set_alert_threshold(req.km)
    except RuntimeError_ as exc:
        raise HTTPException(409, str(exc)) from exc
    return runner.status_payload()


@app.post("/api/simulation/command")
async def sim_command(req: CommandRequest) -> dict[str, Any]:
    """异步指令注入：立即执行或定时执行。"""
    try:
        entry = await runner.inject_command(req.tpl, req.target, req.params, req.when, req.delay)
    except RuntimeError_ as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"accepted": True, "command": entry}


@app.get("/api/simulation/commands")
async def sim_commands() -> list[dict[str, Any]]:
    return runner.command_list()


@app.get("/api/simulation/predict")
async def sim_predict(horizon: float = 86400.0, step: float | None = None) -> dict[str, Any]:
    """预推演当前态势的各实体未来航迹（默认 1 天，动力学与本次推演一致）。"""
    try:
        return await runner.predict(horizon, step)
    except RuntimeError_ as exc:
        raise HTTPException(409, str(exc)) from exc


# ---------- 回放 ----------

@app.get("/api/replays")
async def replays() -> list[dict[str, Any]]:
    return list_recordings(RECORDINGS_DIR)


@app.get("/api/replays/{run_id}")
async def replay_detail(run_id: str, faction: str = "") -> dict[str, Any]:
    try:
        rec = load_recording(RECORDINGS_DIR, run_id)
    except RecorderError as exc:
        raise HTTPException(404, str(exc)) from exc
    return fog_recording(rec, faction)


@app.delete("/api/replays/{run_id}")
async def replay_delete(run_id: str) -> dict[str, Any]:
    try:
        delete_recording(RECORDINGS_DIR, run_id)
    except RecorderError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"deleted": run_id}


# ---------- 外接系统 ----------

@app.get("/api/external/config")
async def external_config() -> dict[str, Any]:
    return external_store.config


@app.put("/api/external/config")
async def external_config_put(data: dict[str, Any]) -> dict[str, Any]:
    try:
        external_store.replace(data)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"saved": True}


@app.post("/api/external/test/{system_id}")
async def external_test(system_id: str) -> dict[str, Any]:
    system = external_store.find_system(system_id)
    if system is None:
        raise HTTPException(404, f"外接系统不存在: {system_id}")
    if not system.get("enabled"):
        raise HTTPException(409, "系统未启用")
    result = await test_system(system)
    external_store.save()
    return {"id": system_id, **result}


@app.post("/api/external/test-all")
async def external_test_all() -> dict[str, Any]:
    enabled = [s for s in external_store.iter_systems() if s.get("enabled")]
    results = await asyncio.gather(*(test_system(s) for s in enabled))
    external_store.save()
    return {"results": {s["id"]: r for s, r in zip(enabled, results)}}


@app.post("/api/external/snapshots")
async def external_snapshot(req: SnapshotRequest) -> dict[str, Any]:
    return external_store.save_snapshot(req.note)


@app.post("/api/external/rollback")
async def external_rollback(req: RollbackRequest) -> dict[str, Any]:
    try:
        external_store.rollback(req.tag)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    return {"version": external_store.config.get("version")}


# ---------- WebSocket ----------

@app.websocket("/ws/situation")
async def ws_situation(ws: WebSocket) -> None:
    await ws.accept()
    runner.attach(ws)
    try:
        await runner.send_snapshot(ws)
        while True:
            raw = await ws.receive_text()       # 心跳/控制消息
            try:
                msg = json.loads(raw)
            except (ValueError, TypeError):
                continue                         # "ping" 等非 JSON 忽略
            if isinstance(msg, dict) and msg.get("op") == "set_faction":
                runner.set_faction(ws, str(msg.get("faction") or ""))
                await runner.send_snapshot(ws)   # 立即补发该阵营视图
    except WebSocketDisconnect:
        pass
    finally:
        runner.detach(ws)


# ---------- 静态前端 ----------

@app.get("/")
async def index() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "scenario.html")


if FRONTEND_DIR.is_dir():
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
