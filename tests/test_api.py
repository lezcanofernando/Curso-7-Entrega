"""Tests de los endpoints de FastAPI (con Redis falso y sin workers)."""

import json

import httpx
import pytest

from app.jobs import COLA, Estado, actualizar_job
from app.main import app

pytestmark = pytest.mark.anyio


@pytest.fixture
async def cliente(redis_async):
    # Sin lifespan: no hace falta un Redis real ni se arrancan workers.
    app.state.redis = redis_async
    transporte = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transporte, base_url="http://test") as c:
        yield c


async def test_post_tasks_encola_y_devuelve_job_id(cliente, redis_async):
    respuesta = await cliente.post("/tasks", json={"pregunta": "¿Cómo está el precio de la leche?"})

    assert respuesta.status_code == 202
    cuerpo = respuesta.json()
    assert cuerpo["estado"] == "PENDING"
    mensaje = json.loads(await redis_async.lindex(COLA, 0))
    assert mensaje == {"job_id": cuerpo["job_id"], "tipo": "nueva", "pregunta": "¿Cómo está el precio de la leche?"}

    job = (await cliente.get(f"/tasks/{cuerpo['job_id']}")).json()
    assert job["estado"] == "PENDING"


async def test_post_tasks_valida_la_pregunta(cliente):
    assert (await cliente.post("/tasks", json={"pregunta": "hi"})).status_code == 422


async def test_get_tarea_inexistente_da_404(cliente):
    assert (await cliente.get("/tasks/no-existe")).status_code == 404


async def test_approve_solo_si_espera_aprobacion(cliente):
    job_id = (await cliente.post("/tasks", json={"pregunta": "Bajá el precio de la yerba"})).json()["job_id"]

    respuesta = await cliente.post(f"/tasks/{job_id}/approve", json={"aprobado": True})

    assert respuesta.status_code == 409


async def test_approve_encola_la_reanudacion(cliente, redis_async):
    await actualizar_job(redis_async, "job-1", estado=Estado.WAITING_APPROVAL, pregunta="x")

    respuesta = await cliente.post("/tasks/job-1/approve", json={"aprobado": False, "comentario": "no"})

    assert respuesta.status_code == 202
    assert respuesta.json()["estado"] == "PENDING"
    mensaje = json.loads(await redis_async.lindex(COLA, -1))
    assert mensaje == {"job_id": "job-1", "tipo": "reanudar", "respuesta": {"aprobado": False, "comentario": "no"}}
