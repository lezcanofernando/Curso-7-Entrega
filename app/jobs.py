"""Estado de los trabajos (jobs) y cola de tareas, guardados en Redis.

Cada job es un hash `job:{id}` con su estado y resultado. La cola es una lista de
Redis (`cola:tareas`): la API hace RPUSH y los workers hacen BLPOP.

Se usa el cliente ASÍNCRONO de Redis (`redis.asyncio`) para no bloquear el event loop.
"""

import json
import time
import uuid
from enum import StrEnum

from redis.asyncio import Redis

COLA = "cola:tareas"

# Campos del hash que se guardan como JSON (el resto son strings).
CAMPOS_JSON = {"accion_pendiente", "recorrido", "aprobacion"}


class Estado(StrEnum):
    PENDING = "PENDING"                    # en la cola, esperando un worker
    RUNNING = "RUNNING"                    # un worker está ejecutando el grafo
    WAITING_APPROVAL = "WAITING_APPROVAL"  # pausado: necesita aprobación humana
    DONE = "DONE"                          # terminó bien, hay resultado
    FAILED = "FAILED"                      # falló: el error queda en el campo `error`


def clave(job_id: str) -> str:
    return f"job:{job_id}"


async def actualizar_job(r: Redis, job_id: str, **campos) -> None:
    """Escribe solo los campos indicados (y la fecha de actualización)."""
    valores = {k: json.dumps(v, ensure_ascii=False) if k in CAMPOS_JSON else str(v) for k, v in campos.items()}
    valores["actualizado"] = str(time.time())
    await r.hset(clave(job_id), mapping=valores)


async def encolar(r: Redis, mensaje: dict) -> None:
    await r.rpush(COLA, json.dumps(mensaje, ensure_ascii=False))


async def crear_job(r: Redis, pregunta: str) -> str:
    """Registra el job como PENDING y lo pone en la cola. Devuelve el job_id."""
    job_id = uuid.uuid4().hex
    await actualizar_job(r, job_id, estado=Estado.PENDING, pregunta=pregunta, creado=time.time())
    await encolar(r, {"job_id": job_id, "tipo": "nueva", "pregunta": pregunta})
    return job_id


async def leer_job(r: Redis, job_id: str) -> dict | None:
    datos = await r.hgetall(clave(job_id))
    if not datos:
        return None
    job = {k: json.loads(v) if k in CAMPOS_JSON else v for k, v in datos.items()}
    job["job_id"] = job_id
    return job
