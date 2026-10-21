"""Supervisor (router + validación) y Sintetizador (respuesta final)."""

from typing import Literal

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from app import config
from app.config import get_llm, medir_tiempo
from app.state import OrquestadorState, formatear_aportes


class CambioPrecioPropuesto(BaseModel):
    """Cambio de precio que el supervisor quiere aplicar (requiere aprobación humana)."""

    producto: str = Field(description='Producto en minúsculas, ej. "yerba".')
    nuevo_precio: float = Field(description="Precio nuevo a aplicar, mayor a cero.")
    motivo: str = Field(description="Por qué se propone este precio, con los números del análisis.")


class Decision(BaseModel):
    """Respuesta estructurada del supervisor."""

    siguiente: Literal["investigador", "analista", "ejecutor", "FINISH"] = Field(
        description="Quién interviene ahora, o FINISH si la tarea está completa."
    )
    instruccion: str = Field(
        description="Tarea concreta para el especialista elegido. Vacío si es FINISH."
    )
    motivo: str = Field(description="Por qué tomaste esta decisión (una oración).")
    cambio_precio: CambioPrecioPropuesto | None = Field(
        default=None,
        description="Solo si siguiente es 'ejecutor': el cambio de precio a aplicar. Si no, null.",
    )


SUPERVISOR_PROMPT = """Sos el Supervisor de un equipo de agentes de Supermercados del Valle.
Dada la conversación actual, decidí quién debe intervenir ahora o si es momento de finalizar.

Especialistas disponibles:
- investigador: BUSCA datos en fuentes externas (reseñas de clientes, precios de la
  competencia, noticias del mercado). No hace cálculos.
- analista: PROCESA datos ya obtenidos (análisis de sentimiento, comparación de precios).
  No busca datos nuevos, así que solo puede trabajar después del investigador.
- ejecutor: APLICA un cambio de precio en el sistema. Es una acción CRÍTICA con efectos
  reales, así que antes un humano la aprueba o la rechaza. Elegilo solo si el usuario
  pidió explícitamente cambiar/ajustar un precio y el analista ya hizo la comparación.
  En ese caso completá `cambio_precio` con el producto y el precio nuevo.

Rúbrica de validación (para elegir FINISH TODAS deben cumplirse):
1. El investigador trajo datos concretos para cada parte del pedido del usuario.
2. Si el pedido requiere análisis o cálculos, el analista los hizo con esos datos y
   muestra números.
3. Los aportes no se contradicen entre sí. Si hay una contradicción o un dato faltante,
   mandá al especialista que corresponda con una instrucción que diga qué corregir.
4. Si el usuario pidió aplicar un cambio de precio, ya hay un aporte del ejecutor
   (cambio aplicado) o de aprobacion_humana (cambio rechazado). Si un humano rechazó el
   cambio, no lo vuelvas a proponer: finalizá informando el rechazo.

Reglas:
- Dale al especialista una instrucción concreta y autocontenida (él no ve el historial).
- No repitas una instrucción que ya se cumplió.
- Si un dato no existe en las fuentes, aceptalo como "no disponible" y no insistas.
- Nunca elijas ejecutor si el usuario solo pidió información o un análisis."""


SINTETIZADOR_PROMPT = """Sos el redactor final del equipo de Supermercados del Valle.
Con el pedido del usuario y los aportes de los especialistas, escribí una respuesta final
clara y breve en español. Usá solo la información de los aportes, sin inventar datos.
Terminá con una recomendación concreta."""


llm = get_llm()
llm_supervisor = llm.with_structured_output(Decision, method="json_schema")


@medir_tiempo("supervisor")
def nodo_supervisor(state: OrquestadorState) -> dict:
    pasos = state.get("pasos", 0)

    # Condición de parada dura: si se llegó al límite, se termina sí o sí.
    if pasos >= config.MAX_PASOS:
        return {
            "next_agent": "FINISH",
            "messages": [AIMessage(f"Límite de {config.MAX_PASOS} pasos alcanzado: finalizo.", name="supervisor")],
        }

    pedido = state["messages"][0].text
    contexto = (
        f"Pedido del usuario:\n{pedido}\n\n"
        f"Aportes de los especialistas hasta ahora:\n{formatear_aportes(state.get('aportes', []))}\n\n"
        f"Paso {pasos + 1} de {config.MAX_PASOS}."
    )
    decision: Decision = llm_supervisor.invoke([SystemMessage(SUPERVISOR_PROMPT), HumanMessage(contexto)])

    siguiente = decision.siguiente
    if siguiente == "ejecutor" and decision.cambio_precio is None:
        # Sin un cambio concreto no hay nada que aprobar ni ejecutar.
        siguiente = "FINISH"

    return {
        "next_agent": siguiente,
        "instruccion": decision.instruccion,
        "pasos": pasos + 1,
        "cambio_precio": decision.cambio_precio.model_dump() if siguiente == "ejecutor" else None,
        "messages": [AIMessage(f"-> {siguiente}: {decision.motivo}", name="supervisor")],
    }


def elegir_siguiente(state: OrquestadorState) -> Literal["investigador", "analista", "aprobacion_humana", "sintetizador"]:
    """Arista condicional: traduce la decisión del supervisor al nombre de un nodo.

    El ejecutor nunca se alcanza directo: primero pasa por la aprobación humana.
    """
    if state["next_agent"] == "FINISH":
        return "sintetizador"
    if state["next_agent"] == "ejecutor":
        return "aprobacion_humana"
    return state["next_agent"]


@medir_tiempo("sintetizador")
def nodo_sintetizador(state: OrquestadorState) -> dict:
    pedido = state["messages"][0].text
    contexto = f"Pedido del usuario:\n{pedido}\n\nAportes:\n{formatear_aportes(state['aportes'])}"
    respuesta = llm.invoke([SystemMessage(SINTETIZADOR_PROMPT), HumanMessage(contexto)])
    return {"messages": [AIMessage(respuesta.text, name="sintetizador")]}
