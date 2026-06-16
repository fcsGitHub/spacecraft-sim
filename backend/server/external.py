"""外接系统：配置存储、真实连通性测试、态势帧外发。

- 配置持久化到 data/external_config.json，快照支持真实回滚（保存完整配置副本）
- 连接测试：按协议解析端点做 TCP 可达性检测（本地文件协议检查目录可写）
- 外发：enabled 且 push 的系统在每次帧广播时收到 JSON 态势帧
  - UDP: 单数据报；TCP: NDJSON 持久连接（断开自动重连，失败静默丢帧并标记状态）
"""

from __future__ import annotations

import asyncio
import json
import logging
import socket
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from server.defaults import default_external_config

logger = logging.getLogger("scsim.external")

WARN_LATENCY_MS = 60.0


class ExternalConfigStore:
    """外接系统配置的读写与快照版本管理。"""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._config: dict[str, Any] = self._load()

    def _load(self) -> dict[str, Any]:
        if self.path.is_file():
            try:
                return json.loads(self.path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                logger.exception("外接配置损坏，使用默认配置")
        config = default_external_config()
        self._write(config)
        return config

    def _write(self, config: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")

    @property
    def config(self) -> dict[str, Any]:
        return self._config

    def replace(self, config: dict[str, Any]) -> None:
        if not isinstance(config, dict) or "categories" not in config:
            raise ValueError("配置必须包含 categories 字段")
        self._config = config
        self._write(config)

    def iter_systems(self):
        for cat in self._config.get("categories", []):
            for sys_ in cat.get("systems", []):
                yield sys_

    def find_system(self, system_id: str) -> dict[str, Any] | None:
        for sys_ in self.iter_systems():
            if sys_.get("id") == system_id:
                return sys_
        return None

    def save(self) -> None:
        self._write(self._config)

    # ---- 快照版本 ----

    def save_snapshot(self, note: str) -> dict[str, Any]:
        version = self._config.get("version", "v1.0")
        try:
            new_tag = f"v{float(version.lstrip('v')) + 0.1:.1f}"
        except ValueError:
            new_tag = f"{version}+1"
        snapshot = {
            "tag": new_tag,
            "note": note or "未填写变更说明",
            "time": time.strftime("%Y-%m-%d %H:%M"),
            "current": True,
        }
        for snap in self._config.setdefault("snapshots", []):
            snap["current"] = False
        self._config["snapshots"].insert(0, snapshot)
        self._config["version"] = new_tag
        store = self._config.setdefault("snapshot_store", {})
        store[new_tag] = json.loads(json.dumps(self._config["categories"], ensure_ascii=False))
        self.save()
        return snapshot

    def rollback(self, tag: str) -> None:
        snapshots = self._config.get("snapshots", [])
        if not any(s.get("tag") == tag for s in snapshots):
            raise ValueError(f"快照不存在: {tag}")
        stored = self._config.get("snapshot_store", {}).get(tag)
        if stored is not None:
            self._config["categories"] = json.loads(json.dumps(stored, ensure_ascii=False))
        for snap in snapshots:
            snap["current"] = snap.get("tag") == tag
        self._config["version"] = tag
        self.save()


def parse_endpoint(protocol: str, endpoint: str) -> tuple[str, int] | None:
    """解析端点为 (host, port)；本地文件等非网络协议返回 None。"""
    text = (endpoint or "").strip()
    if protocol == "本地文件" or text.startswith("./") or text.startswith("/"):
        return None
    if "://" in text:
        parsed = urlparse(text)
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or {"https": 443, "wss": 443, "http": 80, "ws": 80}.get(
            parsed.scheme, 80
        )
        return host, port
    if ":" in text:
        host, _, port_str = text.rpartition(":")
        try:
            return host or "127.0.0.1", int(port_str)
        except ValueError:
            return None
    return None


async def test_system(system: dict[str, Any]) -> dict[str, Any]:
    """真实连通性检测：更新并返回 {status, latency, lastCheck}。"""
    timeout_s = max(0.1, float(system.get("timeout") or 2000) / 1000.0)
    protocol = str(system.get("protocol") or "")
    endpoint = str(system.get("endpoint") or "")
    now = time.strftime("%H:%M:%S")

    addr = parse_endpoint(protocol, endpoint)
    if addr is None:
        start = time.perf_counter()
        path = Path(endpoint)
        try:
            path.mkdir(parents=True, exist_ok=True)
            probe = path / ".scsim_probe"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
            latency = (time.perf_counter() - start) * 1000
            result = {"status": "ok" if latency < WARN_LATENCY_MS else "warn",
                      "latency": round(latency, 1), "lastCheck": now}
        except OSError as exc:
            logger.warning("本地路径检测失败 %s: %s", endpoint, exc)
            result = {"status": "danger", "latency": None, "lastCheck": now}
    else:
        host, port = addr
        start = time.perf_counter()
        try:
            _reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port), timeout=timeout_s
            )
            latency = (time.perf_counter() - start) * 1000
            writer.close()
            try:
                await writer.wait_closed()
            except (OSError, asyncio.CancelledError):
                pass
            result = {"status": "ok" if latency < WARN_LATENCY_MS else "warn",
                      "latency": round(latency, 1), "lastCheck": now}
        except (OSError, asyncio.TimeoutError) as exc:
            logger.info("连接测试失败 %s(%s:%s): %s", system.get("id"), host, port, exc)
            result = {"status": "danger", "latency": None, "lastCheck": now}

    system.update(result)
    return result


class FramePusher:
    """向启用 push 的外接系统推送态势帧。"""

    def __init__(self, store: ExternalConfigStore):
        self.store = store
        self._udp_socket: socket.socket | None = None
        self._tcp_writers: dict[str, asyncio.StreamWriter] = {}
        self._tcp_backoff_until: dict[str, float] = {}

    def _push_targets(self):
        for sys_ in self.store.iter_systems():
            if sys_.get("enabled") and sys_.get("push"):
                yield sys_

    async def push(self, frame: dict[str, Any]) -> None:
        targets = list(self._push_targets())
        if not targets:
            return
        payload = json.dumps(frame, ensure_ascii=False).encode("utf-8")
        for sys_ in targets:
            addr = parse_endpoint(str(sys_.get("protocol") or ""), str(sys_.get("endpoint") or ""))
            if addr is None:
                continue
            if sys_.get("protocol") == "UDP":
                self._push_udp(sys_, addr, payload)
            elif sys_.get("protocol") == "TCP":
                await self._push_tcp(sys_, addr, payload)

    def _push_udp(self, sys_: dict[str, Any], addr: tuple[str, int], payload: bytes) -> None:
        try:
            if self._udp_socket is None:
                self._udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                self._udp_socket.setblocking(False)
            self._udp_socket.sendto(payload, addr)
        except OSError as exc:
            logger.debug("UDP 外发失败 %s: %s", sys_.get("id"), exc)

    async def _push_tcp(self, sys_: dict[str, Any], addr: tuple[str, int], payload: bytes) -> None:
        sid = str(sys_.get("id"))
        writer = self._tcp_writers.get(sid)
        if writer is None or writer.is_closing():
            if time.monotonic() < self._tcp_backoff_until.get(sid, 0):
                return
            try:
                _reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(*addr), timeout=1.0
                )
                self._tcp_writers[sid] = writer
            except (OSError, asyncio.TimeoutError):
                self._tcp_backoff_until[sid] = time.monotonic() + 5.0
                return
        try:
            writer.write(payload + b"\n")
            await writer.drain()
        except (OSError, ConnectionError):
            self._tcp_writers.pop(sid, None)
            self._tcp_backoff_until[sid] = time.monotonic() + 5.0

    async def close(self) -> None:
        for writer in self._tcp_writers.values():
            writer.close()
        self._tcp_writers.clear()
        if self._udp_socket is not None:
            self._udp_socket.close()
            self._udp_socket = None
