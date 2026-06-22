"""默认数据种子：与前端设计稿一致的默认场景与外接系统配置。"""

from __future__ import annotations

from typing import Any


def _sat(sid: str, name: str, group: str, faction: str, payload: str, a: float, e: float,
         i: float, raan: float, argp: float, m0: float, fuel: float, mass: float) -> dict[str, Any]:
    return {
        "id": sid, "name": name, "group": group, "faction": faction,
        "mass": mass, "fuel": fuel,
        "payload": {"type": payload, "state": "待机", "power": 450 if payload == "通信中继" else 320},
        "orbit": {"a": a, "e": e, "i": i, "raan": raan, "argp": argp, "M0": m0},
    }


def default_scenario() -> dict[str, Any]:
    """多星协同观测默认场景（与前端 scenario-store.js 同构）。"""
    scn: dict[str, Any] = {
        "meta": {
            "name": "多星协同观测-A",
            "version": "1.2.0",
            "author": "算法组",
            "created": "2026-06-10",
            "description": "三星对地观测编组 + 中轨中继 + 机动试验星与两个非合作目标的态势感知场景，"
                           "用于轨道机动与任务规划算法验证。",
        },
        "sim": {"epoch": "2026-06-12T04:00:00Z", "duration": 7200, "step": 1,
                "seed": 20260612, "record": True},
        "satellites": [
            _sat("SAT-01", "侦察-01", "观测星组", "红方", "光学成像", 6878, 0.0011, 97.5, 60, 90, 0, 86, 1240),
            _sat("SAT-02", "侦察-02", "观测星组", "红方", "光学成像", 6878, 0.0011, 97.5, 60, 90, 40, 82, 1240),
            _sat("SAT-03", "侦察-03", "观测星组", "红方", "合成孔径雷达", 6928, 0.0015, 97.8, 100, 90, 0, 78, 1560),
            _sat("SAT-04", "中继-01", "通信中继组", "红方", "通信中继", 12760, 0.0008, 28.5, 30, 0, 0, 93, 2100),
            _sat("SAT-05", "中继-02", "通信中继组", "红方", "通信中继", 12760, 0.0008, 28.5, 150, 0, 120, 91, 2100),
            _sat("SAT-06", "机动试验星", "试验星组", "红方", "电子侦察", 7178, 0.021, 45.0, 200, 30, 0, 64, 980),
            _sat("TGT-01", "目标-01", "非合作目标", "蓝方", "未知", 7078, 0.003, 53.0, 210, 60, 25, 50, 800),
            _sat("TGT-02", "目标-02", "非合作目标", "蓝方", "未知", 7278, 0.015, 63.4, 250, 270, 80, 50, 800),
        ],
        "groundStations": [
            {"id": "GS-01", "name": "北京站", "lat": 40.1, "lon": 116.3},
            {"id": "GS-02", "name": "喀什站", "lat": 39.5, "lon": 76.0},
            {"id": "GS-03", "name": "三亚站", "lat": 18.3, "lon": 109.5},
        ],
        "events": [
            {"t": 600, "type": "载荷", "target": "SAT-01", "action": "光学载荷开机"},
            {"t": 900, "type": "载荷", "target": "SAT-03", "action": "SAR 条带成像"},
            {"t": 1800, "type": "机动", "target": "SAT-06", "action": "轨道机动 Δv=2.0 m/s 切向"},
            {"t": 3600, "type": "机动", "target": "SAT-06", "action": "轨道机动 Δv=1.2 m/s 法向"},
            {"t": 5400, "type": "载荷", "target": "SAT-02", "action": "光学载荷关机"},
        ],
    }
    # 演示：观测星 SAT-01 挂相机；加空间拍照裁决与一条拍照预设事件
    scn["satellites"][0]["components"] = [
        {"name": "thruster", "model": "prop.thruster"},
        {"name": "orbit", "model": "orbit.j2"},
        {"name": "attitude", "model": "aocs.simple"},
        {"name": "payload", "model": "payload.generic"},
        {"name": "camera", "model": "sensor.camera",
         "params": {"max_range_km": 5000, "gsd_threshold_m": 200}},
    ]
    scn["adjudications"] = [
        {"type": "adjud.photo"},
        {"type": "adjud.proximity", "params": {"threshold_km": 100}},
    ]
    scn["events"].append(
        {"t": 1200, "type": "拍照", "target": "SAT-01", "action": "拍照 TGT-01"})
    # 演示：机动试验星 SAT-06 挂载一颗可独立显示的子星
    scn["satellites"][5]["children"] = [
        _sat("SUB-06A", "试验子星", "试验星组", "红方", "电子侦察",
             7178, 0.021, 45.0, 200, 30, 2, 100, 120),
    ]
    return scn


def default_external_config() -> dict[str, Any]:
    """外接系统默认配置（与前端 config-page.js 同构，端点指向本服务实际地址）。"""

    def system(sid: str, name: str, desc: str, enabled: bool, protocol: str, endpoint: str,
               timeout: int, auth: str, extra: dict[str, Any] | None = None,
               push: bool = False) -> dict[str, Any]:
        return {
            "id": sid, "name": name, "desc": desc, "enabled": enabled,
            "protocol": protocol, "endpoint": endpoint, "timeout": timeout, "auth": auth,
            "status": "idle", "latency": None, "lastCheck": "—",
            "extra": extra, "push": push,
        }

    return {
        "version": "v1.0",
        "categories": [
            {
                "id": "algo", "name": "算法服务", "sub": "研究算法以服务形式接入",
                "systems": [
                    system("algo-maneuver", "轨道机动规划服务",
                           "接收当前轨道根数与任务约束，返回机动序列（Δv 与点火时刻）",
                           False, "gRPC", "127.0.0.1:50051", 3000, "无",
                           {"label": "算法版本路由", "value": "maneuver-rl/v0.9.3"}),
                    system("algo-sa", "态势感知算法服务",
                           "非合作目标意图识别与威胁评估，订阅全量遥测",
                           False, "HTTP REST", "http://127.0.0.1:8080/api/v1", 5000, "Bearer Token",
                           {"label": "算法版本路由", "value": "sa-transformer/v1.2.0"}),
                    system("algo-sched", "任务调度算法服务",
                           "多星成像任务分配与重规划（星座场景使用）",
                           False, "gRPC", "127.0.0.1:50052", 3000, "无",
                           {"label": "算法版本路由", "value": "sched-milp/v0.4.1"}),
                ],
            },
            {
                "id": "engine", "name": "仿真引擎", "sub": "动力学推进与时间管理",
                "systems": [
                    system("eng-core", "内置仿真引擎 (simcore)",
                           "本系统 Python 仿真引擎，AForce 原子模型规范，经 REST/WebSocket 提供服务",
                           True, "HTTP REST", "http://127.0.0.1:8000/api/health", 2000, "无",
                           {"label": "积分器", "value": "RK4", "options": ["RK4"]}),
                    system("eng-att", "外接姿态动力学引擎",
                           "刚体姿态递推与执行机构模型（可选，未接入时由内置简化模型代替）",
                           False, "TCP", "127.0.0.1:9101", 2000, "无",
                           {"label": "积分器", "value": "RK4", "options": ["RK4", "RKF7(8)"]}),
                ],
            },
            {
                "id": "data", "name": "数据接口", "sub": "遥测落盘与实验记录",
                "systems": [
                    system("data-exp", "实验记录存储",
                           "场景快照、随机种子、配置版本、回放录制归档 —— 实验可复现的关键链路",
                           True, "本地文件", "./data/recordings/", 1000, "无",
                           {"label": "归档格式", "value": "JSON"}),
                    system("data-tsdb", "遥测时序数据库",
                           "全量遥测写入外部时序库（可选）",
                           False, "InfluxDB HTTP", "http://127.0.0.1:8086", 5000, "Token",
                           {"label": "保留策略", "value": "30 天"}),
                ],
            },
            {
                "id": "feed", "name": "数据外发", "sub": "态势帧实时推送外部系统",
                "systems": [
                    system("feed-udp", "UDP 遥测外发",
                           "仿真推进期间向指定地址发送 JSON 态势帧数据报",
                           False, "UDP", "127.0.0.1:9200", 1000, "无",
                           {"label": "外发频率", "value": "随推送节拍"}, push=True),
                    system("feed-tcp", "TCP 态势外发",
                           "按行分隔 JSON 推送态势帧（外部系统作为 TCP 服务端监听）",
                           False, "TCP", "127.0.0.1:9300", 2000, "无",
                           {"label": "帧格式", "value": "NDJSON"}, push=True),
                ],
            },
            {
                "id": "viz", "name": "可视化服务", "sub": "态势推送与外部显示",
                "systems": [
                    system("viz-ws", "态势推送 WebSocket",
                           "向本前端态势页推送实时状态帧（本系统内置通道）",
                           True, "WebSocket", "ws://127.0.0.1:8000/ws/situation", 2000, "无",
                           {"label": "推送频率", "value": "≤15 Hz"}),
                    system("viz-wall", "大屏显示服务",
                           "对外演示大屏的镜像推流（演示场合启用）",
                           False, "WebSocket", "ws://127.0.0.1:8766/wall", 2000, "无",
                           {"label": "推流分辨率", "value": "3840×1080"}),
                ],
            },
        ],
        "snapshots": [
            {"tag": "v1.0", "note": "初始配置", "time": "2026-06-12 00:00", "current": True},
        ],
        "snapshot_store": {},
    }
