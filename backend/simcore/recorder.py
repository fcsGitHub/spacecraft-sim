"""仿真录制与回放数据管理。

录制文件为单个 JSON：场景快照 + 按 record_interval_s 采样的帧序列 + 全部关键事件。
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from simcore.engine import Frame
from simcore.scenario import Scenario

_ID_PATTERN = re.compile(r"^[A-Za-z0-9_\-]+$")


class RecorderError(Exception):
    pass


def _safe_recording_path(directory: Path, recording_id: str) -> Path:
    """防止路径穿越：录制 ID 仅允许字母数字下划线连字符。"""
    if not _ID_PATTERN.match(recording_id):
        raise RecorderError(f"非法录制 ID: {recording_id}")
    return directory / f"{recording_id}.json"


def _meta_path(directory: Path, recording_id: str) -> Path:
    return directory / f"{recording_id}.meta.json"


def _meta_from_recording(data: dict[str, Any], fallback_id: str) -> dict[str, Any]:
    return {
        "run_id": data.get("run_id", fallback_id),
        "scenario_name": data.get("scenario_name", "?"),
        "epoch_utc": data.get("epoch_utc", ""),
        "frame_count": data.get("frame_count", 0),
        "duration_recorded_s": data.get("duration_recorded_s", 0.0),
        "event_count": len(data.get("events", [])),
    }


@dataclass
class Recorder:
    """采样录制器：按间隔记录帧，事件全量记录。"""

    scenario: Scenario
    run_id: str = ""
    frames: list[dict[str, Any]] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)
    _next_record_t: float = 0.0

    def __post_init__(self) -> None:
        if not self.run_id:
            self.run_id = time.strftime("run_%Y%m%d_%H%M%S")

    def on_frame(self, frame: Frame) -> None:
        frame_dict = frame.to_dict()
        self.events.extend(frame_dict["events"])
        if frame.t + 1e-9 >= self._next_record_t:
            self.frames.append(
                {"t": frame_dict["t"], "utc": frame_dict["utc"], "entities": frame_dict["entities"]}
            )
            self._next_record_t = frame.t + self.scenario.record_interval_s

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "scenario": dict(self.scenario.raw),
            "scenario_name": self.scenario.name,
            "epoch_utc": self.scenario.epoch_utc,
            "step_s": self.scenario.step_s,
            "record_interval_s": self.scenario.record_interval_s,
            "frame_count": len(self.frames),
            "duration_recorded_s": self.frames[-1]["t"] if self.frames else 0.0,
            "frames": self.frames,
            "events": self.events,
        }

    def save(self, directory: str | Path) -> Path:
        out_dir = Path(directory)
        out_dir.mkdir(parents=True, exist_ok=True)
        data = self.to_dict()
        path = _safe_recording_path(out_dir, self.run_id)
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        # meta 旁车文件：list_recordings 无需解析全量帧数据
        _meta_path(out_dir, self.run_id).write_text(
            json.dumps(_meta_from_recording(data, self.run_id), ensure_ascii=False),
            encoding="utf-8",
        )
        return path


def list_recordings(directory: str | Path) -> list[dict[str, Any]]:
    """录制清单（不含帧数据，便于前端列表展示）。

    优先读取 meta 旁车文件；旧录制缺失 meta 时解析全量文件并回填。
    """
    out_dir = Path(directory)
    if not out_dir.is_dir():
        return []
    items: list[dict[str, Any]] = []
    for path in sorted(out_dir.glob("*.json"), reverse=True):
        if path.name.endswith(".meta.json"):
            continue
        meta_path = _meta_path(out_dir, path.stem)
        if meta_path.is_file():
            try:
                items.append(json.loads(meta_path.read_text(encoding="utf-8")))
                continue
            except (json.JSONDecodeError, OSError):
                pass  # meta 损坏则回退全量解析
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        meta = _meta_from_recording(data, path.stem)
        try:
            meta_path.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass  # 回填失败不影响列表
        items.append(meta)
    return items


def load_recording(directory: str | Path, run_id: str) -> dict[str, Any]:
    path = _safe_recording_path(Path(directory), run_id)
    if not path.is_file():
        raise RecorderError(f"录制不存在: {run_id}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RecorderError(f"录制文件损坏: {run_id}（{exc}）") from exc


def delete_recording(directory: str | Path, run_id: str) -> None:
    out_dir = Path(directory)
    path = _safe_recording_path(out_dir, run_id)
    if path.is_file():
        path.unlink()
    meta = _meta_path(out_dir, run_id)
    if meta.is_file():
        meta.unlink()
