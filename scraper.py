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


def _decodificar_base64(texto_codificado: str) -> str:
    """Decodifica um texto base64, completando o preenchimento (padding) que falta."""
    resto = len(texto_codificado) % 4
    preenchimento = (4 - resto) % 4
    texto_com_padding = texto_codificado + ("=" * preenchimento)
    return base64.b64decode(texto_com_padding).decode()


def _extrair_datas_originais(url_base: str) -> tuple[str, str]:
    """Pega o searchParams da URL, decodifica, e extrai as duas primeiras
    datas distintas encontradas (assumidas como ida e volta originais)."""
    qs = urllib.parse.urlparse(url_base).query
    params = urllib.parse.parse_qs(qs)
    if "searchParams" not in params:
        raise ValueError("A URL colada não tem um parâmetro 'searchParams'. Confirma que é a URL da página de resultado (decolar.com/.../results/...).")

    payload_encoded = params["searchParams"][0]
    payload_decoded = _decodificar_base64(payload_encoded)

    datas = DATE_RE.findall(payload_decoded)
    if len(datas) < 2:
        raise ValueError(f"Não encontrei duas datas no searchParams decodificado: {payload_decoded}")

    ida_original, volta_original = datas[0], datas[1]
    return ida_original, volta_original


def _montar_url_para_janela(url_base: str, ida_original: str, volta_original: str,
                             nova_ida: str, nova_volta: str) -> str:
    """Troca as datas dentro do searchParams (decodificando, substituindo
    o texto, e recodificando), mantendo o resto da URL intacto."""
    parsed = urllib.parse.urlparse(url_base)
    params = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)

    payload_encoded = params["searchParams"][0]
    payload_decoded = _decodificar_base64(payload_encoded)

    novo_payload = payload_decoded.replace(ida_original, nova_ida).replace(volta_original, nova_volta)
    novo_payload_b64 = base64.b64encode(novo_payload.encode()).decode()

    params["searchParams"] = [novo_payload_b64]

    nova_query = urllib.parse.urlencode(params, doseq=True, quote_via=urllib.parse.quote)
    nova_url = urllib.parse.urlunparse(parsed._replace(query=nova_query))
    return nova_url


def _extrair_preco(texto_pagina: str) -> float | None:
    m = PRICE_FINAL_RE.search(texto_pagina)
    if m:
        candidatos = [m.group(1)]
    else:
        candidatos = PRICE_ANY_RE.findall(texto_pagina)

    valores = []
    for c in candidatos:
        limpo = c.replace(".", "").replace(",", ".")
        try:
            valores.append(float(limpo))
        except ValueError:
            continue

    if not valores:
        return None
    # Se veio do padrão "Final", é um valor só (confiável).
    # Se veio do fallback genérico, usa o maior valor plausível como
    # estimativa do preço total do pacote.
    return valores[0] if m else max(valores)


def buscar_preco_janela(page, url_base: str, ida_original: str, volta_original: str,
                         data_ida: date, data_volta: date, limite_preco: float) -> ResultadoBusca:
    url = _montar_url_para_janela(
        url_base, ida_original, volta_original,
        data_ida.isoformat(), data_volta.isoformat(),
    )

    try:
        page.goto(url, timeout=60000, wait_until="domcontentloaded")
        try:
            # Espera a página realmente "assentar" (sem requisições pendentes).
            # Alguns sites nunca ficam 100% parados — nesse caso, seguimos
            # em frente mesmo assim, e a espera fixa abaixo cobre o resto.
            page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass
        page.wait_for_timeout(6000)  # tempo extra pro React renderizar o preço
    except Exception as e:
        return ResultadoBusca(
            data_ida=data_ida.isoformat(), data_volta=data_volta.isoformat(),
            preco=None, url=url, abaixo_do_limite=False,
            observacao=f"Falha ao carregar página: {e}",
        )

    texto = page.inner_text("body")
    preco = _extrair_preco(texto)

    print(f"DEBUG — Título da página: {page.title()!r}")
    print(f"DEBUG — Primeiros 300 caracteres do texto: {texto[:300]!r}")

    return ResultadoBusca(
        data_ida=data_ida.isoformat(), data_volta=data_volta.isoformat(),
        preco=preco, url=url,
        abaixo_do_limite=(preco is not None and preco < limite_preco),
        observacao="" if preco is not None else "Nenhum preço encontrado na página",
    )


def rodar_verificacao(url_base: str, data_inicio: date, dias_totais: int,
                       duracao: int, limite_preco: float,
                       delay_min_s: float = DELAY_MIN_S, delay_max_s: float = DELAY_MAX_S,
                       salvar_incrementalmente: bool = False, imprimir_progresso: bool = False) -> list[ResultadoBusca]:
    ida_original, volta_original = _extrair_datas_originais(url_base)
    janelas = gerar_janelas(data_inicio, dias_totais, duracao)
    resultados = []

    if salvar_incrementalmente:
        from historico import salvar_resultados  # import local pra evitar dependência circular

    with sync_playwright() as p:
        # headless=False de propósito: o site parece detectar e bloquear
        # o modo headless (todas as buscas em modo invisível retornaram
        # "nenhum preço encontrado", enquanto o modo visível funcionou).
        # Uma janela do Chrome vai aparecer e navegar sozinha — é esperado,
        # só não mexa nela enquanto estiver rodando.
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()

        for i, (ida, volta) in enumerate(janelas):
            if imprimir_progresso:
                print(f"[{i+1}/{len(janelas)}] Buscando ida={ida} volta={volta}...")

            resultado = buscar_preco_janela(
                page, url_base, ida_original, volta_original, ida, volta, limite_preco
            )
            resultados.append(resultado)

            if imprimir_progresso:
                if resultado.preco is not None:
                    marca = "✅ ABAIXO DO LIMITE" if resultado.abaixo_do_limite else ""
                    print(f"    -> R$ {resultado.preco:.2f} {marca}")
                else:
                    print(f"    -> Falhou: {resultado.observacao}")

            if salvar_incrementalmente:
                salvar_resultados([resultado])

            if i < len(janelas) - 1:
                espera = random.uniform(delay_min_s, delay_max_s)
                if imprimir_progresso:
                    print(f"    (aguardando {espera/60:.1f} min antes da próxima busca...)")
                time.sleep(espera)

        browser.close()

    return resultados
