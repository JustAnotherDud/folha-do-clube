# -*- coding: utf-8 -*-
"""scrape_prs.py — extrai Best Efforts de corrida (Strava) e escreve prs.json.

Corre no GitHub Actions (cron diário) ou localmente:
    STRAVA_SESSION=<cookie _strava4_session> python scrape_prs.py

Fonte: widget "Best Efforts" da sidebar do perfil. O HTML da página
/athletes/<id> é uma app React — a tabela é preenchida por JS, por isso o
HTML servido não a contém. Os dados vêm de um endpoint AJAX à parte:

    /athletes/<id>/profile_sidebar_comparison?hl=en-GB

...que devolve um fragmento HTML já com a tabela, mas SÓ quando pedido com
o header X-Requested-With: XMLHttpRequest (sem ele devolve corpo vazio).
O hl=en-GB força labels em inglês ("Half-Marathon", "Best Efforts"),
independentemente da locale da conta — o parsing depende deles.

NÃO é o "All-Time PRs" (esse é preenchido à mão pelo próprio atleta, via
botão "Add PR", e diverge do que a Strava calcula) — é a tabela calculada
automaticamente a partir do histórico de corridas, a mesma que usávamos à
mão na folha de cálculo do clube.

Quando se vê o perfil de outra pessoa (não o dono da sessão), a Strava
acrescenta uma 2ª coluna de tempos com a comparação do próprio utilizador
autenticado — por isso o parsing usa sempre a 1ª coluna de tempo (tds[1]),
nunca a 2ª (tds[2], que seria o dono da sessão, não o atleta da página).
No perfil do próprio dono da sessão há só uma coluna, e tds[1] continua a
ser o tempo dele — logo a mesma regra serve nos dois casos.

Não cobre bike: a Strava não tem um widget agregado de Best Efforts por
distância para Ride (só a "Power Curve", que é outra coisa) — ver README.

Falha com exit != 0 se a sessão expirou — renovar o secret STRAVA_SESSION
com um cookie fresco copiado do browser.
"""
import json
import os
import re
import sys
import time
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

from comum import HEADERS, normalizar_tempo
from scrape import BASE, membros_clube

PAGE_DELAY = 1.5

# fragmento AJAX da sidebar; precisa do header XHR ou devolve corpo vazio
XHR_HEADERS = {**HEADERS, "X-Requested-With": "XMLHttpRequest",
               "Accept": "text/javascript, text/html, application/xml, text/xml, */*"}
SIDEBAR = "/athletes/{}/profile_sidebar_comparison?hl=en-GB"
# tempo válido: "1:03" (M:SS) ou "1:20:16" (H:MM:SS) — filtra linhas não-dados
TEMPO_RE = re.compile(r"^\d{1,2}(:\d{2}){1,2}$")


def parse_best_efforts(html):
    """{"5K": {"tempo": "19:26", "url": ".../activities/123"}, ...} do fragmento. {} se vazio."""
    soup = BeautifulSoup(html, "html.parser")
    marcador = soup.select_one('span[data-glossary-term="definition-best-efforts"]')
    if not marcador:
        return {}
    tbody = marcador.find_parent("tbody")
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
        # o tempo é um link para /activities/<id>/best-efforts — guardar a
        # actividade em si (sem o sufixo /best-efforts)
        url = ""
        a = cel.find("a", href=True)
        if a:
            m = re.search(r"/activities/(\d+)", a["href"])
            if m:
                url = f"{BASE}/activities/{m.group(1)}"
        resultado[label] = {"tempo": normalizar_tempo(tempo_raw), "url": url}
    return resultado


def main():
    cookie = os.environ.get("STRAVA_SESSION", "").strip()
    if not cookie:
        sys.exit("STRAVA_SESSION não definido.")
    s = requests.Session()
    s.cookies.set("_strava4_session", cookie, domain=".strava.com")

    atletas = membros_clube(s)
    print(f"{len(atletas)} membros: " + ", ".join(n for _, n in atletas))

    prs = {}
    for athlete_id, nome in atletas:
        r = s.get(BASE + SIDEBAR.format(athlete_id), headers=XHR_HEADERS, timeout=30)
        r.raise_for_status()
        if "/login" in r.url:
            sys.exit("Sessão expirada — renovar secret STRAVA_SESSION.")
        efforts = parse_best_efforts(r.text)
        if efforts:
            prs[nome] = efforts
            print(f"  {nome}: {len(efforts)} distâncias")
        else:
            print(f"  {nome}: sem Best Efforts (perfil privado ou sem corridas suficientes)")
        time.sleep(PAGE_DELAY)

    if not prs:
        sys.exit("0 atletas com Best Efforts — estrutura da página mudou ou bloqueio anti-bot.")

    out = {"gerado": datetime.now(timezone.utc).isoformat(timespec="minutes").replace("+00:00", "Z"),
           "atletas": prs}
    with open(os.path.join(os.path.dirname(__file__) or ".", "prs.json"),
              "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"{len(prs)} atleta(s) -> prs.json")


if __name__ == "__main__":
    main()
