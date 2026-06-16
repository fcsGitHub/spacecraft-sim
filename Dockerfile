# 空间飞行器仿真系统 —— 单阶段镜像（纯 Python + 静态前端，无构建步骤）
#
# 镜像内目录布局与本地一致：/app/backend 与 /app/frontend 为兄弟目录，
# 后端从 /app/backend 以 server.main:app 启动，前端由 FastAPI 托管。
# 可变运行数据经 SCSIM_DATA_DIR 重定向到 /app/data 卷，容器内自动播种种子。
FROM python:3.11-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    # 运行数据与回放写入卷，便于持久化与挂载
    SCSIM_DATA_DIR=/app/data \
    # 开箱即用加载示例外部模型（大气阻力），演示无侵入扩展；可在运行时覆盖
    SCSIM_MODEL_DIRS=/app/backend/examples/models \
    PORT=8000 \
    HOST=0.0.0.0

WORKDIR /app

# 仅先拷依赖清单，命中 Docker 层缓存（依赖未变则跳过重装）
COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install -r backend/requirements.txt

# 拷贝应用源码（后端 + 静态前端）
COPY backend/ ./backend/
COPY frontend/ ./frontend/

# 非 root 运行，并准备可写的数据卷目录
RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p "$SCSIM_DATA_DIR/recordings" "$SCSIM_DATA_DIR/models" \
    && chown -R appuser:appuser /app

VOLUME ["/app/data"]
EXPOSE 8000
USER appuser
WORKDIR /app/backend

# 健康检查：命中 /api/health（slim 镜像无 curl，用 stdlib urllib）
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import os,urllib.request,sys; \
url='http://127.0.0.1:%s/api/health' % os.environ.get('PORT','8000'); \
sys.exit(0 if urllib.request.urlopen(url, timeout=4).status==200 else 1)"

# exec 替换 shell，使 uvicorn 成为 PID 1，docker stop 的 SIGTERM 可触达，
# 走 FastAPI lifespan 优雅关闭（停推进循环、关外发连接）。HOST/PORT 可经环境变量覆盖。
CMD ["sh", "-c", "exec uvicorn server.main:app --host \"$HOST\" --port \"$PORT\""]
