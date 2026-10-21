"""Agente Analista: procesa los datos que trajo el Investigador.

Tiene dos herramientas: análisis de sentimiento y comparación de precios.
"""

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import tool
from langgraph.prebuilt import create_react_agent

from app.config import get_llm, medir_tiempo
from app.state import OrquestadorState

# Análisis de sentimiento simple por palabras clave (fácil de entender y de verificar).
POSITIVAS = {"buena", "bueno", "buen", "excelente", "rica", "rico", "fresca", "recomendable", "suave", "rinde"}
NEGATIVAS = {"mala", "malo", "malísima", "cara", "caro", "roto", "vencida", "falta", "nunca"}


@tool
def analizar_sentimiento(textos: list[str]) -> dict:
    """Clasifica cada texto como positivo, negativo o neutro y devuelve un resumen.

    Args:
        textos: lista de reseñas u opiniones (una por elemento).
    """
    detalle = []
    conteo = {"positivo": 0, "negativo": 0, "neutro": 0}
    for texto in textos:
        palabras = texto.lower().replace(",", " ").replace(".", " ").split()
        puntaje = sum(p in POSITIVAS for p in palabras) - sum(p in NEGATIVAS for p in palabras)
        etiqueta = "positivo" if puntaje > 0 else "negativo" if puntaje < 0 else "neutro"
        conteo[etiqueta] += 1
        detalle.append({"texto": texto, "puntaje": puntaje, "sentimiento": etiqueta})
    total = len(textos) or 1
    return {
        "detalle": detalle,
        "conteo": conteo,
        "porcentaje_positivo": round(100 * conteo["positivo"] / total, 1),
    }


@tool
def comparar_precios(nuestro_precio: float, precios_competencia: list[float]) -> dict:
    """Compara nuestro precio contra los precios de la competencia.

    Args:
        nuestro_precio: precio de Supermercados del Valle.
        precios_competencia: precios de los competidores.
    """
    promedio = sum(precios_competencia) / len(precios_competencia)
    return {
        "promedio_competencia": round(promedio, 2),
        "minimo_competencia": min(precios_competencia),
        "maximo_competencia": max(precios_competencia),
        "diferencia_vs_promedio_%": round(100 * (nuestro_precio - promedio) / promedio, 2),
    }


PROMPT = """Sos el Analista de Supermercados del Valle.
Recibís datos ya buscados por el Investigador y los procesás con tus herramientas:
- `analizar_sentimiento` para reseñas u opiniones.
- `comparar_precios` para precios.
No busques información nueva ni inventes datos: usá solo los que te pasan.
Respondé con los resultados numéricos y una conclusión breve."""

agente = create_react_agent(get_llm(), tools=[analizar_sentimiento, comparar_precios], prompt=PROMPT)


@medir_tiempo("analista")
def nodo_analista(state: OrquestadorState) -> dict:
    """Nodo del grafo. Recibe la instrucción del supervisor + SOLO los datos del
    investigador (no los mensajes del supervisor ni el resto del historial)."""
    datos = "\n\n".join(a["resultado"] for a in state["aportes"] if a["agente"] == "investigador")
    pedido = f"{state['instruccion']}\n\nDatos del investigador:\n{datos or '(sin datos)'}"
    resultado = agente.invoke({"messages": [HumanMessage(pedido)]})
    texto = resultado["messages"][-1].text
    return {
        "aportes": [{"agente": "analista", "instruccion": state["instruccion"], "resultado": texto}],
        "messages": [AIMessage(texto, name="analista")],
    }
