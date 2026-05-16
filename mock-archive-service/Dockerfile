# Phase 4.5 mock 归档服务（PRD §18.2）— 演示 AutoNode 调外部 HTTP API
FROM python:3.12-slim-bookworm

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY main.py /app/main.py

# 数据目录（docker-compose volume 挂载到此路径）
RUN mkdir -p /data/archive
VOLUME ["/data/archive"]

EXPOSE 5000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "5000"]
