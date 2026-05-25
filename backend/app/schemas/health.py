from pydantic import BaseModel


class HealthStatus(BaseModel):
    status: str
    services: dict[str, str]


class HealthResponse(BaseModel):
    data: HealthStatus

