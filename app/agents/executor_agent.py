"""Ejecutor: aplica en el sistema el cambio de precio que propuso el supervisor.

Es la única parte del grafo con EFECTOS SECUNDARIOS (escribe en Redis el precio
vigente de la góndola). Por eso es una acción "crítica": en el grafo, antes de
llegar acá siempre se pasa por el nodo de aprobación humana (ver app/hitl.py).
"""

import json
from datetime import datetime, timezone

from langchain_core.messages import AIMessage
from langchain_core.tools import tool

from app import config
from app.config import medir_tiempo
from app.state import OrquestadorState

# Claves de Redis donde queda el efecto de la herramienta.
CLAVE_PRECIOS = "precios:supermercados_del_valle"  # hash producto -> precio vigente
CLAVE_AUDITORIA = "auditoria:precios"              # lista con cada cambio aplicado


@tool
def actualizar_precio(producto: str, nuevo_precio: float, motivo: str) -> dict:
    """Actualiza el precio vigente de un producto en Supermercados del Valle.

    Args:
        producto: nombre simple del producto en minúsculas (ej: "yerba").
        nuevo_precio: precio nuevo, mayor a cero.
        motivo: por qué se cambia el precio.
    """
    if nuevo_precio <= 0:
        raise ValueError(f"Precio inválido para {producto}: {nuevo_precio}")
    r = config.get_redis()
    anterior = r.hget(CLAVE_PRECIOS, producto)
    r.hset(CLAVE_PRECIOS, producto, nuevo_precio)
    registro = {
        "producto": producto,
        "precio_anterior": float(anterior) if anterior else None,
        "precio_nuevo": nuevo_precio,
        "motivo": motivo,
        "fecha": datetime.now(timezone.utc).isoformat(),
    }
    r.rpush(CLAVE_AUDITORIA, json.dumps(registro, ensure_ascii=False))
    return registro


@medir_tiempo("ejecutor")
def nodo_ejecutor(state: OrquestadorState) -> dict:
    """Nodo del grafo. No usa el LLM: solo ejecuta la herramienta con el cambio ya aprobado."""
    cambio = state["cambio_precio"]
    registro = actualizar_precio.invoke(dict(cambio))
    texto = f"Precio de {cambio['producto']} actualizado a ${cambio['nuevo_precio']:,.2f} (aprobado por un humano)."
    return {
        "aportes": [{"agente": "ejecutor", "instruccion": state["instruccion"], "resultado": f"{texto} Registro: {registro}"}],
        "messages": [AIMessage(texto, name="ejecutor")],
        "cambio_precio": None,
    }
