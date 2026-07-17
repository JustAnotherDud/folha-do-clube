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

O fragmento traz uma tabela Best Efforts por desporto do atleta (Run, Ride,
...). Para ciclistas o default "selected" é Ride ("Longest Ride", efforts de
bike) — se apanhássemos a primeira tabela, o corredor ciclista ficava com
dados de bike ou sem dados. Por isso escolhemos a tabela cujo separador de
desporto "selected" tem title="Run".

Actividades com o GPS bugado ficam "flagged" no Strava e geram best efforts
impossíveis (ex.: 1/2 milha mais rápida que o ritmo de 5K). O Strava exclui-as
das leaderboards mas ainda as mostra nos best efforts do atleta — por isso
verificamos a página de cada actividade de origem e excluímos os efforts cuja
actividade esteja flagged. O estado fica em cache em flagged.json (só se busca
o que ainda não está lá; apagar uma entrada força reconsulta).

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
from pathlib import Path

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
CACHE_FLAGGED = Path(__file__).parent / "flagged.json"


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


def _carregar_flagged():
    if CACHE_FLAGGED.exists():
        return json.loads(CACHE_FLAGGED.read_text(encoding="utf-8"))
    return {}


def actividades_flagged(s, act_ids):
    """{act_id: bool} — actividade com GPS bugado ('flagged') no Strava. Usa cache em disco.

    Fail-open: em erro de rede assume não-flagged (não descarta effort legítimo)."""
    cache = _carregar_flagged()
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
        CACHE_FLAGGED.write_text(json.dumps(cache, ensure_ascii=False, indent=1, sort_keys=True),
                                 encoding="utf-8")
        n_flag = sum(1 for a in act_ids if cache.get(a))
        print(f"  flagged: {novos} actividade(s) nova(s) consultada(s); "
              f"{n_flag} flagged nesta corrida ({len(cache)} no cache total).")
    return cache


def main():
    cookie = os.environ.get("STRAVA_SESSION", "").strip()
    if not cookie:
        sys.exit("STRAVA_SESSION não definido.")
    s = requests.Session()
    s.cookies.set("_strava4_session", cookie, domain=".strava.com")

    atletas = membros_clube(s)
    print(f"{len(atletas)} membros: " + ", ".join(n for _, n in atletas))

    # 1ª passagem: recolher os best efforts (com act_id) de cada atleta
    brutos = {}
    for athlete_id, nome in atletas:
        r = s.get(BASE + SIDEBAR.format(athlete_id), headers=XHR_HEADERS, timeout=30)
        r.raise_for_status()
        if "/login" in r.url:
            sys.exit("Sessão expirada — renovar secret STRAVA_SESSION.")
        efforts = parse_best_efforts(r.text)
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

    out = {"gerado": datetime.now(timezone.utc).isoformat(timespec="minutes").replace("+00:00", "Z"),
           "atletas": prs}
    with open(os.path.join(os.path.dirname(__file__) or ".", "prs.json"),
              "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"{len(prs)} atleta(s) -> prs.json")


if __name__ == "__main__":
    main()
