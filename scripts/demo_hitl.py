"""Demo del Human-in-the-loop: una tarea crítica que se pausa hasta que la aprobás.

Uso (con la API levantada):
    python scripts/demo_hitl.py              # te pregunta por consola si aprobás
    python scripts/demo_hitl.py --aprobar    # aprueba sin preguntar
    python scripts/demo_hitl.py --rechazar   # rechaza sin preguntar
"""

import argparse
import asyncio
import json

import httpx

from cliente import esperar

PREGUNTA = (
    "Analizá cómo está nuestra yerba frente a la competencia y, si estamos más caros que "
    "el promedio, bajá el precio para quedar en el promedio."
)


async def main(url: str, decision: bool | None) -> None:
    async with httpx.AsyncClient(base_url=url, timeout=30) as cliente:
        job_id = (await cliente.post("/tasks", json={"pregunta": PREGUNTA})).raise_for_status().json()["job_id"]
        print(f"Tarea encolada: {job_id}\nEsperando a que el grafo llegue a la acción crítica...\n")

        job = await esperar(cliente, job_id)
        if job["estado"] != "WAITING_APPROVAL":
            print(f"La tarea terminó sin pedir aprobación (estado {job['estado']}).")
            return

        print("ACCIÓN PENDIENTE DE APROBACIÓN:")
        print(json.dumps(job["accion_pendiente"], indent=2, ensure_ascii=False))
        if decision is None:
            decision = input("\n¿Aprobás? [s/n]: ").strip().lower() == "s"

        await cliente.post(f"/tasks/{job_id}/approve", json={"aprobado": decision, "comentario": "demo"})
        print(f"\nEnviado: {'APROBADO' if decision else 'RECHAZADO'}. Esperando el resultado...\n")

        job = await esperar(cliente, job_id)
        print(f"Estado: {job['estado']}  ·  recorrido: {' -> '.join(job.get('recorrido', []))}\n")
        print(job.get("resultado") or job.get("error"))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", default="http://localhost:8000")
    grupo = parser.add_mutually_exclusive_group()
    grupo.add_argument("--aprobar", action="store_const", const=True, dest="decision")
    grupo.add_argument("--rechazar", action="store_const", const=False, dest="decision")
    args = parser.parse_args()
    asyncio.run(main(args.url, args.decision))
