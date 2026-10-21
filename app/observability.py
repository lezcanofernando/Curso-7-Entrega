"""Observabilidad con LangSmith.

LangSmith traza solo todo lo que corre con LangChain/LangGraph (cada nodo, cada
llamada al LLM con sus tokens y cada herramienta) cuando están estas variables:

    LANGSMITH_TRACING=true
    LANGSMITH_API_KEY=...
    LANGSMITH_PROJECT=supermercados-del-valle-e7

Además, con el decorador `traceable` envolvemos la ejecución completa de cada job
(ver app/worker.py), así cada tarea es UNA traza con el job_id en la metadata.
Con eso el dashboard calcula el costo por ejecución y la latencia de cada tarea.
"""

import os

from langchain_core.tracers.langchain import wait_for_all_tracers
from langsmith import traceable

from app.config import logger

__all__ = ["configurar_observabilidad", "traceable", "vaciar_trazas"]

# Se define al importar el módulo, antes de que se envíe cualquier traza.
os.environ.setdefault("LANGSMITH_PROJECT", "supermercados-del-valle-e7")


def configurar_observabilidad() -> bool:
    """Informa en el log si las trazas están activas. Devuelve True si lo están."""
    activa = os.getenv("LANGSMITH_TRACING", "").lower() == "true"
    if activa:
        logger.info("LangSmith activo: trazas en el proyecto '%s'", os.environ["LANGSMITH_PROJECT"])
    else:
        logger.warning("LangSmith desactivado: poné LANGSMITH_TRACING=true en el .env para enviar trazas")
    return activa


def vaciar_trazas() -> None:
    """Espera a que se terminen de enviar las trazas pendientes (al apagar la API)."""
    wait_for_all_tracers()
