# 自定义外部模型投放目录（Docker 卷挂载点）

把研究人员编写的原子模型 `*.py` 文件放进本目录，`docker compose` 会将其挂载到容器内
`/app/data/models`，服务**启动时自动加载**（无需改动仓库代码或重建镜像）。

模型写法见 [`backend/examples/models/drag_atmo.py`](../backend/examples/models/drag_atmo.py)：
用 `@register_model` 注册一个继承 `AtomicModel` 的类，实现五接口即可。

放入后重启容器使其生效：

```bash
docker compose restart
```

> 镜像自带的示例大气阻力模型已通过 `SCSIM_MODEL_DIRS=/app/backend/examples/models`
> 默认加载，与本目录互不冲突。
