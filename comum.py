# -*- coding: utf-8 -*-
"""Utilitários de scrape.py e scrape_prs.py: datas, tempos e localização dos segmentos."""
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
LOCAL_DELAY  = 1.0  # segundos entre pedidos a /segments/<id> (só para ids novos)

# Em Portugal o título vem muitas vezes "Cidade, Distrito", sem país.
DISTRITOS_PT = {
    "lisbon", "lisboa", "porto", "santarém", "santarem", "leiria", "braga",
    "aveiro", "setúbal", "setubal", "faro", "coimbra", "viseu",
    "viana do castelo", "vila real", "bragança", "braganca", "guarda",
    "castelo branco", "portalegre", "évora", "evora", "beja",
    "açores", "acores", "madeira",
}


def _normalizar_local(cidade, pais):
    """Se o 'país' for um distrito PT, o país é Portugal."""
    if pais.strip().lower() in DISTRITOS_PT:
        return cidade, "Portugal"
    return cidade, pais


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
    """segundos totais -> 'M:SS' ou 'H:MM:SS'."""
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


def localizar_segmentos(seg_ids, sessao=None):
    """{seg_id: {"cidade", "pais"}} para os ids pedidos, com cache em localizacoes.json.

    Não precisa de sessão: o <title> da página pública já traz "Segment in Cidade, País".
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
                # "Cidade, Estado, País" fica com cidade "Cidade, Estado"
                cidade, pais = _normalizar_local((cidade or local).strip(), pais.strip())
                cache[sid] = {"cidade": cidade, "pais": pais}
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
