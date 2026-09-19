"""
buscar_uma_janela.py
---------------------
Roda no GitHub Actions, disparado por cron a cada ~20 minutos. Cada
execução testa APENAS UMA janela (a próxima da lista), atualiza o
estado.json com qual foi a última testada, e sai. O ritmo de "uma a
cada 20 min" fica garantido pelo próprio agendamento do GitHub Actions,
não por um sleep() dentro do script — assim cada execução é curta e
não fica um runner preso rodando por horas.

Config vem de variáveis de ambiente (definidas no workflow .yml):
  URL_BASE, DATA_INICIO, DIAS_TOTAIS, DURACAO, LIMITE_PRECO
"""

import os
import json
from datetime import date, datetime

from scraper import gerar_janelas, _extrair_datas_originais, buscar_preco_janela
from historico import salvar_resultados
from playwright.sync_api import sync_playwright

ESTADO_PATH = os.path.join(os.path.dirname(__file__), "estado.json")


def carregar_estado():
    if os.path.exists(ESTADO_PATH):
        with open(ESTADO_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"proximo_offset": 0, "ciclo_iniciado_em": None}


def salvar_estado(estado):
    with open(ESTADO_PATH, "w", encoding="utf-8") as f:
        json.dump(estado, f, indent=2)


def carregar_config():
    config_path = os.path.join(os.path.dirname(__file__), "config.json")
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


def main():
    config = carregar_config()
    url_base = config["url_base"]
    data_inicio = datetime.strptime(config["data_inicio"], "%Y-%m-%d").date()
    dias_totais = int(config.get("dias_totais", 30))
    duracao = int(config.get("duracao", 8))
    limite_preco = float(config.get("limite_preco", 22000))

    janelas = gerar_janelas(data_inicio, dias_totais, duracao)
    estado = carregar_estado()
    offset = estado["proximo_offset"]

    if offset >= len(janelas):
        print(f"Ciclo completo: todas as {len(janelas)} janelas já foram testadas.")
        print("Pra rodar de novo, apague o estado.json ou mude DATA_INICIO no workflow.")
        return

    ida, volta = janelas[offset]
    print(f"Janela {offset + 1}/{len(janelas)}: ida={ida} volta={volta}")

    ida_original, volta_original = _extrair_datas_originais(url_base)

    with sync_playwright() as p:
        # headless=False + Xvfb (configurado no workflow) — o modo headless
        # puro é bloqueado pelo site, então simulamos uma tela virtual.
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()

        resultado = buscar_preco_janela(
            page, url_base, ida_original, volta_original, ida, volta, limite_preco
        )

        browser.close()

    print(f"Preço: {resultado.preco} | Abaixo do limite: {resultado.abaixo_do_limite} | {resultado.observacao}")

    salvar_resultados([resultado])

    estado["proximo_offset"] = offset + 1
    if estado["ciclo_iniciado_em"] is None:
        estado["ciclo_iniciado_em"] = datetime.now().isoformat()
    salvar_estado(estado)


if __name__ == "__main__":
    main()
