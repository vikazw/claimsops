import os
import time
from contextlib import asynccontextmanager, contextmanager

import psycopg2
from fastapi import FastAPI, HTTPException
from prometheus_fastapi_instrumentator import Instrumentator

DATABASE_URL = os.environ["DATABASE_URL"]           # missing -> KeyError -> exit 1 (drill 3)
READY_DELAY = float(os.getenv("READY_DELAY", "0"))  # slows readiness (drill 1)
_held = []                                          # memory for the OOM drill


@contextmanager
def db_cursor():
    conn = psycopg2.connect(DATABASE_URL, connect_timeout=2)
    try:
        with conn, conn.cursor() as cur:   # commits on success, rolls back on error
            yield cur
    finally:
        conn.close()


@asynccontextmanager
async def lifespan(app):
    with db_cursor() as cur:
        cur.execute(
            "CREATE TABLE IF NOT EXISTS claims ("
            "id SERIAL PRIMARY KEY, member TEXT NOT NULL, "
            "amount NUMERIC NOT NULL, status TEXT NOT NULL DEFAULT 'received')"
        )
    yield


app = FastAPI(title="claims-api", lifespan=lifespan)
Instrumentator().instrument(app).expose(app)        # request metrics at /metrics


@app.get("/healthz")
def healthz():
    """Liveness: is the process alive? Never checks the database."""
    return {"status": "alive"}


@app.get("/ready")
def ready():
    """Readiness: can this pod serve traffic right now? Checks the database."""
    time.sleep(READY_DELAY)
    try:
        with db_cursor() as cur:
            cur.execute("SELECT 1")
    except psycopg2.Error as exc:
        raise HTTPException(status_code=503, detail=f"database unavailable: {exc}")
    return {"status": "ready"}


@app.post("/claims", status_code=201)
def create_claim(member: str, amount: float):
    with db_cursor() as cur:
        cur.execute(
            "INSERT INTO claims (member, amount) VALUES (%s, %s) RETURNING id",
            (member, amount),
        )
        claim_id = cur.fetchone()[0]
    return {"id": claim_id, "member": member, "amount": amount, "status": "received"}


@app.get("/claims/{claim_id}")
def get_claim(claim_id: int):
    with db_cursor() as cur:
        cur.execute("SELECT id, member, amount, status FROM claims WHERE id = %s", (claim_id,))
        row = cur.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="claim not found")
    return {"id": row[0], "member": row[1], "amount": float(row[2]), "status": row[3]}


@app.post("/debug/leak")
def leak(mb: int = 50):
    """Holds memory on purpose, for the OOMKilled drill. Never ship this for real."""
    _held.append(b"x" * (mb * 1024 * 1024))
    return {"held_mb": len(_held) * mb}