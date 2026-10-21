"""Tests de las herramientas de los agentes y de la carga de datos."""

import pytest

from app.agents.analyst_agent import analizar_sentimiento, comparar_precios
from app.agents.research_agent import buscar_en_fuentes, cargar_fuentes


# ---------- Investigador ----------

def test_buscar_precios_de_yerba():
    resultados = buscar_en_fuentes.invoke({"producto": "yerba", "tipo": "precios"})
    assert len(resultados) == 4
    assert all(r["tipo"] == "precios" for r in resultados)


def test_buscar_todo_trae_varios_tipos():
    resultados = buscar_en_fuentes.invoke({"producto": "yerba"})
    assert {r["tipo"] for r in resultados} == {"reseñas", "precios", "noticias"}


def test_buscar_normaliza_mayusculas_y_espacios():
    assert buscar_en_fuentes.invoke({"producto": "  Leche ", "tipo": "reseñas"})


def test_buscar_producto_inexistente_devuelve_lista_vacia():
    assert buscar_en_fuentes.invoke({"producto": "caviar"}) == []


# ---------- Analista ----------

def test_sentimiento_clasifica_positivo_negativo_y_neutro():
    resultado = analizar_sentimiento.invoke({"textos": [
        "Excelente yerba, muy buena.",
        "La leche llegó vencida, malísima.",
        "Compré un paquete.",
    ]})
    etiquetas = [d["sentimiento"] for d in resultado["detalle"]]
    assert etiquetas == ["positivo", "negativo", "neutro"]
    assert resultado["porcentaje_positivo"] == 33.3


def test_sentimiento_lista_vacia_no_falla():
    assert analizar_sentimiento.invoke({"textos": []})["porcentaje_positivo"] == 0


def test_comparar_precios():
    resultado = comparar_precios.invoke({"nuestro_precio": 4200, "precios_competencia": [3900, 4500, 4000]})
    assert resultado["promedio_competencia"] == 4133.33
    assert resultado["minimo_competencia"] == 3900
    assert resultado["maximo_competencia"] == 4500
    assert resultado["diferencia_vs_promedio_%"] == 1.61


# ---------- Carga de data/ ----------

def test_cargar_fuentes_archivo_inexistente(tmp_path):
    with pytest.raises(RuntimeError, match="No se encontró"):
        cargar_fuentes(tmp_path / "no_existe.json")


def test_cargar_fuentes_json_invalido(tmp_path):
    ruta = tmp_path / "roto.json"
    ruta.write_text("{esto no es json", encoding="utf-8")
    with pytest.raises(RuntimeError, match="no es un JSON válido"):
        cargar_fuentes(ruta)


def test_cargar_fuentes_vacio(tmp_path):
    ruta = tmp_path / "vacio.json"
    ruta.write_text("[]", encoding="utf-8")
    with pytest.raises(RuntimeError, match="está vacío"):
        cargar_fuentes(ruta)
