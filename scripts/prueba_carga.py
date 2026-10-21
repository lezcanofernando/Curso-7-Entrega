"""Prueba de carga: envía 5 tareas CONCURRENTES a la API y espera a que terminen.

Uso (con la API levantada):
    python scripts/prueba_carga.py
    python scripts/prueba_carga.py --url http://localhost:8000

Muestra la latencia que vio el cliente para cada tarea y un p95 de referencia.
El p95 y el costo "oficiales" se leen en el dashboard de LangSmith (ver README).
"""

import argparse
import asyncio
import statistics
import time

import httpx

from cliente import esperar

PREGUNTAS = [
    "¿Qué opinan los clientes de nuestra yerba y estamos caros o baratos frente a la competencia?",
    "¿Cómo está el precio de la leche frente a la competencia? Quiero la diferencia en porcentaje.",
    "¿Qué dicen las reseñas sobre el aceite? Dame el porcentaje de reseñas positivas.",
    "¿Hay noticias del mercado sobre la yerba? Resumilas en dos líneas.",
    "Compará el precio de nuestro aceite con la competencia y decime si conviene revisarlo.",
]


async def una_tarea(cliente: httpx.AsyncClient, pregunta: str) -> dict:
    inicio = time.perf_counter()
    respuesta = (await cliente.post("/tasks", json={"pregunta": pregunta})).raise_for_status().json()
    job = await esperar(cliente, respuesta["job_id"])
    job["latencia_cliente_s"] = time.perf_counter() - inicio
    return job


async def main(url: str) -> None:
    async with httpx.AsyncClient(base_url=url, timeout=30) as cliente:
        print(f"Enviando {len(PREGUNTAS)} tareas concurrentes a {url} ...\n")
        inicio = time.perf_counter()
        jobs = await asyncio.gather(*(una_tarea(cliente, p) for p in PREGUNTAS))
        total = time.perf_counter() - inicio

    for job in jobs:
        print(f"{job['job_id'][:8]}  {job['estado']:<17} {job['latencia_cliente_s']:6.1f} s  {' -> '.join(job.get('recorrido', []))}")
        if job["estado"] == "FAILED":
            print(f"          error: {job['error']}")

    latencias = [j["latencia_cliente_s"] for j in jobs]
    p95 = statistics.quantiles(latencias, n=20, method="inclusive")[18]
    print(f"\nTiempo total: {total:.1f} s (si fuera secuencial sería ~{sum(latencias):.0f} s)")
    print(f"Latencia vista por el cliente: p50 = {statistics.median(latencias):.1f} s · p95 = {p95:.1f} s")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", default="http://localhost:8000")
    asyncio.run(main(parser.parse_args().url))
