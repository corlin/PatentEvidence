from fastapi import FastAPI


app = FastAPI(title="PatentEvidence API", version="0.1.0")


@app.get("/health")
async def health() -> dict[str, str]:
    """Report process health without probing external dependencies."""
    return {"service": "api", "status": "ok", "phase": "P0"}
