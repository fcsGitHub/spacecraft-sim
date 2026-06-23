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
| 02 仿真态势 | `frontend/situation.html` | 三维态势（全景/跟踪/局部视角，按**阵营**着色 + **战争迷雾**（阵营视角切换：己方+已感知可见，未感知目标隐藏、延时态半透明）+ **预推演轨迹**叠加），运行控制（开始/暂停/单步/复位/1–300 倍速），遥测曲线，几何分析（星间距离/通视/接近预警/地面站可见性），**构型分析**（LVLH/RIC 相对运动视图：两星已运行+预推演相对航迹），异步指令注入（立即/定时），事件时间线，回放分析（拖动时间线任意跳转） |
| 03 外接配置 | `frontend/config.html` | 外接系统分类管理（算法服务/仿真引擎/数据接口/数据外发/可视化），真实连通性测试（TCP 探测/本地目录探测），配置快照版本与真实回滚，UDP/TCP 态势帧外发 |

前端为纯静态页面（无构建步骤），由 FastAPI 托管；Three.js 已本地化（`frontend/vendor/`）。

## 架构

```
backend/
├── simcore/                 # 仿真引擎核心（不依赖 Web 框架，可独立脚本化使用）
│   ├── params.py            # 七类参数结构（属性/指控/导调/实时输入/实时输出/数据恢复/关键输出）
│   ├── bus.py               # 内存发布订阅总线：BusMessage + 全局序号 + 主题过滤（确定性投递）
│   ├── model.py             # SimModel 基类（五接口 + sim_restore）/ AtomicModel / AdjudicationModel + SimContext
│   ├── registry.py          # @register_model 注册表 + 内置/外部目录模型发现
│   ├── orbits.py            # 轨道力学：根数↔状态、J2 摄动、RK4 积分、星下点
│   ├── sun.py               # 低精度太阳位置（ECI 单位矢量）与圆柱影锥受照判定
│   ├── timebase.py          # UTC/BJT(北京时) 历元与仿真时钟
│   ├── scenario.py          # 场景加载与校验（JSON/YAML，与前端同规则；含 adjudications 裁决声明）
│   ├── composite.py         # 组合模型：卫星 = 推进→轨道→姿态→载荷(可选相机) 组件链 + build_satellite
│   ├── translate.py         # 前端指令模板/预设事件 → 引擎指控(ctr)/导调(dir)指令
│   ├── engine.py            # 两相步进（实体推进+发布／裁决评判）、总线投递、指令调度、数据恢复快照
│   ├── predict.py           # 预推演：克隆引擎状态前向空跑（动力学一致，含预约指令）
│   ├── recorder.py          # 回放录制（采样帧 + 全量事件）
│   └── models/              # 内置模型（原子/裁决，研究人员扩展入口）
│       ├── orbit_j2.py         #   J2 轨道动力学（支持推力输入、导调轨道重置）
│       ├── thruster.py         #   推进机动（有限点火、编队保持示例控制器、故障注入）
│       ├── attitude.py         #   简化姿态（模式管理、确定性偏差遥测、瞬态响应）
│       ├── payload.py          #   通用载荷（开关机/成像/侦收状态机、事件记录）
│       ├── camera.py           #   光学相机 sensor.camera：发起拍照请求，发布 camera.photo_request
│       ├── sensor_perception.py #  感知载荷 sensor.perception：开机发布 perception.scan，消费 perception.result
│       ├── adjud_proximity.py  #   接近预警裁决 adjud.proximity：星对距离低于门限预警（迟滞）
│       ├── adjud_photo.py      #   空间拍照裁决 adjud.photo：几何/光照/质量评判，回传 camera.photo_result
│       ├── adjud_perception_full.py    #   全域实时感知裁决 adjud.perception_full（type1：双方实时互感知）
│       ├── adjud_perception_delay.py   #   延时感知裁决 adjud.perception_delay（type2：滞后位置速度，环形缓冲+恢复）
│       └── adjud_perception_onboard.py #   星上感知裁决 adjud.perception_onboard（type3：作用距离判定+结果回传）
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

> 模型分**原子/组合/裁决**三类（`model_kind`），共用上述五接口 + `sim_restore`：原子模型为叶子（轨道/推进/姿态/载荷/相机），组合模型按挂载顺序串联子模型并经 `rt_in.upstream` 串联数据流，裁决模型为引擎级中立全局逻辑、由引擎在实体推进之后统一调度。卫星即 `composite.satellite` 组合实体。模型间除组件链 `upstream` 外，还可经内存发布订阅总线（类属性 `subscribes`/`publishes` 声明主题，投递延迟一拍以保持确定性）通信。

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
  使用标准链。指令模板面向标准组件名（thruster/orbit/attitude/payload/camera），
  自定义链沿用同名即可响应指令；
- 发布订阅总线（跨实体/跨模型解耦）：模型用类属性 `subscribes` / `publishes` 声明总线主题，
  `sim_advance` 返回的 `messages` 由引擎统一盖戳（补 source/全局 seq）后投递，订阅方**下一步**
  在 `rt_in.messages` 收到（延迟一拍，保持逐位复现）。示例：相机 `sensor.camera` 发起
  `camera.photo_request`，空间拍照裁决评判后回传 `camera.photo_result`；感知载荷
  `sensor.perception` 开机发布 `perception.scan`，星上感知裁决判定后回传 `perception.result`；
- 裁决模型（adjudication）：继承 `AdjudicationModel`，为引擎级中立全局逻辑（不归属任何实体/阵营），
  由引擎在全部实体推进**之后**统一调度，可读本拍全部实体态势并产出关键输出/发布消息。
  在场景 `adjudications:` 段声明启用；内置 `adjud.proximity`（接近预警，原引擎内置逻辑迁移而来）
  与 `adjud.photo`（空间拍照，几何/光照/成像质量三段评判）。**感知域裁决**三类：`adjud.perception_full`
  （type1 全域实时互感知）、`adjud.perception_delay`（type2 延时感知，可外推）、`adjud.perception_onboard`
  （type3 星上感知，按感知载荷作用距离判定，命中回传 `perception.result`）——可任选其一，也可
  type2+type3 并用（引擎按 `(阵营, 目标)` 取最新合并）。各裁决产出的阵营感知图汇入 `Frame.perception`，
  驱动**战争迷雾**（见下）。新增 `拍照` 预设事件类型会翻译为相机 `take_photo` 指控指令：

  ```yaml
  adjudications:
    - {type: adjud.photo}
    - {type: adjud.proximity, params: {threshold_km: 100}}   # 缺省即仅启用此项（门限 100 km）
  events:
    - {t: 1200, type: 拍照, target: SAT-01, action: 拍照 TGT-01}   # → 相机 take_photo {target: TGT-01}
  ```

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
| GET | `/api/models` | 已注册模型元数据（含 `model_kind` 原子/组合/裁决 与 `subscribes`/`publishes` 总线主题） |
| GET/PUT | `/api/scenario` | 当前场景读写（草稿允许暂存，校验结果随响应返回） |
| POST | `/api/scenario/validate` · `/import` · GET `/export?fmt=yaml` | 校验 / 导入(JSON/YAML) / 导出 |
| GET | `/api/simulation/status` | 运行状态（state/t/duration/speed/seed…） |
| POST | `/api/simulation/load` · `/start` · `/pause` · `/reset` · `/step` · `/speed` | 仿真过程控制 |
| POST | `/api/simulation/command` | **异步指令注入**：`{tpl, target, params, when: now/later, delay}` |
| GET | `/api/simulation/commands` | 指令队列（含执行状态） |
| GET | `/api/simulation/predict` | **预推演**：`?horizon=&step=`，沙箱前向推演各实体未来航迹（动力学与本次推演一致，含未触发预约指令；默认 1 天） |
| POST | `/api/simulation/alert-threshold` | 接近预警门限（代理到 `adjud.proximity` 裁决模型） |
| GET/DELETE | `/api/replays` · `/api/replays/{id}` | 回放录制列表/详情（`?faction=` 按阵营施加战争迷雾）/删除 |
| GET/PUT | `/api/external/config` | 外接系统配置 |
| POST | `/api/external/test/{id}` · `/test-all` · `/snapshots` · `/rollback` | 连通测试 / 快照 / 回滚 |
| WS | `/ws/situation` | 态势流：`{type:"status"}` 与 `{type:"frame", data, events}`（≤15 Hz，**按连接阵营施加战争迷雾**）；上行控制 `{op:"set_faction", faction}` 切换阵营视角 |

## 关键设计

- **确定性与可复现**：引擎同步确定性推进；同场景 + 同种子 + 同指令序列 → 逐位复现。
  复位提示与录制归档共同构成实验可复现链路。
- **模型分层与发布订阅**：模型分**原子/组合/裁决**三类（`model_kind`），实体即组合模型
  （推进→轨道→姿态→载荷 组件链，可选挂相机）。单步**两相推进**——相位 1 各组合实体推进并向
  内存总线发布消息；相位 2 中立裁决（接近预警 `adjud.proximity` / 空间拍照 `adjud.photo`）读取本拍
  消息评判并产出关键输出。实体间读取与裁决回传**延迟一拍**，保持逐位复现。拍照链路：相机
  `sensor.camera` 发起 `camera.photo_request`，拍照裁决按几何/光照/成像质量评判后回传
  `camera.photo_result`。
- **战争迷雾（服务端按阵营分发）**：感知域裁决在相位 2 读本拍实体真值，按阵营产出各阵营对
  非己方实体的可感知位置速度（来源 realtime/delayed/onboard），引擎合并入 `Frame.perception`。
  运行时 WS 按连接声明的阵营用纯函数 `faction_view` 折叠为「己方真值 + 已感知非己方」并移除
  perception 后下发（每阵营序列化一次；真值绝不出现在非己方链路），回放端点 `?faction=` 同函数
  过滤；中立/全局视角显示全局真值。前端可随时切换阵营视角，未感知目标隐藏、延时感知态半透明显示。
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
