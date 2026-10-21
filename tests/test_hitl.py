"""Tests del Human-in-the-loop: el grafo se pausa antes del ejecutor y solo aplica
el cambio de precio si un humano lo aprueba."""

from langgraph.types import Command

from app.agents.executor_agent import CLAVE_AUDITORIA, CLAVE_PRECIOS

CFG = {"configurable": {"thread_id": "job-de-prueba"}}
PEDIDO = {"messages": [("user", "Bajá el precio de la yerba")]}


def test_el_grafo_se_pausa_antes_de_ejecutar(grafo_de_prueba, redis_sync):
    grafo_de_prueba.invoke(PEDIDO, CFG)

    estado = grafo_de_prueba.get_state(CFG)
    assert estado.next == ("aprobacion_humana",)
    assert estado.interrupts[0].value["producto"] == "yerba"
    assert estado.interrupts[0].value["nuevo_precio"] == 4100.0
    assert redis_sync.hget(CLAVE_PRECIOS, "yerba") is None  # todavía no se tocó nada


def test_si_se_aprueba_se_aplica_el_cambio(grafo_de_prueba, redis_sync):
    grafo_de_prueba.invoke(PEDIDO, CFG)
    grafo_de_prueba.invoke(Command(resume={"aprobado": True, "comentario": "ok"}), CFG)

    estado = grafo_de_prueba.get_state(CFG)
    assert estado.next == ()  # terminó
    assert redis_sync.hget(CLAVE_PRECIOS, "yerba") == "4100.0"
    assert redis_sync.llen(CLAVE_AUDITORIA) == 1
    assert [a["agente"] for a in estado.values["aportes"]] == ["ejecutor"]
    assert estado.values["messages"][-1].text == "respuesta final"


def test_si_se_rechaza_no_se_aplica_nada(grafo_de_prueba, redis_sync):
    grafo_de_prueba.invoke(PEDIDO, CFG)
    grafo_de_prueba.invoke(Command(resume={"aprobado": False, "comentario": "muy agresivo"}), CFG)

    estado = grafo_de_prueba.get_state(CFG)
    assert estado.next == ()
    assert redis_sync.hget(CLAVE_PRECIOS, "yerba") is None
    assert estado.values["aportes"][0]["agente"] == "aprobacion_humana"
    assert "RECHAZÓ" in estado.values["aportes"][0]["resultado"]
