# 空间飞行器仿真系统（SPACECRAFT SIM · 算法研究平台）

面向**算法研究与演示**的空间飞行器仿真系统：场景生成、仿真过程控制、仿真中异步指令注入、
三维全景/局部态势显示与分析、全过程回放、外接系统配置。
仿真引擎为 Python 实现，模型规范参照《AForce原子模型仿真建模规范V3.0》，强调可扩展性。

## 快速开始

```bash
cd backend
pip install -r requirements.txt
python -m uvicorn server.main:app --host 127.0.0.1 --port 8000
```

浏览器打开 <http://127.0.0.1:8000/>（默认进入场景生成页）。

运行测试：

```bash
cd backend
python -m pytest tests/ -q     # 113 项：轨道力学 / 场景校验 / 引擎 / 指令翻译 / 录制 / REST+WS API
```

## Docker 部署

镜像为纯 Python + 静态前端，无构建步骤，约 260 MB；以非 root 用户运行。

```bash
docker compose up -d --build          # 构建并后台启动
# 浏览器打开 http://127.0.0.1:8000/
docker compose logs -f                # 跟随日志
docker compose down                   # 停止（数据卷 scsim-data 保留）
```

或直接用 `docker`：

```bash
docker build -t spacecraft-sim .
docker run -d -p 8000:8000 -v scsim-data:/app/data --name scsim spacecraft-sim
```

- **持久化**：场景、外接配置、回放录制写入卷 `/app/data`（由 `SCSIM_DATA_DIR` 指定），
  首次启动自动播种默认场景与外接配置种子。
- **自定义外部模型**：把研究人员的 `*.py` 模型放入宿主 `./models`（compose 已挂载到
  `/app/data/models`），重启容器即自动加载；镜像另默认加载示例模型 `examples/models/`
  （`SCSIM_MODEL_DIRS`，可覆盖）。
- **可配置环境变量**：`PORT`（对外端口，默认 8000）、`HOST`、`SCSIM_DATA_DIR`、`SCSIM_MODEL_DIRS`。
- **健康检查**：容器内置 `HEALTHCHECK` 探测 `/api/health`；`docker stop` 经 SIGTERM 触发
  FastAPI lifespan 优雅关闭（停推进循环、关外发连接）。
- 容器内同样可跑测试：`docker run --rm -e SCSIM_DATA_DIR=/tmp/d spacecraft-sim python -m pytest tests/ -q`。

## 三个前端页面

| 页面 | 文件 | 功能 |
|------|------|------|
| 01 场景生成 | `frontend/scenario.html` | 结构树 + 表单编辑卫星/地面站/预设事件，轨道预览，JSON/YAML 实时预览与导入导出，实时校验，自动同步后端 |
| 02 仿真态势 | `frontend/situation.html` | 三维态势（全景/跟踪/局部视角，按**阵营**着色 + **预推演轨迹**叠加），运行控制（开始/暂停/单步/复位/1–300 倍速），遥测曲线，几何分析（星间距离/通视/接近预警/地面站可见性），**构型分析**（LVLH/RIC 相对运动视图：两星已运行+预推演相对航迹），异步指令注入（立即/定时），事件时间线，回放分析（拖动时间线任意跳转） |
| 03 外接配置 | `frontend/config.html` | 外接系统分类管理（算法服务/仿真引擎/数据接口/数据外发/可视化），真实连通性测试（TCP 探测/本地目录探测），配置快照版本与真实回滚，UDP/TCP 态势帧外发 |

前端为纯静态页面（无构建步骤），由 FastAPI 托管；Three.js 已本地化（`frontend/vendor/`）。

## 架构

```
backend/
├── simcore/                 # 仿真引擎核心（不依赖 Web 框架，可独立脚本化使用）
│   ├── params.py            # 七类参数结构（属性/指控/导调/实时输入/实时输出/数据恢复/关键输出）
│   ├── model.py             # AtomicModel 原子模型基类（五接口）+ SimContext
│   ├── registry.py          # @register_model 注册表 + 内置/外部目录模型发现
│   ├── orbits.py            # 轨道力学：根数↔状态、J2 摄动、RK4 积分、星下点
│   ├── timebase.py          # UTC/BJT(北京时) 历元与仿真时钟
│   ├── scenario.py          # 场景加载与校验（JSON/YAML，与前端同规则）
│   ├── assembly.py          # 实体组装：卫星 = 推进→轨道→姿态→载荷 组件链
│   ├── translate.py         # 前端指令模板/预设事件 → 引擎指控(ctr)/导调(dir)指令
│   ├── engine.py            # 步进推进、指令调度、接近预警裁决、数据恢复快照
│   ├── predict.py           # 预推演：克隆引擎状态前向空跑（动力学一致，含预约指令）
│   ├── recorder.py          # 回放录制（采样帧 + 全量事件）
│   └── models/              # 内置原子模型（研究人员扩展入口）
│       ├── orbit_j2.py      #   J2 轨道动力学（支持推力输入、导调轨道重置）
│       ├── thruster.py      #   推进机动（有限点火、编队保持示例控制器、故障注入）
│       ├── attitude.py      #   简化姿态（模式管理、确定性偏差遥测、瞬态响应）
│       └── payload.py       #   通用载荷（开关机/成像/侦收状态机、事件记录）
├── server/                  # FastAPI 服务层
│   ├── main.py              # REST 路由 + WebSocket + 静态前端托管
│   ├── runtime.py           # 仿真运行时：异步推进循环、倍速、异步指令队列、WS 广播
│   ├── external.py          # 外接系统：配置存储、连通性测试、UDP/TCP 态势帧外发
│   └── defaults.py          # 默认场景与默认外接配置种子
├── examples/models/         # 示例外部模型（大气阻力等，演示无侵入扩展）
├── tests/                   # pytest 测试套件（113 项）
└── data/                    # 运行数据：scenario.json / external_config.json / recordings/
frontend/                    # 静态前端（设计稿 space-craft.zip 的接线实现）
Dockerfile                   # 容器镜像（单阶段，非 root，内置 HEALTHCHECK）
docker-compose.yml           # 一键部署（数据卷 + 自定义模型挂载）
models/                      # Docker 自定义外部模型投放目录（挂载到 /app/data/models）
```

### AForce 规范 → Python 对照

| 规范（C++） | 本系统（Python） |
|---|---|
| `SimInit(pShare, bjt[6], utc[6], mpAttribute)` | `sim_init(ctx, bjt, utc, attribute)` |
| `SimCtrResponse(mpCtrIn)` 指控输入 | `sim_ctr_response(ctr_in)`（异步注入，步进间隙调用） |
| `SimDirResponse(mpDirIn)` 导调输入 | `sim_dir_response(dir_in)`（故障注入等） |
| `SimAdvance(..., mpRTIn, mpRTOut, mpKeyVecOut, mpMROut)` | `sim_advance(ctx, bjt, utc, step, rt_in) -> StepResult` |
| `SimEnd(...)` | `sim_end(ctx, bjt, utc, step)` |
| 7 类参数结构体（表1） | `simcore/params.py` 中 7 个 frozen dataclass |
| 模型数据恢复结构体 | `mr_output` + `sim_restore()`（断点恢复/回放接续） |
| 返回 0 正常 / 非 0 异常 | 相同约定 |
| 命名空间防冲突 | `model_type` 注册键（如 `"orbit.j2"`） |
| ID 用 long long | Python int 天然无溢出；实体 ID 沿用场景字符串编号 |

## 扩展自定义模型（研究人员指南）

新增一个原子模型只需三步，前端场景编辑与指令面板的元数据随 `/api/models` 自动可见：

```python
# backend/simcore/models/my_sensor.py —— 放入此目录即被自动发现注册
from simcore.model import AtomicModel, SimContext, Array6
from simcore.params import ParamAttribute, ParamRTInput, ParamRTOutput, StepResult, ParamMROutput
from simcore.registry import register_model

@register_model
class MySensorModel(AtomicModel):
    model_type = "sensor.my"            # 全局唯一注册键
    display_name = "我的传感器"
    category = "sensor"
    attribute_schema = {                # 属性参数说明（供前端表单/文档生成）
        "range_km": {"type": "number", "unit": "km", "default": 500.0, "desc": "探测距离"},
    }

    def sim_init(self, ctx, bjt, utc, attribute: ParamAttribute) -> int:
        super().sim_init(ctx, bjt, utc, attribute)
        self._range = float(attribute.data.get("range_km", 500.0))
        return 0

    def sim_advance(self, ctx, bjt, utc, step, rt_in: ParamRTInput) -> StepResult:
        # rt_in.env["entities"]  -> 上一步全部实体状态快照（含 pos_km/vel_kmps 等）
        # rt_in.upstream         -> 本实体内上游组件（推进/轨道/姿态）的输出
        detections = []  # ... 探测逻辑 ...
        return StepResult(
            rt_output=ParamRTOutput(data={"detections": detections}),
            mr_output=ParamMROutput(time=ctx.sim_time + step, state={}),
        )
```

- 指令响应：覆写 `sim_ctr_response` / `sim_dir_response`，并在 `ctr_commands` / `dir_commands`
  里声明参数说明；
- 组件挂载（无侵入，推荐）：卫星定义中用可选 `components` 字段声明组件链，
  无需修改任何仓库代码（标准模型的轨道根数/质量等属性自动注入，`params` 可覆盖）：

  ```yaml
  satellites:
    - id: SAT-01
      # ... 常规字段 ...
      components:
        - {name: thruster, model: prop.thruster}
        - {name: drag, model: perturb.drag_atmo, params: {cd: 2.2, area_m2: 12}}
        - {name: orbit, model: orbit.j2}
        - {name: attitude, model: aocs.simple}
        - {name: payload, model: payload.generic}
  ```

  组件顺序即推进顺序，上游输出经 `rt_in.upstream` 传给下游；缺省（不写 components）
  使用标准链。指令模板面向标准组件名（thruster/orbit/attitude/payload），
  自定义链沿用同名即可响应指令；
- 外部模型目录（免改仓库）：`*.py` 模型文件放入 `backend/data/models/` 服务启动自动加载，
  或环境变量 `SCSIM_MODEL_DIRS` 指定目录（多个用系统路径分隔符）；脚本化用
  `registry.load_models_from_dir(path)`（幂等，可重复调用）；
- 完整可运行示例：`examples/models/drag_atmo.py`（指数大气阻力摄动，阻力叠加进
  `thrust_accel_mps2` 由轨道模型统一消费，文件头注释含三种加载方式与挂接 YAML）；
- 脚本化研究（不起 Web 服务）：

```python
from simcore import discover_builtin_models, load_scenario, SimulationEngine, command_from_template
discover_builtin_models()
engine = SimulationEngine(load_scenario(open("场景.yaml", encoding="utf-8").read()))
engine.init()
engine.schedule_command(command_from_template("轨道机动", "SAT-01", {"dv": 2.0, "dir": "切向"}, t=600))
while not engine.finished:
    frame = engine.step()          # frame.entities / frame.events
engine.end()
```

## REST / WebSocket API

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/models` | 已注册模型元数据 |
| GET/PUT | `/api/scenario` | 当前场景读写（草稿允许暂存，校验结果随响应返回） |
| POST | `/api/scenario/validate` · `/import` · GET `/export?fmt=yaml` | 校验 / 导入(JSON/YAML) / 导出 |
| GET | `/api/simulation/status` | 运行状态（state/t/duration/speed/seed…） |
| POST | `/api/simulation/load` · `/start` · `/pause` · `/reset` · `/step` · `/speed` | 仿真过程控制 |
| POST | `/api/simulation/command` | **异步指令注入**：`{tpl, target, params, when: now/later, delay}` |
| GET | `/api/simulation/commands` | 指令队列（含执行状态） |
| GET | `/api/simulation/predict` | **预推演**：`?horizon=&step=`，沙箱前向推演各实体未来航迹（动力学与本次推演一致，含未触发预约指令；默认 1 天） |
| POST | `/api/simulation/alert-threshold` | 接近预警门限 |
| GET/DELETE | `/api/replays` · `/api/replays/{id}` | 回放录制列表/详情/删除 |
| GET/PUT | `/api/external/config` | 外接系统配置 |
| POST | `/api/external/test/{id}` · `/test-all` · `/snapshots` · `/rollback` | 连通测试 / 快照 / 回滚 |
| WS | `/ws/situation` | 态势流：`{type:"status"}` 与 `{type:"frame", data, events}`（≤15 Hz） |

## 关键设计

- **确定性与可复现**：引擎同步确定性推进；同场景 + 同种子 + 同指令序列 → 逐位复现。
  复位提示与录制归档共同构成实验可复现链路。
- **异步指令注入**：REST 注入 → asyncio 队列 → 两个仿真步之间调用模型
  `sim_ctr_response`/`sim_dir_response`，与规范的异步指控/导调语义一致。
- **回放**：录制按 `record_interval`（自适应，约 1500 帧全程）采样帧 + 全量事件；
  保存时同步生成 `*.meta.json` 旁车文件，回放列表接口无需解析全量帧数据
  （旧录制首次列表时自动回填）；前端回放模式本地播放/拖动跳转，轨迹按时间窗重建。
- **外接系统**：配置页所有连通测试为真实 TCP/目录探测；
  「数据外发」类目下启用 UDP/TCP 即可向外部系统推送 NDJSON 态势帧。
- **单位约定**：对外接口 km / km/s / 度 / 秒（与前端一致）；引擎内部积分用 SI（米）。
- **性能**：每步精确输出位置/速度/高度/星下点；昂贵的 osculating 根数换算按
  `ELEMENTS_REFRESH_S`（10 仿真秒）缓存刷新（点火期间与导调重置/数据恢复后立即刷新）；
  星下点 GMST 用历元值 + 地球自转率线性递推（与完整公式严格等价，免去每步 datetime 构造）。
  实测单核吞吐：8 星 ≈ 4600 步/s、30 星 ≈ 900 步/s（步长 1 s），均远超 300× 倍速上限。
  WS 广播对全部客户端只序列化一次；再入等持续性告警带迟滞（跌破 120 km 仅告警一次，
  回升 140 km 以上重新武装），防止事件洪泛拖垮时间线与录制。

## 已知简化（面向算法研究的取舍）

- 轨道动力学：二体 + J2，RK4 积分（无大气阻力/三体/光压；`orbits.py` 易于叠加新摄动项）；
- 姿态为简化模式机 + 确定性偏差遥测（非刚体动力学积分）；
- 编队保持为视线方向 P 控制示例，预期由研究算法（如 CW 制导）替换；
- 星下点经纬度采用简化 GMST 球面模型，精度满足态势显示。
