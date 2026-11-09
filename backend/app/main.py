from fastapi import FastAPI, HTTPException, status

from app.config import get_settings
from app.db import check_database

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
