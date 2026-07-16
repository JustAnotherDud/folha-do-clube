# -*- coding: utf-8 -*-
"""scrape_prs.py — extrai Best Efforts de corrida (Strava) e escreve prs.json.

Corre no GitHub Actions (cron diário) ou localmente:
    STRAVA_SESSION=<cookie _strava4_session> python scrape_prs.py

Fonte: widget "Best Efforts" na sidebar do perfil público de cada atleta
(https://www.strava.com/athletes/<id>), separador Run. NÃO é o "All-Time PRs"
(esse é preenchido à mão pelo próprio atleta, via botão "Add PR", e por isso
diverge do que a Strava calcula sozinha) — é a tabela calculada automaticamente
pela Strava a partir do histórico de corridas, a mesma que já usávamos à mão
na folha de cálculo do clube.

Quando se vê o perfil de outra pessoa (não o dono da sessão), a Strava
acrescenta uma 2ª coluna de tempos com a comparação do próprio utilizador
autenticado — por isso o parsing usa sempre a 1ª coluna de tempo (tds[1]),
nunca a 2ª (tds[2], que seria o Zé, não o atleta da página).

Não cobre bike: a Strava não tem um widget agregado de Best Efforts por
distância para Ride (só a "Power Curve", que é outra coisa) — ver README.

Falha com exit != 0 se a sessão expirou — renovar o secret STRAVA_SESSION
com um cookie fresco copiado do browser.
"""
import json
import os
import sys
import time
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

from comum import HEADERS, normalizar_tempo
from scrape import BASE, membros_clube

PAGE_DELAY = 1.5


def parse_best_efforts(html):
    """{"5K": "19:26", ...} a partir do perfil de um atleta. {} se não houver widget."""
    soup = BeautifulSoup(html, "html.parser")
    marcador = soup.select_one('span[data-glossary-term="definition-best-efforts"]')
    if not marcador:
        return {}
    tbody = marcador.find_parent("tbody")
    if not tbody:
        return {}
    resultado = {}
    for tr in tbody.find_all("tr")[1:]:   # [0] é a linha de título "Best Efforts"
        tds = tr.find_all("td")
        if len(tds) < 2:
            continue
        label = tds[0].get_text(strip=True)
        tempo_raw = tds[1].get_text(strip=True)
        if label and tempo_raw:
            resultado[label] = normalizar_tempo(tempo_raw)
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
        r = s.get(f"{BASE}/athletes/{athlete_id}", headers=HEADERS, timeout=30)
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
