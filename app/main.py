"""API REST del orquestador multi-agente de Supermercados del Valle.

Endpoints:
    POST /tasks                 encola una pregunta y devuelve un job_id (no espera al grafo)
    GET  /tasks/{job_id}        estado del job: PENDING / RUNNING / WAITING_APPROVAL / DONE / FAILED
    POST /tasks/{job_id}/approve  aprueba o rechaza la acción crítica (ver app/hitl.py)
    GET  /health                chequea la conexión con Redis

Levantar:  uvicorn app.main:app
"""

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field
from redis.asyncio import Redis
from redis.exceptions import ConnectionError as RedisConnectionError

from app import config
from app.observability import configurar_observabilidad, vaciar_trazas
from app.graph import construir_grafo, crear_checkpointer
from app.hitl import router as router_hitl
from app.jobs import Estado, crear_job, leer_job
from app.worker import worker_loop


@asynccontextmanager
async def lifespan(app: FastAPI):
    configurar_observabilidad()

    r = Redis.from_url(config.REDIS_URL, decode_responses=True)
    try:
        await r.ping()
    except RedisConnectionError:
        raise RuntimeError(
            f"No se pudo conectar a Redis en {config.REDIS_URL}. "
            "Levantalo con: docker compose up -d redis"
        ) from None

    # setup() del checkpointer es sincrónico: lo corro en un hilo para no bloquear el event loop.
    grafo = construir_grafo(await asyncio.to_thread(crear_checkpointer))
    app.state.redis = r

    workers = [asyncio.create_task(worker_loop(f"worker-{i}", grafo, r)) for i in range(config.WORKERS)]
    config.logger.info("API lista con %d workers", len(workers))
    yield

    for tarea in workers:
        tarea.cancel()
    await asyncio.gather(*workers, return_exceptions=True)
    await asyncio.to_thread(vaciar_trazas)
    await r.aclose()


app = FastAPI(title="Supermercados del Valle - Orquestador multi-agente", lifespan=lifespan)
app.include_router(router_hitl)


class Tarea(BaseModel):
    """Pedido del usuario."""

    pregunta: str = Field(min_length=5, max_length=2000, description="Pregunta o pedido para el equipo de agentes.")


@app.post("/tasks", status_code=202)
async def crear_tarea(tarea: Tarea, request: Request) -> dict:
    """Encola la tarea y responde enseguida con el job_id (202 Accepted)."""
    job_id = await crear_job(request.app.state.redis, tarea.pregunta)
    return {"job_id": job_id, "estado": Estado.PENDING}


@app.get("/tasks/{job_id}")
async def ver_tarea(job_id: str, request: Request) -> dict:
    job = await leer_job(request.app.state.redis, job_id)
    if job is None:
        raise HTTPException(404, f"No existe la tarea {job_id}")
    return job


@app.get("/health")
async def health(request: Request) -> dict:
    await request.app.state.redis.ping()
    return {"estado": "ok"}
