"""Tests del ruteo del supervisor, la condición de parada y la validación del entorno."""

import pytest
from langchain_core.messages import HumanMessage

from app import config, supervisor


def test_elegir_siguiente_mapea_a_nodos():
    assert supervisor.elegir_siguiente({"next_agent": "investigador"}) == "investigador"
    assert supervisor.elegir_siguiente({"next_agent": "analista"}) == "analista"
    assert supervisor.elegir_siguiente({"next_agent": "FINISH"}) == "sintetizador"


def test_ejecutor_siempre_pasa_por_aprobacion_humana():
    assert supervisor.elegir_siguiente({"next_agent": "ejecutor"}) == "aprobacion_humana"


class LLMQueNoDebeLlamarse:
    def invoke(self, *args, **kwargs):
        raise AssertionError("Con el límite alcanzado, el supervisor no debería llamar al LLM")


def test_supervisor_corta_al_llegar_a_max_pasos(monkeypatch):
    monkeypatch.setattr(supervisor, "llm_supervisor", LLMQueNoDebeLlamarse())
    estado = {"messages": [], "aportes": [], "pasos": config.MAX_PASOS}

    resultado = supervisor.nodo_supervisor(estado)

    assert resultado["next_agent"] == "FINISH"
    assert supervisor.elegir_siguiente(resultado) == "sintetizador"


class LLMQuePideEjecutorSinCambio:
    def invoke(self, *args, **kwargs):
        return supervisor.Decision(siguiente="ejecutor", instruccion="cambiar", motivo="x", cambio_precio=None)


def test_ejecutor_sin_cambio_concreto_termina(monkeypatch):
    monkeypatch.setattr(supervisor, "llm_supervisor", LLMQuePideEjecutorSinCambio())
    estado = {"messages": [HumanMessage("Bajá el precio de la yerba")], "aportes": [], "pasos": 0}

    resultado = supervisor.nodo_supervisor(estado)

    assert resultado["next_agent"] == "FINISH"
    assert resultado["cambio_precio"] is None


def test_validar_entorno_pide_langsmith_key_si_el_tracing_esta_activo(monkeypatch):
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="LANGSMITH_API_KEY"):
        config.validar_entorno()


def test_validar_entorno_falla_si_falta_la_api_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        config.validar_entorno()
