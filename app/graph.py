"""Grafo principal: Supervisor + especialistas + aprobación humana + sintetizador."""

from langgraph.checkpoint.redis import RedisSaver
from langgraph.graph import END, START, StateGraph

from app.agents.analyst_agent import nodo_analista
from app.agents.executor_agent import nodo_ejecutor
from app.agents.research_agent import nodo_investigador
from app.config import REDIS_URL
from app.hitl import nodo_aprobacion_humana
from app.state import OrquestadorState
from app.supervisor import elegir_siguiente, nodo_sintetizador, nodo_supervisor


def crear_checkpointer() -> RedisSaver:
    """Checkpointer de LangGraph en Redis: guarda el estado del grafo después de cada nodo.

    Gracias a esto una tarea pausada (esperando aprobación) sobrevive a un reinicio de la API.
    """
    checkpointer = RedisSaver(redis_url=REDIS_URL)
    checkpointer.setup()  # crea los índices en Redis (la primera vez)
    return checkpointer


def construir_grafo(checkpointer=None):
    grafo = StateGraph(OrquestadorState)

    grafo.add_node("supervisor", nodo_supervisor)
    grafo.add_node("investigador", nodo_investigador)
    grafo.add_node("analista", nodo_analista)
    grafo.add_node("aprobacion_humana", nodo_aprobacion_humana)
    grafo.add_node("ejecutor", nodo_ejecutor)
    grafo.add_node("sintetizador", nodo_sintetizador)

    # Todo empieza en el supervisor
    grafo.add_edge(START, "supervisor")

    # El supervisor decide a quién mandar la tarea
    grafo.add_conditional_edges("supervisor", elegir_siguiente)

    # Los especialistas siempre le devuelven el control al supervisor.
    # aprobacion_humana no tiene aristas fijas: devuelve Command(goto="ejecutor" o "supervisor").
    grafo.add_edge("investigador", "supervisor")
    grafo.add_edge("analista", "supervisor")
    grafo.add_edge("ejecutor", "supervisor")

    grafo.add_edge("sintetizador", END)
    return grafo.compile(checkpointer=checkpointer)
