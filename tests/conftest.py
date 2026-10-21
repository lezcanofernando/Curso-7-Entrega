"""Configuración de pytest.

Ningún test llama a la API de Anthropic ni necesita un Redis real:
- Ponemos una API key falsa para poder importar los módulos sin un .env real.
- Apagamos LangSmith para no enviar trazas desde los tests.
- Redis se reemplaza por `fakeredis` (un Redis en memoria).
"""

import os

import fakeredis
import pytest
from langchain_core.messages import AIMessage

os.environ.setdefault("ANTHROPIC_API_KEY", "clave-falsa-para-tests")
os.environ["LANGSMITH_TRACING"] = "false"  # load_dotenv no pisa variables ya definidas

from langgraph.checkpoint.memory import InMemorySaver  # noqa: E402

from app import config, graph  # noqa: E402  (después de definir las variables)

CAMBIO = {"producto": "yerba", "nuevo_precio": 4100.0, "motivo": "Quedar en el promedio de la competencia"}


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def redis_sync(monkeypatch):
    """Redis falso para la herramienta del ejecutor (cliente sincrónico)."""
    r = fakeredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(config, "get_redis", lambda: r)
    return r


@pytest.fixture
def redis_async():
    """Redis falso para la API y el worker (cliente asíncrono)."""
    return fakeredis.FakeAsyncRedis(decode_responses=True)


def supervisor_falso(state):
    """Primero propone un cambio de precio (acción crítica); después da FINISH."""
    if not state.get("aportes"):
        return {
            "next_agent": "ejecutor", "instruccion": "Bajar el precio de la yerba", "pasos": 1,
            "cambio_precio": CAMBIO,
            "messages": [AIMessage("-> ejecutor", name="supervisor")],
        }
    return {
        "next_agent": "FINISH", "instruccion": "", "pasos": 2,
        "cambio_precio": None, "messages": [AIMessage("-> FINISH", name="supervisor")],
    }


@pytest.fixture
def grafo_de_prueba(monkeypatch):
    """El grafo real, con el supervisor y el sintetizador reemplazados (no llaman al LLM)."""
    monkeypatch.setattr(graph, "nodo_supervisor", supervisor_falso)
    monkeypatch.setattr(graph, "nodo_sintetizador", lambda s: {"messages": [AIMessage("respuesta final", name="sintetizador")]})
    return graph.construir_grafo(InMemorySaver())
