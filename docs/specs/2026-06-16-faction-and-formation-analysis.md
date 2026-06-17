# 阵营字段 + 预推演轨迹 + 两星相对构型分析 — 设计

日期：2026-06-16 · 状态：已批准，实施中

## 目标

1. 卫星实体模型新增 **阵营**（faction）字段，与现有 **编组**（group）并存。
2. 前端可展示卫星的 **已运行轨迹** 与 **预推演轨迹**。
3. 新增 **相对构型分析**（LVLH/RIC 相对运动视图），便于比较两颗卫星的构型演化。

## 已定决策

- 阵营为**独立新字段**，预设值 `红方 / 蓝方 / 中立`，与编组互不影响。
- 三维态势中**阵营驱动主色**（红方 `#d96459` / 蓝方 `#5b8def` / 中立 `#8a93a6`）；编组下沉为左侧分组与标签。
- 预推演采用**后端沙箱**：克隆当前引擎状态前向空跑，动力学与本次推演完全一致（J2 / 推进 / 姿态 / 载荷 / 任意自定义组件 + 未触发的预约指令）。
- 预推演**默认时长 1 天（86400 s），可在 UI 调节**。
- 相对构型采用**新增 LVLH/RIC 视图**（参考星 RIC 系展示目标星历史+预测相对航迹）。
- **保留** ECI 三维预推虚线叠加（针对选中星/构型对，限长以保证可读性）。

## 性能约束（预推演）

- 内部步进默认用引擎步长；步数超过 `MAX_PREDICT_STEPS`（≈8000）时自适应放大预测步长（`orbits.propagate` 内部仍按 ≤10 s 子步，轨道精度不受影响），响应回报 `step_used_s`，透明可见。
- 预测在 `asyncio.to_thread` 中执行，不阻塞事件循环；状态在主线程同步快照后再交线程，避免与实时推进竞争。
- 前端按需取 + 缓存（暂停 / 切换参考星 / 点「刷新预推」时刷新，不每帧拉取）。

## 后端改动

| 文件 | 改动 |
|------|------|
| `simcore/params.py` | `EntityInfo` 增 `faction: str = ""` |
| `simcore/scenario.py` | `SatelliteDef` 增 `faction`；`scenario_from_dict` 解析；校验宽松（缺省/非红蓝中立不报错） |
| `simcore/engine.py` | `_build_entities` 注入 faction；upstream/`entity_infos()` 携带 faction；新增 `pending_commands()` 公共访问器 |
| `simcore/predict.py`（新） | `predict_tracks(engine, horizon_s, sample_step_s=None)` → `PredictionResult{t0,horizon_s,step_used_s,times,tracks{id:[{pos_km,vel_kmps}]}}`；克隆=新建引擎→init→restore_mr→rng.setstate→step(0.0)→schedule(pending)→前向采样；不污染实时引擎 |
| `simcore/__init__.py` | 导出 `predict_tracks`, `PredictionResult` |
| `server/runtime.py` | `predict(horizon_s, sample_step_s)`：主线程快照 + `to_thread` 跑预测 |
| `server/main.py` | `GET /api/simulation/predict?horizon=&step=`（未装载 → 409） |
| `server/defaults.py` | 默认 8 星补 faction（观测/中继=红方、试验星=红方、非合作目标=蓝方） |

## 前端改动

| 文件 | 改动 |
|------|------|
| `shared/store.js` | `sat()` 增 faction；默认 8 星赋值；`validate()` 镜像（宽松） |
| `scenario-editor.js` | 「基本信息」段加「阵营」下拉（红方/蓝方/中立）；模板补 faction |
| `situation-scene.js` | `FACTION_COLORS` 着色（球体/轨道线/轨迹）；`factionColor()` 导出；`setPredicted(tracks)` 画选中对的预推虚线（限长）；编组改为标签用途 |
| `situation-main.js` | `pushHistory` 补存 `vel`；预推缓存 + `refreshPrediction(horizon)`（live 走 API、replay 用游标后帧）；ctx 暴露 `sampleVel/getPrediction/refreshPrediction/getMode`；喂 `SitScene.setPredicted` |
| `situation-formation.js`（新） | `SitFormation` 模块：LVLH 画布（R-T 平面）绘历史实线 + 预测虚线 + 当前点；构型参数（距离/距离变化率/ΔR/ΔT/ΔN/通视/预推时长）；参考-目标选择 + 时长控件 + 刷新 |
| `situation-panels.js` | 第 4 个 tab「构型」委托 `SitFormation`；实体列表/选中卡显示阵营色与编组标签 |
| `situation.html` | 加 tab 按钮 + `#tab-formation` 容器 + `situation-formation.js` script |
| `situation.css` | 阵营徽标 / LVLH 画布 / 时长控件样式 |

## LVLH/RIC 帧（前端）

参考星 A（ECI）位置 `r`、速度 `v`：`R̂=r/|r|`，`N̂=(r×v)/|r×v|`，`T̂=N̂×R̂`。
目标星 B 相对位置 `Δr=r_B−r_A`，投影 `ΔR=Δr·R̂`、`ΔT=Δr·T̂`、`ΔN=Δr·N̂`（km）。
主图绘 T（横，迹向）×R（纵，径向）；ΔN 作读数。历史段各采样点需 A 的速度（`pushHistory` 补 vel）。

## 测试（TDD，目标 80%+）

- `tests/test_scenario.py`：faction 解析 / 缺省为空 / 校验宽松。
- `tests/test_predict.py`（新）：采样长度；**确定性**（两次预测一致）；**不污染**（预测后 `clock.t`/`last_frame` 不变）；**预约机动生效**（含/不含预约指令的预测在机动后发散）；超长时长触发 `step_used_s > step_s` 且步数受限。
- `tests/test_api.py`：`/api/simulation/predict` 正常返回 tracks；未装载 409。

## 分期

1. 后端数据模型（faction 贯通 + defaults + 测试）
2. 后端预推演（predict.py + runtime + 接口 + 测试）
3. 前端数据模型（store/editor/校验 faction）
4. 前端三维（阵营配色 + ECI 预推叠加）
5. 前端构型 tab（LVLH 视图 + 预推/回放接线）
6. 文档（README/CLAUDE）+ 手动验证
