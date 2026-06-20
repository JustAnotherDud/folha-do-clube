# -*- coding: utf-8 -*-
"""comum.py — utilitários partilhados por scrape.py e make_data.py.

Centraliza o que antes estava duplicado nos dois scripts:
- parsing de datas no formato do Strava ("Jul 10, 2025")
- normalização do campo "tempo" (vinha misto: "25s" / "2:29" / "1:20:16")
- lookup de cidade/país por segmento, com cache em disco (localizacoes.json)

A localização não precisa de sessão/cookie: a página pública
/segments/<id> devolve sempre uma wall de login quando não autenticado,
mas o <title> já inclui "... Segment in Cidade, País" mesmo assim.
Só dá cidade + país (sem distrito) — Strava não expõe distrito aqui.
"""
import json
import re
import time
from datetime import date
from pathlib import Path

import requests

MESES = {"Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
         "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12}

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
           "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36"}

CACHE_LOCAIS = Path(__file__).parent / "localizacoes.json"
CACHE_SEGS   = Path(__file__).parent / "segmentos.json"
LOCAL_DELAY  = 1.0   # segundos entre pedidos a /segments/<id>
API_DELAY    = 0.3   # segundos entre pedidos à API v3


def iso_date(s):
    m = re.match(r"([A-Za-z]{3})\w* (\d+), (\d+)", s.strip())
    return (date(int(m.group(3)), MESES[m.group(1)[:3]], int(m.group(2))).isoformat()
            if m else s)


def parse_tempo(s):
    """'25s' / '2:29' / '1:20:16' -> segundos totais (int)."""
    s = s.strip()
    if s.endswith("s") and ":" not in s:
        return int(s[:-1])
    partes = [int(p) for p in s.split(":")]
    while len(partes) < 3:
        partes.insert(0, 0)
    h, m, sec = partes
    return h * 3600 + m * 60 + sec


def format_tempo(segundos):
    """segundos totais -> 'M:SS' ou 'H:MM:SS' — formato único, sem 'Ns'."""
    h, resto = divmod(int(segundos), 3600)
    m, s = divmod(resto, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def normalizar_tempo(s):
    return format_tempo(parse_tempo(s))


def extrair_seg_id(url):
    m = re.search(r"/segments/(\d+)", url)
    return m.group(1) if m else None


def _carregar_cache():
    if CACHE_LOCAIS.exists():
        return json.loads(CACHE_LOCAIS.read_text(encoding="utf-8"))
    return {}


def _guardar_cache(cache):
    CACHE_LOCAIS.write_text(json.dumps(cache, ensure_ascii=False, indent=1, sort_keys=True),
                             encoding="utf-8")


def _carregar_cache_segs():
    if CACHE_SEGS.exists():
        return json.loads(CACHE_SEGS.read_text(encoding="utf-8"))
    return {}


def _guardar_cache_segs(cache):
    CACHE_SEGS.write_text(json.dumps(cache, ensure_ascii=False, indent=1, sort_keys=True),
                          encoding="utf-8")


def buscar_detalhes_segmentos(seg_ids, access_token):
    """
    Devolve {seg_id: {"elev_gain": m, "avg_grade": %, "climb_cat": 0-5}}
    via API v3 (requer access_token OAuth). Usa cache em segmentos.json.
    """
    cache = _carregar_cache_segs()
    novos = 0
    for sid in seg_ids:
        if sid in cache:
            continue
        try:
            r = requests.get(f"https://www.strava.com/api/v3/segments/{sid}",
                             headers={"Authorization": f"Bearer {access_token}"},
                             timeout=30)
            r.raise_for_status()
            d = r.json()
            cache[sid] = {
                "elev_gain":  round(d.get("total_elevation_gain", 0)),
                "avg_grade":  round(d.get("average_grade", 0), 1),
                "climb_cat":  d.get("climb_category", 0),
            }
        except requests.RequestException:
            cache[sid] = {"elev_gain": 0, "avg_grade": 0, "climb_cat": 0}
        novos += 1
        time.sleep(API_DELAY)
    if novos:
        _guardar_cache_segs(cache)
        print(f"  detalhes: {novos} segmento(s) consultados via API "
              f"({len(cache)} no cache total).")
    return cache


def localizar_segmentos(seg_ids, sessao=None):
    """
    Devolve {seg_id: {"cidade": ..., "pais": ...}} para todos os ids pedidos.
    Usa cache em disco (localizacoes.json) — só pede à Strava os ids que
    ainda não tem. Não precisa de cookie de sessão.
    """
    cache = _carregar_cache()
    s = sessao or requests.Session()
    novos = 0
    for sid in seg_ids:
        if sid in cache:
            continue
        try:
            r = s.get(f"https://www.strava.com/segments/{sid}",
                      headers=HEADERS, timeout=30)
            r.raise_for_status()
            m = re.search(r"<title[^>]*>.*?Segment in ([^<]+)</title>", r.text, re.S)
            if m:
                local = m.group(1).strip()
                cidade, _, pais = local.rpartition(",")
                # nota: para localizações tipo "Cidade, Estado, País" isto
                # apanha só o último campo como país — não relevante p/ EU.
                cache[sid] = {"cidade": (cidade or local).strip(), "pais": pais.strip()}
            else:
                cache[sid] = {"cidade": "", "pais": ""}
        except requests.RequestException:
            cache[sid] = {"cidade": "", "pais": ""}
        novos += 1
        time.sleep(LOCAL_DELAY)
    if novos:
        _guardar_cache(cache)
        print(f"  localização: {novos} segmento(s) novo(s) consultados "
              f"({len(cache)} no cache total).")
    return cache
