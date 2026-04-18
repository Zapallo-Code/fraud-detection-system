from fastapi import FastAPI

app = FastAPI(
    title="Fraud Detection Serving API",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
