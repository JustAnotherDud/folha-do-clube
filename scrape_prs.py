# -*- coding: utf-8 -*-
"""Lê os Best Efforts de corrida dos membros do clube e escreve prs.json.

    STRAVA_SESSION=<cookie _strava4_session> python scrape_prs.py

A página /athletes/<id> é React e não traz a tabela no HTML. Os dados vêm de
/athletes/<id>/profile_sidebar_comparison?hl=en-GB, que só responde com o
header X-Requested-With. O hl=en-GB fixa os labels em inglês.

O fragmento traz uma tabela por desporto: usamos a que tem "Run" seleccionado.
No perfil de outra pessoa a Strava junta uma 2.ª coluna com os tempos do dono
da sessão, por isso lemos sempre a 1.ª (tds[1]).

Actividades flagged (GPS bugado) dão tempos impossíveis e são descartadas.
O estado fica em cache em flagged.json.

Sai com erro se a sessão expirou.
"""
import re
import sys
import time

import requests
from bs4 import BeautifulSoup

from comum import HEADERS, get, gravar_cache, gravar_saida, ler_cache, normalizar_tempo, sessao
from scrape import BASE, PAGE_DELAY, membros_clube

XHR_HEADERS = {**HEADERS, "X-Requested-With": "XMLHttpRequest",
               "Accept": "text/javascript, text/html, application/xml, text/xml, */*"}
SIDEBAR = "/athletes/{}/profile_sidebar_comparison?hl=en-GB"
# tempo válido: "1:03" ou "1:20:16"; filtra linhas sem dados
TEMPO_RE = re.compile(r"^\d{1,2}(:\d{2}){1,2}$")


def _run_tbody(soup):
    """O <tbody> da tabela Best Efforts de corrida (separador 'Run' selected). None se não houver."""
    for marcador in soup.select('span[data-glossary-term="definition-best-efforts"]'):
        tabela = marcador.find_parent("table")
        if not tabela:
            continue
        sel = tabela.select_one('button[class*="sport-"][class*="selected"][title]')
        if sel and sel.get("title") == "Run":
            return marcador.find_parent("tbody")
    return None


def parse_best_efforts(html):
    """{"5K": {"tempo": "19:26", "act": "123"}, ...} do fragmento. {} se não houver corrida."""
    tbody = _run_tbody(BeautifulSoup(html, "html.parser"))
    if not tbody:
        return {}
    resultado = {}
    for tr in tbody.find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) < 2:
            continue                          # linha de título "Best Efforts" (só th)
        label = tds[0].get_text(strip=True)
        cel = tds[1]                          # 1ª coluna = atleta da página
        tempo_raw = cel.get_text(strip=True)
        if not (label and TEMPO_RE.match(tempo_raw)):
            continue
        # o tempo é um link para /activities/<id>/best-efforts
        act = ""
        a = cel.find("a", href=True)
        if a:
            m = re.search(r"/activities/(\d+)", a["href"])
            if m:
                act = m.group(1)
        resultado[label] = {"tempo": normalizar_tempo(tempo_raw), "act": act}
    return resultado


def actividades_flagged(s, act_ids):
    """{act_id: bool}, com cache em flagged.json. Em erro de rede assume não flagged."""
    cache = ler_cache("flagged.json")
    novos = 0
    for act in sorted(a for a in act_ids if a and a not in cache):
        try:
            r = s.get(f"{BASE}/activities/{act}", headers=HEADERS, timeout=30)
            cache[act] = ("inset flagged error" in r.text
                          or "This activity has been flagged" in r.text)
        except requests.RequestException:
            cache[act] = False
        novos += 1
        time.sleep(PAGE_DELAY)
    if novos:
        gravar_cache("flagged.json", cache)
        n_flag = sum(1 for a in act_ids if cache.get(a))
        print(f"  flagged: {novos} actividade(s) nova(s) consultada(s); "
              f"{n_flag} flagged nesta corrida ({len(cache)} no cache total).")
    return cache


def main():
    s = sessao()
    atletas = membros_clube(s)
    print(f"{len(atletas)} membros: " + ", ".join(n for _, n in atletas))

    # 1ª passagem: recolher os best efforts (com act_id) de cada atleta
    brutos = {}
    for athlete_id, nome in atletas:
        efforts = parse_best_efforts(get(s, BASE + SIDEBAR.format(athlete_id), XHR_HEADERS).text)
        if efforts:
            brutos[nome] = efforts
            print(f"  {nome}: {len(efforts)} distâncias")
        else:
            print(f"  {nome}: sem Best Efforts (não corre, perfil privado, ou sem corridas)")
        time.sleep(PAGE_DELAY)

    # descartar efforts de actividades flagged (GPS bugado -> tempos impossíveis)
    todas_act = {e["act"] for efs in brutos.values() for e in efs.values()}
    flagged = actividades_flagged(s, todas_act)

    prs = {}
    for nome, efforts in brutos.items():
        limpos = {label: {"tempo": e["tempo"],
                          "url": f"{BASE}/activities/{e['act']}" if e["act"] else ""}
                  for label, e in efforts.items() if not flagged.get(e["act"])}
        descartados = len(efforts) - len(limpos)
        if descartados:
            print(f"  {nome}: {descartados} effort(s) descartado(s) (actividade flagged)")
        if limpos:
            prs[nome] = limpos

    if not prs:
        sys.exit("0 atletas com Best Efforts — estrutura da página mudou ou bloqueio anti-bot.")

    gravar_saida("prs.json", "atletas", prs)
    print(f"{len(prs)} atleta(s) -> prs.json")


if __name__ == "__main__":
    main()
