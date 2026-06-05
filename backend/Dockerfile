# 基础镜像：python:3.11-slim (官方多架构镜像)
# 支持架构：linux/amd64, linux/arm64, linux/arm/v7 等
# 验证命令：docker pull --platform linux/arm64 python:3.11-slim
FROM python:3.11-slim AS builder

WORKDIR /build

# 使用阿里云PyPI镜像加速
RUN pip config set global.index-url https://mirrors.aliyun.com/pypi/simple/ && \
    pip config set global.trusted-host mirrors.aliyun.com

# 安装依赖到独立目录（编译阶段）
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# --- 运行阶段 ---
FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# 从编译阶段复制已安装的依赖
COPY --from=builder /install /usr/local

# 复制源代码
COPY src/ ./src/

# 创建必要目录
RUN mkdir -p logs /data/fonts /data/output

ENTRYPOINT ["python", "-m", "src.main"]
CMD ["--help"]
