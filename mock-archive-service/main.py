"""mock-archive-service — Phase 4.5 演示用 mock 外部归档服务（PRD §18.2）。

行为：接收 POST /archive，把 body 写到 /data/archive/{flow_id}.json 文件。
不做鉴权 / 持久化策略 / 重排 — 仅为演示 AutoNode 调外部 HTTP API 模式。
"""

from __future__ import annotations

import json
import os
import pathlib

from fastapi import FastAPI, Request

DATA_DIR = pathlib.Path(os.environ.get("ARCHIVE_DATA_DIR", "/data/archive"))
# 启动时尝试 mkdir，失败延后到第一次写入（macOS 测试时 /data 只读，让用户用 ARCHIVE_DATA_DIR override）
try:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
except OSError:
    pass

app = FastAPI(title="mock-archive-service", version="0.1.0")


@app.post("/archive")
async def archive(req: Request) -> dict:
    DATA_DIR.mkdir(parents=True, exist_ok=True)  # 幂等保险
    body = await req.json()
    flow_id = body.get("flow_id") or "unknown"
    path = DATA_DIR / f"{flow_id}.json"
    path.write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"archived": True, "path": str(path), "size": path.stat().st_size}


@app.get("/health")
async def health() -> dict:
    return {"ok": True, "data_dir": str(DATA_DIR)}
