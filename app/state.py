"""Estado compartido del orquestador.

Todos los nodos del grafo leen y escriben este mismo diccionario.
"""

import operator
from typing import Annotated

from langgraph.graph import MessagesState
from typing_extensions import TypedDict


class Aporte(TypedDict):
    """Lo que entregó un especialista en un turno."""

    agente: str       # "investigador", "analista", "aprobacion_humana" o "ejecutor"
    instruccion: str  # qué le pidió el supervisor
    resultado: str    # qué respondió el especialista


class CambioPrecio(TypedDict):
    """Acción crítica que propone el supervisor y que un humano debe aprobar."""

    producto: str        # ej. "yerba"
    nuevo_precio: float  # precio a aplicar en Supermercados del Valle
    motivo: str          # por qué se propone el cambio


class OrquestadorState(MessagesState):
    """Estado del grafo.

    Hereda `messages` de MessagesState (historial de la conversación) y suma:
    - next_agent: a quién eligió el supervisor ("investigador", "analista", "ejecutor" o "FINISH").
    - instruccion: la tarea concreta que el supervisor le da al especialista.
    - aportes: registro de qué agente contribuyó con qué. Usa `operator.add` como
      reducer, así cada especialista AGREGA su aporte a la lista en vez de pisarla.
    - pasos: cuántas decisiones tomó el supervisor (sirve para cortar bucles).
    - cambio_precio: el cambio de precio propuesto, que espera aprobación humana.
    """

    next_agent: str
    instruccion: str
    aportes: Annotated[list[Aporte], operator.add]
    pasos: int
    cambio_precio: CambioPrecio | None


def formatear_aportes(aportes: list[Aporte]) -> str:
    """Convierte la lista de aportes en texto para pasarle a un LLM."""
    if not aportes:
        return "(todavía no hay aportes)"
    bloques = []
    for i, aporte in enumerate(aportes, start=1):
        bloques.append(
            f"### Aporte {i} - {aporte['agente']}\n"
            f"Instrucción: {aporte['instruccion']}\n"
            f"Resultado:\n{aporte['resultado']}"
        )
    return "\n\n".join(bloques)
