from fastapi import FastAPI

app = FastAPI(title="PR Sentinel API")


@app.get("/")
def read_root():
    return {
        "status": "ok",
        "service": "pr-sentinel-backend"
    }


@app.get("/health")
def health_check():
    return {
        "healthy": True
    }