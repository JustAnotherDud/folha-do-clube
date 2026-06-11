# -*- coding: utf-8 -*-
"""scrape.py — extrai KOMs/Top10s do Strava e escreve data.json.

Corre no GitHub Actions (cron diário) ou localmente:
    STRAVA_SESSION=<cookie _strava4_session> python scrape.py

A posição vem codificada no ícone (icon-segment-effort-NN.svg, KOM=01).
Falha com exit != 0 se a sessão expirou — renovar o secret STRAVA_SESSION
com um cookie fresco copiado do browser.
"""
import json
import os
import re
import sys
import time
from datetime import datetime, date

import requests
from bs4 import BeautifulSoup

ATLETAS = [
    ("100300630", "Zé"),
    ("135219743", "Xeira"),
    # acrescentar ("id", "Nome") quando houver mais
]
BASE = "https://www.strava.com"
PAGE_DELAY = 1.5
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
           "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36"}
MESES = {"Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
         "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12}


def iso_date(s):
    m = re.match(r"([A-Za-z]{3})\w* (\d+), (\d+)", s.strip())
    return (date(int(m.group(3)), MESES[m.group(1)[:3]], int(m.group(2))).isoformat()
            if m else s)


def parse_rows(html):
    soup = BeautifulSoup(html, "html.parser")
    table = soup.select_one("table.my-segments")
    if not table:
        return []
    rows = []
    for tr in table.select("tbody tr"):
        seg = tr.select_one("a[href^='/segments/']")
        if not seg:
            continue
        effort = tr.select_one("a[href^='/segment_efforts/']")
        icon = tr.select_one("td.icon img")
        m = re.search(r"icon-segment-effort-(\d+)", icon["src"]) if icon else None
        nowrap = [td.get_text(" ", strip=True) for td in tr.select("td.no-wrap")]
        tds = tr.find_all("td")
        rows.append({
            "posicao": int(m.group(1)) if m else 0,
            "tipo": tds[1].get_text(" ", strip=True) if len(tds) > 1 else "",
            "segmento": seg.get_text(strip=True),
            "url": BASE + seg["href"],
            "effort_url": (BASE + effort["href"]) if effort else "",
            "dist_km": float(nowrap[0].replace(" km", "")) if nowrap else 0,
            "elev_m": int((nowrap[1] if len(nowrap) > 1 else "0").replace(" m", "") or 0),
            "tempo": effort.get_text(strip=True) if effort else "",
            "data": iso_date(tr.find("time").get_text(strip=True)) if tr.find("time") else "",
        })
    return rows


def main():
    cookie = os.environ.get("STRAVA_SESSION", "").strip()
    if not cookie:
        sys.exit("STRAVA_SESSION não definido.")
    s = requests.Session()
    s.cookies.set("_strava4_session", cookie, domain=".strava.com")

    linhas = []
    for athlete_id, nome in ATLETAS:
        for top_tens in (False, True):
            n = 1
            while True:
                url = (f"{BASE}/athletes/{athlete_id}/segments/leader"
                       f"?page={n}" + ("&top_tens=true" if top_tens else ""))
                r = s.get(url, headers=HEADERS, timeout=30)
                r.raise_for_status()
                if "/login" in r.url:
                    sys.exit("Sessão expirada — renovar secret STRAVA_SESSION.")
                rows = parse_rows(r.text)
                if not rows:
                    break
                for row in rows:
                    row["atleta"] = nome
                linhas.extend(rows)
                print(f"  {nome} {'Top10' if top_tens else 'KOM'} pág {n}: {len(rows)}")
                n += 1
                time.sleep(PAGE_DELAY)

    if not linhas:
        sys.exit("0 linhas — estrutura da página mudou ou bloqueio anti-bot.")

    out = {"gerado": datetime.utcnow().isoformat(timespec="minutes") + "Z",
           "linhas": linhas}
    with open(os.path.join(os.path.dirname(__file__) or ".", "data.json"),
              "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"{len(linhas)} linhas -> data.json")


if __name__ == "__main__":
    main()
