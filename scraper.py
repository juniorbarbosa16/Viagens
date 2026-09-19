"""
scraper.py
----------
Estratégia validada com o site real: em vez de tentar simular a
digitação de origem/destino/passageiros (frágil, o site é um app React
sem seletores estáveis), pedimos que o usuário faça UMA busca manual
no navegador normal (com a origem, destino, passageiros que quiser) e
cole aqui a URL do resultado. O script então troca só as datas dentro
dessa URL para cada janela de N dias, reaproveitando o restante
(origem, destino, nº de passageiros, sessão de busca).

Isso foi validado manualmente: trocar as datas no parâmetro
`searchParams` (mantendo o resto da URL, inclusive o `searchId` antigo)
retornou um resultado real e válido.
"""

import re
import random
import time
import base64
import urllib.parse
from datetime import date, timedelta
from dataclasses import dataclass

from playwright.sync_api import sync_playwright

DELAY_MIN_S = 5
DELAY_MAX_S = 15

DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")

# Tenta primeiro o padrão "Final 2 pessoas R$21.018"; se não achar,
# cai para o maior valor "R$ ..." encontrado na página como estimativa.
PRICE_FINAL_RE = re.compile(r"Final\s+\d+\s+pessoas?\s+R\$\s?([\d\.]+)", re.IGNORECASE)
PRICE_ANY_RE = re.compile(r"R\$\s?([\d\.]+,\d{2}|\d[\d\.]*)")


@dataclass
class ResultadoBusca:
    data_ida: str
    data_volta: str
    preco: float | None
    url: str
    abaixo_do_limite: bool
    observacao: str = ""


def gerar_janelas(data_inicio: date, dias_totais: int, duracao: int):
    """Gera pares (ida, volta) deslizando 1 dia por vez."""
    janelas = []
    for offset in range(dias_totais - duracao + 1):
        ida = data_inicio + timedelta(days=offset)
        volta = ida + timedelta(days=duracao)
        janelas.append((ida, volta))
    return janelas


def _extrair_datas_originais(url_base: str) -> tuple[str, str]:
    """Pega o searchParams da URL, decodifica, e extrai as duas primeiras
    datas distintas encontradas (assumidas como ida e volta originais)."""
    qs = urllib.parse.urlparse(url_base).query
    params = urllib.parse.parse_qs(qs)
    if "searchParams" not in params:
        raise ValueError("A URL colada não tem um parâmetro 'searchParams'. Confirma que é a URL da página de resultado (decolar.com/.../results/...).")

    payload_encoded = params["searchParams"][0]
    payload_decoded = base64.b64decode(payload_encoded + "=" *
