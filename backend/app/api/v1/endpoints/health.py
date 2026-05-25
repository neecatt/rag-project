from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db, healthcheck_database, healthcheck_redis
from app.schemas.health import HealthResponse, HealthStatus

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
def get_health(db: Session = Depends(get_db)) -> HealthResponse:
    settings = get_settings()
    postgres_status = "ok" if healthcheck_database(db) else "error"
    redis_status = "ok" if healthcheck_redis(settings.redis_url) else ("not_configured" if not settings.redis_url else "error")
    overall_status = "ok" if postgres_status == "ok" and redis_status in {"ok", "not_configured"} else "degraded"
    payload = HealthStatus(
        status=overall_status,
        services={"api": "ok", "postgres": postgres_status, "redis": redis_status},
    )
    return HealthResponse(data=payload)
