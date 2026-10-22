"""Tests del worker: estados del job en Redis, incluido FAILED ante una excepción."""

import asyncio
from types import SimpleNamespace

import pytest
from langgraph.types import Interrupt
from redis.exceptions import TimeoutError

from app import worker
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


class GrafoPausadoComoRedisSaver:
    """Imita al RedisSaver: invoke devuelve "__interrupt__", pero get_state().interrupts viene vacío."""

    def invoke(self, entrada, cfg):
        return {"__interrupt__": [Interrupt(value={"accion": "actualizar_precio", "producto": "yerba"})]}

    def get_state(self, cfg):
        return SimpleNamespace(values={"messages": [], "aportes": []}, interrupts=())


async def test_detecta_la_pausa_aunque_get_state_no_la_muestre(redis_async):
    await procesar({"job_id": "job-4", "tipo": "nueva", "pregunta": "Bajá la yerba"}, GrafoPausadoComoRedisSaver(), redis_async)

    job = await leer_job(redis_async, "job-4")
    assert job["estado"] == "WAITING_APPROVAL"
    assert job["accion_pendiente"]["producto"] == "yerba"


class RedisInestable:
    """BLPOP que primero falla (como el TimeoutError de redis-py), después trae un
    mensaje y al final corta el bucle."""

    def __init__(self):
        self.respuestas = [TimeoutError("network:TimeoutError"), None, ("cola:tareas", '{"job_id": "job-3"}')]

    async def blpop(self, *args, **kwargs):
        if not self.respuestas:
            raise asyncio.CancelledError  # termina el bucle infinito del test
        respuesta = self.respuestas.pop(0)
        if isinstance(respuesta, Exception):
            raise respuesta
        return respuesta


async def test_el_worker_sobrevive_a_errores_de_redis(monkeypatch):
    procesados = []

    async def procesar_falso(mensaje, grafo, r):
        procesados.append(mensaje["job_id"])

    monkeypatch.setattr(worker, "procesar", procesar_falso)
    sleep_original = asyncio.sleep
    monkeypatch.setattr(asyncio, "sleep", lambda s: sleep_original(0))  # no esperar 2 s en el test

    with pytest.raises(asyncio.CancelledError):
        await worker.worker_loop("worker-test", grafo=None, r=RedisInestable())

    assert procesados == ["job-3"]  # siguió vivo después del error y procesó el mensaje


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
