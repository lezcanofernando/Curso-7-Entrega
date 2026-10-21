"""Tests del worker: estados del job en Redis, incluido FAILED ante una excepción."""

import pytest

from app.agents.executor_agent import CLAVE_PRECIOS
from app.jobs import Estado, actualizar_job, leer_job
from app.worker import procesar

pytestmark = pytest.mark.anyio


class GrafoQueFalla:
    def invoke(self, *args, **kwargs):
        raise ValueError("se cayó el LLM")


async def test_si_el_grafo_falla_el_job_queda_failed(redis_async):
    await actualizar_job(redis_async, "job-1", estado=Estado.PENDING)

    await procesar({"job_id": "job-1", "tipo": "nueva", "pregunta": "hola"}, GrafoQueFalla(), redis_async)

    job = await leer_job(redis_async, "job-1")
    assert job["estado"] == "FAILED"
    assert "se cayó el LLM" in job["error"]


async def test_flujo_completo_con_aprobacion(grafo_de_prueba, redis_async, redis_sync):
    # 1) Tarea nueva: el grafo se pausa esperando aprobación.
    await procesar({"job_id": "job-2", "tipo": "nueva", "pregunta": "Bajá la yerba"}, grafo_de_prueba, redis_async)
    job = await leer_job(redis_async, "job-2")
    assert job["estado"] == "WAITING_APPROVAL"
    assert job["accion_pendiente"]["producto"] == "yerba"

    # 2) El humano aprueba: el worker reanuda el grafo desde el checkpoint.
    respuesta = {"aprobado": True, "comentario": ""}
    await procesar({"job_id": "job-2", "tipo": "reanudar", "respuesta": respuesta}, grafo_de_prueba, redis_async)
    job = await leer_job(redis_async, "job-2")
    assert job["estado"] == "DONE"
    assert job["resultado"] == "respuesta final"
    assert job["recorrido"] == ["ejecutor"]
    assert redis_sync.hget(CLAVE_PRECIOS, "yerba") == "4100.0"
