"""Funciones comunes de los scripts: consultar una tarea hasta que cambie de estado."""

import asyncio
import time

import httpx

ESTADOS_FINALES = {"DONE", "FAILED", "WAITING_APPROVAL"}


async def esperar(cliente: httpx.AsyncClient, job_id: str, timeout_s: float = 600, cada_s: float = 2) -> dict:
    """Hace polling a GET /tasks/{job_id} hasta que el job llegue a DONE, FAILED o WAITING_APPROVAL."""
    limite = time.monotonic() + timeout_s
    while time.monotonic() < limite:
        job = (await cliente.get(f"/tasks/{job_id}")).raise_for_status().json()
        if job["estado"] in ESTADOS_FINALES:
            return job
        await asyncio.sleep(cada_s)
    raise TimeoutError(f"La tarea {job_id} no terminó en {timeout_s} s")
