"""Agente Investigador: busca información en fuentes externas.

Las "fuentes externas" son simuladas: viven en data/fuentes.json
(reseñas de clientes, precios de la competencia y noticias del mercado).
"""

import json
from pathlib import Path
from typing import Literal

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import tool
from langgraph.prebuilt import create_react_agent

from app.config import get_llm, medir_tiempo
from app.state import OrquestadorState

RUTA_FUENTES = Path(__file__).parents[2] / "data" / "fuentes.json"


def cargar_fuentes(ruta: Path = RUTA_FUENTES) -> list[dict]:
    """Lee las fuentes simuladas. Si el archivo falta, está roto o vacío, corta con un mensaje claro."""
    try:
        fuentes = json.loads(ruta.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise RuntimeError(f"No se encontró el archivo de fuentes: {ruta}") from None
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise RuntimeError(f"El archivo de fuentes {ruta} no es un JSON válido: {error}") from None
    if not fuentes:
        raise RuntimeError(f"El archivo de fuentes {ruta} está vacío: no hay nada para buscar.")
    return fuentes


FUENTES = cargar_fuentes()


@tool
def buscar_en_fuentes(
    producto: str,
    tipo: Literal["reseñas", "precios", "noticias", "todo"] = "todo",
) -> list[dict]:
    """Busca información sobre un producto en fuentes externas.

    Args:
        producto: nombre simple del producto en minúsculas (ej: "yerba", "leche", "aceite").
        tipo: qué buscar: "reseñas" (opiniones de clientes), "precios" (nuestro precio y
            el de la competencia), "noticias" (novedades del mercado) o "todo".

    Returns:
        Lista de resultados con la fuente y el texto encontrado. Lista vacía si no hay nada.
    """
    producto = producto.strip().lower()
    return [
        f for f in FUENTES
        if f["producto"] == producto and (tipo == "todo" or f["tipo"] == tipo)
    ]


PROMPT = """Sos el Investigador de Supermercados del Valle.
Tu único trabajo es BUSCAR datos con la herramienta `buscar_en_fuentes`.
- No analices ni hagas cálculos: eso lo hace otro agente.
- Devolvé los datos encontrados de forma ordenada y textual (citá la fuente de cada uno).
- Si no encontrás nada, decilo claramente. Nunca inventes datos."""

# Agente ReAct: el LLM decide cuándo llamar a la herramienta y cuándo responder.
agente = create_react_agent(get_llm(), tools=[buscar_en_fuentes], prompt=PROMPT)


@medir_tiempo("investigador")
def nodo_investigador(state: OrquestadorState) -> dict:
    """Nodo del grafo. El agente solo recibe la instrucción del supervisor,
    no todo el historial (así evitamos la "contaminación de contexto")."""
    resultado = agente.invoke({"messages": [HumanMessage(state["instruccion"])]})
    texto = resultado["messages"][-1].text
    return {
        "aportes": [{"agente": "investigador", "instruccion": state["instruccion"], "resultado": texto}],
        "messages": [AIMessage(texto, name="investigador")],
    }
