"""全局 exception handler — 把所有未捕获异常包成 envelope。

注意：不能泄露 stacktrace 到前端；要写日志 + 返回 generic message。
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .envelope import err

logger = logging.getLogger(__name__)


def register_exception_handlers(app: FastAPI) -> None:
    """注册全局 exception handler。"""

    @app.exception_handler(StarletteHTTPException)
    async def http_exc_handler(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=err(str(exc.detail), meta={"status_code": exc.status_code}),
        )

    @app.exception_handler(HTTPException)
    async def fastapi_http_exc_handler(_: Request, exc: HTTPException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=err(str(exc.detail), meta={"status_code": exc.status_code}),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content=err("请求参数校验失败", meta={"errors": exc.errors()}),
        )

    @app.exception_handler(Exception)
    async def generic_handler(req: Request, exc: Exception) -> JSONResponse:
        logger.exception("[unhandled] %s %s — %s", req.method, req.url.path, exc)
        return JSONResponse(
            status_code=500,
            content=err("服务器内部错误，请稍后重试"),
        )
