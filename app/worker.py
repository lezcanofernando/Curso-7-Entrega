"""Worker: saca tareas de la cola de Redis y ejecuta el grafo en segundo plano.

Ciclo de estados de un job:

    PENDING -> RUNNING -> DONE
                       -> WAITING_APPROVAL -> (POST /approve) -> PENDING -> RUNNING -> ...
                       -> FAILED  (si el grafo lanza una excepción)

El grafo es sincrónico (los agentes usan `invoke`), así que se corre en un hilo con
`asyncio.to_thread`. Así el event loop de FastAPI nunca se bloquea.

Por defecto la API arranca los workers adentro (ver app/main.py). También se pueden
correr como un proceso aparte:  python -m app.worker   (y la API con WORKERS=0).
"""

import asyncio
import json
import time

from langgraph.types import Command
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app import config
from app.config import logger
from app.jobs import COLA, Estado, actualizar_job
from app.observability import traceable


@traceable(name="tarea_orquestador", run_type="chain")
def ejecutar_grafo(grafo, entrada, cfg: dict) -> dict:
    """Corre (o reanuda) el grafo y resume cómo quedó. Es UNA traza en LangSmith por llamada."""
    salida = grafo.invoke(entrada, cfg)
    # Si el grafo se pausó en un interrupt(), invoke lo devuelve en la clave "__interrupt__".
    # (No uso get_state().interrupts: con RedisSaver viene vacío aunque el grafo esté pausado.)
    interrupciones = salida.get("__interrupt__")
    valores = grafo.get_state(cfg).values
    return {
        "resultado": valores["messages"][-1].text if valores.get("messages") else "",
        "recorrido": [a["agente"] for a in valores.get("aportes", [])],
        "interrupcion": interrupciones[0].value if interrupciones else None,
    }


async def procesar(mensaje: dict, grafo, r: Redis) -> None:
    """Procesa un mensaje de la cola. Nunca deja escapar una excepción: si algo falla,
    el job pasa a FAILED con el error, así el cliente no queda esperando para siempre."""
    job_id = mensaje["job_id"]
    # thread_id = job_id: el checkpointer guarda el estado de cada job por separado.
    cfg = {"configurable": {"thread_id": job_id}, "recursion_limit": 40}

    if mensaje["tipo"] == "reanudar":
        entrada = Command(resume=mensaje["respuesta"])
    else:
        entrada = {"messages": [("user", mensaje["pregunta"])]}

    await actualizar_job(r, job_id, estado=Estado.RUNNING)
    inicio = time.perf_counter()
    try:
        salida = await asyncio.to_thread(
            ejecutar_grafo, grafo, entrada, cfg,
            langsmith_extra={"metadata": {"job_id": job_id, "tipo": mensaje["tipo"]}},
        )
    except Exception as error:
        logger.exception("job %s FAILED", job_id)
        await actualizar_job(r, job_id, estado=Estado.FAILED, error=f"{type(error).__name__}: {error}")
        return

    duracion = time.perf_counter() - inicio
    if salida["interrupcion"]:
        logger.info("job %s WAITING_APPROVAL (%.2f s)", job_id, duracion)
        await actualizar_job(
            r, job_id, estado=Estado.WAITING_APPROVAL,
            accion_pendiente=salida["interrupcion"], recorrido=salida["recorrido"],
        )
    else:
        logger.info("job %s DONE (%.2f s)", job_id, duracion)
        await actualizar_job(
            r, job_id, estado=Estado.DONE,
            resultado=salida["resultado"], recorrido=salida["recorrido"], duracion_s=round(duracion, 2),
        )


async def worker_loop(nombre: str, grafo, r: Redis) -> None:
    """Bucle infinito: espera un mensaje en la cola (BLPOP) y lo procesa."""
    logger.info("%s esperando tareas", nombre)
    while True:
        try:
            # El timeout del BLPOP tiene que ser MENOR que el socket_timeout del cliente
            # (5 s por defecto en redis-py 8). Si no, redis-py lanza TimeoutError.
            item = await r.blpop([COLA], timeout=1)
        except RedisError:
            # Un corte de Redis no debe matar al worker: lo registro y reintento.
            logger.exception("%s: error leyendo la cola, reintento en 2 s", nombre)
            await asyncio.sleep(2)
            continue
        if item is None:
            continue  # no llegó nada en 1 s: vuelvo a esperar
        try:
            await procesar(json.loads(item[1]), grafo, r)
        except Exception:
            # Un mensaje roto no debe matar al worker.
            logger.exception("%s: no se pudo procesar el mensaje %s", nombre, item[1])


async def main() -> None:
    """Modo proceso aparte: python -m app.worker"""
    from app.graph import construir_grafo, crear_checkpointer
    from app.observability import configurar_observabilidad

    configurar_observabilidad()
    r = Redis.from_url(config.REDIS_URL, decode_responses=True)
    grafo = construir_grafo(await asyncio.to_thread(crear_checkpointer))
    cantidad = config.WORKERS or 5
    await asyncio.gather(*(worker_loop(f"worker-{i}", grafo, r) for i in range(cantidad)))


if __name__ == "__main__":
    asyncio.run(main())
