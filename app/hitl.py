"""Human-in-the-loop: pausa obligatoria antes de una acción crítica.

- `nodo_aprobacion_humana`: nodo del grafo. Llama a `interrupt()`, que PAUSA la
  ejecución y guarda el estado en el checkpointer de Redis. El grafo queda detenido
  hasta que alguien lo reanude con `Command(resume=...)`.
- `POST /tasks/{job_id}/approve`: endpoint donde el humano aprueba o rechaza. No
  ejecuta nada: encola un mensaje "reanudar" y un worker retoma el grafo.
"""

from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from langchain_core.messages import AIMessage
from langgraph.types import Command, interrupt
from pydantic import BaseModel, Field

from app.config import logger
from app.jobs import Estado, actualizar_job, encolar, leer_job
from app.state import OrquestadorState


def nodo_aprobacion_humana(state: OrquestadorState) -> Command[Literal["ejecutor", "supervisor"]]:
    """Pausa el grafo hasta que un humano apruebe o rechace el cambio de precio.

    Importante: al reanudar, LangGraph vuelve a correr este nodo desde el principio y
    `interrupt()` devuelve la respuesta del humano. Por eso acá no hay llamadas al LLM
    ni efectos secundarios antes del `interrupt()`.
    """
    cambio = state["cambio_precio"]
    respuesta = interrupt({
        "accion": "actualizar_precio",
        "producto": cambio["producto"],
        "nuevo_precio": cambio["nuevo_precio"],
        "motivo": cambio["motivo"],
        "pregunta": "¿Aprobás aplicar este cambio de precio?",
    })

    comentario = respuesta.get("comentario", "")
    if respuesta.get("aprobado"):
        logger.info("aprobación humana: APROBADO %s", cambio)
        return Command(
            goto="ejecutor",
            update={"messages": [AIMessage(f"Cambio aprobado por un humano. {comentario}".strip(), name="aprobacion_humana")]},
        )

    logger.info("aprobación humana: RECHAZADO %s", cambio)
    texto = f"Un humano RECHAZÓ el cambio de precio de {cambio['producto']} a {cambio['nuevo_precio']}. Comentario: {comentario or '(sin comentario)'}"
    return Command(
        goto="supervisor",
        update={
            "aportes": [{"agente": "aprobacion_humana", "instruccion": state["instruccion"], "resultado": texto}],
            "messages": [AIMessage(texto, name="aprobacion_humana")],
            "cambio_precio": None,
        },
    )


# ---------- Endpoint de aprobación ----------

router = APIRouter()


class Aprobacion(BaseModel):
    """Respuesta del humano a la acción pendiente."""

    aprobado: bool = Field(description="true para aplicar el cambio, false para rechazarlo.")
    comentario: str = Field(default="", description="Comentario opcional del revisor.")


@router.post("/tasks/{job_id}/approve", status_code=202)
async def aprobar_tarea(job_id: str, aprobacion: Aprobacion, request: Request) -> dict:
    r = request.app.state.redis
    job = await leer_job(r, job_id)
    if job is None:
        raise HTTPException(404, f"No existe la tarea {job_id}")
    if job["estado"] != Estado.WAITING_APPROVAL:
        raise HTTPException(409, f"La tarea no espera aprobación (estado actual: {job['estado']})")

    await actualizar_job(r, job_id, estado=Estado.PENDING, aprobacion=aprobacion.model_dump())
    await encolar(r, {"job_id": job_id, "tipo": "reanudar", "respuesta": aprobacion.model_dump()})
    return {"job_id": job_id, "estado": Estado.PENDING}
