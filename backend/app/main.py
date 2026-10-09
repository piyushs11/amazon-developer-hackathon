from fastapi import FastAPI

app = FastAPI(title="MCP Bridge")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
