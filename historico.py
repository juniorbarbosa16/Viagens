"""
historico.py
------------
Grava cada rodada de verificação num CSV (data_verificacao, ida, volta,
preco, abaixo_do_limite). Um CSV simples, abre direto no Excel.
"""

import csv
import os
from datetime import datetime

CSV_PATH = os.path.join(os.path.dirname(__file__), "historico_precos.csv")

CAMPOS = ["data_verificacao", "data_ida", "data_volta", "preco", "abaixo_do_limite", "observacao"]


def salvar_resultados(resultados):
    arquivo_existe = os.path.exists(CSV_PATH)
    agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with open(CSV_PATH, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CAMPOS)
        if not arquivo_existe:
            writer.writeheader()

        for r in resultados:
            writer.writerow({
                "data_verificacao": agora,
                "data_ida": r.data_ida,
                "data_volta": r.data_volta,
                "preco": r.preco if r.preco is not None else "",
                "abaixo_do_limite": r.abaixo_do_limite,
                "observacao": r.observacao,
            })
