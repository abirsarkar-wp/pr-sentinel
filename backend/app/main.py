import logging

from fastapi import FastAPI

from app.webhooks import router as webhooks_router


logging.basicConfig(level=logging.INFO)


app = FastAPI(title="PR Sentinel API")

app.include_router(webhooks_router)


@app.get("/")
def read_root():
    return {
        "status": "ok",
        "service": "pr-sentinel-backend",
    }


@app.get("/health")
def health_check():
    return {
        "healthy": True,
    }