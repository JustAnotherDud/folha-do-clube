# -*- coding: utf-8 -*-
"""scrape_activities.py: extrai o feed de actividades do clube (Strava) e
escreve activities.json, só dos 5 atletas também seguidos no squadrats-club
(o clube "Nozes Velozes" tem 10 membros; os outros 5 não interessam a este
cruzamento).

Corre no GitHub Actions (cron diário) ou localmente:
    STRAVA_SESSION=<cookie _strava4_session> python scrape_activities.py

Fonte: /clubs/<club_id>/feed?club_id=<id>&feed_type=club&num_entries=N, a
mesma API JSON que alimenta a página "Recent Activity" do clube (React).
Não é HTML a raspar como o scrape.py, nem um fragmento AJAX como o
scrape_prs.py: é JSON estruturado directo (athlete/type/startDate/
elapsedTime/stats), mais barato e mais robusto do que os dois. Descoberto por
inspecção da sessão autenticada em 2026-09-12 (squadrats-club, investigação
"Actividades do clube"); não documentado publicamente pela Strava, por isso
fica aqui o essencial:
  - startDate vem em ISO-8601 UTC ao segundo (ex. "2026-09-10T21:44:09Z"),
    é o que interessa ao cruzamento com os snapshots do squadrats-club.
  - elapsedTime vem em segundos, já numérico: não precisa de parsing de
    "1h 5m" como o resto da folha.
  - distância e ritmo só vêm como texto com markup (stats[].value, ex.
    "15.15<abbr...> km</abbr>"): stat_one = distância, stat_two = ritmo/
    velocidade, stat_three = duração (mas essa já se tem em elapsedTime).

Paginação: o parâmetro `page` é ignorado (devolve sempre os mesmos N mais
recentes) e um `before`/`cursor` construído a partir do cursorData de cada
entrada (testado à mão) também não avançou a janela, fica por confirmar,
não vale a pena persegui-lo agora. Em vez disso, o script pede sempre as N
mais recentes do CLUBE INTEIRO e FUNDE com o activities.json já existente
por id, sem apagar entradas antigas. O histórico acumula-se corrida a
corrida, como o append_events.py do squadrats-club faz com os eventos.

Segunda fonte, feed de PERFIL: com 10 membros a competir pelas mesmas 20
vagas do feed de clube, quem posta menos fica diluído (num teste real, um
dos 5 atletas seguidos não apareceu nenhuma vez). O perfil de cada atleta
(/athletes/<id>) resolve isto: não tem endpoint /feed próprio (testei
várias combinações, 404 sempre), mas a própria página vem com um bloco
data-react-props (React hidratado no servidor) que já traz
appContext.preFetchedEntries, a MESMA forma de activity que o feed de
clube. A maioria das entradas pré-carregadas não são actividades (são
cartões de "Challenge", desafios/badges do Strava) -- filtra-se por
entity=="Activity". Sem paginação nenhuma (não há "ver mais" na página);
tipicamente só 1-4 actividades por atleta, mas cada um tem sempre a fatia
dele garantida, ao contrário do feed de clube. As duas fontes fundem-se no
mesmo activities.json, por id; sobreporem-se nalguma actividade não faz mal.

Cadência (2026-09-13): corre à parte do resto da folha, workflow próprio
(.github/workflows/update-activities.yml), 4x/dia -- não 1x/dia como o
scrape.py/scrape_prs.py. Medido no perfil do Pedro: 19 actividades em 4
semanas (~0,7/dia) mas 84% delas nunca chegavam a ser vistas com uma corrida
só por dia, porque a janela de cada fonte é pequena (feed de clube: ~2 vagas
por atleta, dividido por 10; feed de perfil: tipicamente 2-4, a maioria do
espaço ocupada por cartões de "Challenge"). A 4x/dia (de 6 em 6h) uma
actividade só se perde se o mesmo atleta postar mais actividades do que a
janela aguenta DENTRO de 6h, muito mais raro do que dentro de 24h. Continua
SEM paginação: não resolve o tecto de fundo, só encolhe a janela de perda.
Ver README para a análise completa (custo, porquê 4x, o que não resolve).

Falha com exit != 0 se a sessão expirou (mesmo critério do scrape.py).
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

from comum import HEADERS
from scrape import BASE

CLUBE_ID = "1238300"  # id numérico de /clubs/nozes; o /feed não aceita o slug
NUM_ENTRIES = 20
PAGE_DELAY = 1.5  # entre pedidos, mesmo valor do scrape.py/scrape_prs.py

# Strava athlete id -> nome, EXACTAMENTE os nomes de squadrats-club/data/
# squadrats.json (squadrats-club/pipeline/atletas.py é a fonte). Só estes 5
# dos 10 membros do clube interessam ao cruzamento com squadratinhos.
# Actualizar aqui se o roster do squadrats-club mudar.
ATLETAS_SQUADRATS = {
    "100300630": "Zé",
    "135219743": "Xeira",
    "135392048": "Carolina",
    "134981805": "Inês S.",
    "135494683": "Pedro",
}

OUT = Path(__file__).parent / "activities.json"
_NUM_RE = re.compile(r"^([\d.,]+)")   # "15.15<abbr...>" -> "15.15"
_TAG_RE = re.compile(r"<[^>]+>")      # tira markup de dentro de stats[].value


def _stat(stats, key):
    for s in stats:
        if s.get("key") == key:
            return s.get("value") or ""
    return ""


def _num(valor_html):
    m = _NUM_RE.match(valor_html.strip())
    return float(m.group(1).replace(",", "")) if m else None


def _texto(valor_html):
    return _TAG_RE.sub("", valor_html).strip()


def parse_entries(entries):
    """[{"activity": {...}}, ...] (a forma do /feed) -> linhas só dos 5
    atletas seguidos, já com os campos que o cruzamento e a página vão usar."""
    linhas = []
    for e in entries:
        a = e.get("activity") or {}
        athlete_id = (a.get("athlete") or {}).get("athleteId")
        nome = ATLETAS_SQUADRATS.get(athlete_id)
        if not nome or not a.get("id"):
            continue  # não é um dos 5, ou entrada sem forma (post/achievement solto)
        stats = a.get("stats") or []
        linhas.append({
            "id": str(a["id"]),
            "atleta": nome,
            "tipo": a.get("type", ""),
            "inicio": a.get("startDate", ""),   # ISO-8601 UTC
            "duracao_s": a.get("elapsedTime"),  # segundos
            "dist_km": _num(_stat(stats, "stat_one")),
            "ritmo": _texto(_stat(stats, "stat_two")),
        })
    return linhas


def buscar_feed(s, num_entries=NUM_ENTRIES):
    r = s.get(f"{BASE}/clubs/{CLUBE_ID}/feed",
               params={"club_id": CLUBE_ID, "feed_type": "club", "num_entries": num_entries},
               headers=HEADERS, timeout=30)
    r.raise_for_status()
    if "/login" in r.url:
        sys.exit("Sessão expirada — renovar secret STRAVA_SESSION.")
    try:
        dados = r.json()
    except ValueError:
        sys.exit("Resposta do feed não é JSON: a estrutura da API mudou?")
    return dados.get("entries", [])


def buscar_perfil_atividades(s, athlete_id):
    """Actividades reais (entity=="Activity") pré-carregadas na página de
    perfil do atleta. Sem endpoint /feed próprio: /athletes/<id>/feed dá 404
    com qualquer combinação de parâmetros que testei. Os dados vêm embutidos
    num atributo data-react-props (o mesmo mecanismo de hidratação React do
    resto do site), na forma {"activity": {...}} igual à do feed de clube.
    Devolve [] em silêncio se a página não tiver esse bloco (perfil privado,
    conta suspensa, estrutura mudou) -- um atleta sem correspondência aqui
    não deve travar os outros 4."""
    r = s.get(f"{BASE}/athletes/{athlete_id}", headers=HEADERS, timeout=30)
    r.raise_for_status()
    if "/login" in r.url:
        sys.exit("Sessão expirada: renovar secret STRAVA_SESSION.")
    soup = BeautifulSoup(r.text, "html.parser")
    tag = next((t for t in soup.select("[data-react-props]")
               if "startDate" in (t.get("data-react-props") or "")), None)
    if not tag:
        return []
    try:
        props = json.loads(tag["data-react-props"])
    except (KeyError, ValueError):
        return []
    entries = (props.get("appContext") or {}).get("preFetchedEntries") or []
    return [e for e in entries if e.get("entity") == "Activity"]


def fundir(antigas, novas):
    """Junta por id, a versão nova substitui a antiga (kudos/edições não
    interessam aqui, mas por segurança fica sempre a mais recente vista).
    Devolve (linhas fundidas, quantas eram mesmo novas)."""
    por_id = {l["id"]: l for l in antigas}
    n_novas = sum(1 for l in novas if l["id"] not in por_id)
    por_id.update({l["id"]: l for l in novas})
    linhas = sorted(por_id.values(), key=lambda l: l["inicio"], reverse=True)
    return linhas, n_novas


def main():
    cookie = os.environ.get("STRAVA_SESSION", "").strip()
    if not cookie:
        sys.exit("STRAVA_SESSION não definido.")
    s = requests.Session()
    s.cookies.set("_strava4_session", cookie, domain=".strava.com")

    do_clube = parse_entries(buscar_feed(s))
    print(f"feed de clube: {len(do_clube)} actividade(s) dos 5 seguidos")

    do_perfil = []
    for athlete_id, nome in ATLETAS_SQUADRATS.items():
        time.sleep(PAGE_DELAY)
        linhas_atleta = parse_entries(buscar_perfil_atividades(s, athlete_id))
        print(f"perfil de {nome}: {len(linhas_atleta)} actividade(s)")
        do_perfil += linhas_atleta

    # as duas fontes podem trazer a mesma actividade; por id, a última ganha
    novas = list({l["id"]: l for l in do_clube + do_perfil}.values())
    if not novas:
        sys.exit("0 actividades dos 5 atletas seguidos, nas duas fontes: API mudou ou sessão sem acesso.")

    antigas = []
    if OUT.exists():
        antigas = json.loads(OUT.read_text(encoding="utf-8")).get("linhas", [])

    linhas, n_novas = fundir(antigas, novas)
    out = {"gerado": datetime.now(timezone.utc).isoformat(timespec="minutes").replace("+00:00", "Z"),
           "linhas": linhas}
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(novas)} distintas nas duas fontes ({n_novas} nova(s) desde a última corrida), "
          f"{len(linhas)} no total -> {OUT.name}")


if __name__ == "__main__":
    main()
