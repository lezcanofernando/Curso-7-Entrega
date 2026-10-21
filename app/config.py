"""Configuración compartida."""

import logging
import os
import time
from functools import wraps

import redis
from dotenv import load_dotenv
from langchain_anthropic import ChatAnthropic

load_dotenv()  # lee las variables del archivo .env

VARIABLES_REQUERIDAS = ["ANTHROPIC_API_KEY"]


def validar_entorno() -> None:
    """Falla al inicio, con un mensaje claro, si falta alguna variable de entorno."""
    faltantes = [v for v in VARIABLES_REQUERIDAS if not os.getenv(v)]
    # Si se pide trazar con LangSmith, la API key de LangSmith pasa a ser obligatoria.
    if os.getenv("LANGSMITH_TRACING", "").lower() == "true" and not os.getenv("LANGSMITH_API_KEY"):
        faltantes.append("LANGSMITH_API_KEY")
    if faltantes:
        raise RuntimeError(
            f"Faltan variables de entorno: {', '.join(faltantes)}. "
            "Copiá .env.example a .env y completalas."
        )


validar_entorno()

MODEL = os.getenv("MODEL", "claude-sonnet-5-5")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")

# Cuántas tareas se procesan a la vez (workers en segundo plano).
WORKERS = int(os.getenv("WORKERS", "5"))

# Máximo de decisiones del supervisor. Evita el "supervisor infinito".
MAX_PASOS = 8

# Logger propio: solo muestra nuestros mensajes (no los de cada request HTTP de las librerías).
logger = logging.getLogger("orquestador")
logger.setLevel(logging.INFO)
if not logger.handlers:  # evita handlers duplicados si el módulo se recarga
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S"))
    logger.addHandler(handler)


def get_llm() -> ChatAnthropic:
    # Todos los agentes usan este mismo LLM, así la configuración es igual en todos lados.
    return ChatAnthropic(model=MODEL)


def get_redis() -> redis.Redis:
    """Cliente de Redis sincrónico (lo usan las herramientas que corren dentro del grafo)."""
    return redis.Redis.from_url(REDIS_URL, decode_responses=True)


def medir_tiempo(nombre: str):
    """Decorador para los nodos del grafo: registra en el log cuánto tardó cada uno."""

    def decorador(funcion):
        @wraps(funcion)
        def envoltura(state):
            inicio = time.perf_counter()
            resultado = funcion(state)
            duracion = time.perf_counter() - inicio
            destino = f" -> {resultado['next_agent']}" if isinstance(resultado, dict) and "next_agent" in resultado else ""
            logger.info("nodo %s%s (%.2f s)", nombre, destino, duracion)
            return resultado

        return envoltura

    return decorador
