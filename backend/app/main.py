from fastapi import FastAPI, HTTPException, status

from app.config import get_settings
from app.db import check_database
from app.integration.api import router as integration_router
from app.interface_registry.api import router as interface_router
from app.realtime.routes import router as realtime_router

settings = get_settings()
app = FastAPI(title=settings.app_name, version="0.1.0")


@app.get("/health", tags=["system"])
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/database", tags=["system"])
async def database_health() -> dict[str, str]:
    try:
        await check_database()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database is unavailable",
        ) from exc
    return {"status": "ok"}


# 整合层（A 规划 + B 执行）与 C 的接口注册中心 / 实时事件
app.include_router(integration_router)
app.include_router(interface_router)
app.include_router(realtime_router)
