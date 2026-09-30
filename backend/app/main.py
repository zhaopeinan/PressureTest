from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.runs import router
from app.config import settings

app = FastAPI(
    title="PressureTest Control API",
    description="Local Locust orchestration API. Only test systems you own or are authorized to test.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.get("/")
async def root() -> dict[str, str]:
    return {
        "name": "PressureTest",
        "docs": "/docs",
        "hint": "Open the frontend at http://localhost:5173",
    }
