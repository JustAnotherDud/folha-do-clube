# -*- coding: utf-8 -*-
"""make_data.py — converte os CSVs do strava_koms_fetch.py em data.json p/ o site.

Uso: python make_data.py
Lê todos os D:\\sync_hub\\output\\strava_koms*.csv e escreve data.json aqui.
"""
import csv
import json
import re
from datetime import datetime, date
from pathlib import Path

CSV_DIR = Path(r"D:\sync_hub\output")
OUT = Path(__file__).parent / "data.json"

# normalizar nomes do CSV -> nomes da sheet
NOMES = {"Ze": "Zé", "Joao": "Xeira"}
MESES = {"Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
         "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12}


def iso_date(s):
    m = re.match(r"([A-Za-z]{3})\w* (\d+), (\d+)", s.strip())
    if not m:
        return s
    return date(int(m.group(3)), MESES[m.group(1)[:3]], int(m.group(2))).isoformat()


rows = []
for f in sorted(CSV_DIR.glob("strava_koms*.csv")):
    with open(f, encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            rows.append({
                "atleta": NOMES.get(r["atleta"], r["atleta"]),
                "posicao": int(r["posicao"]),
                "tipo": r["tipo"],
                "segmento": r["segmento"],
                "url": r["segment_url"],
                "effort_url": r["effort_url"],
                "dist_km": float(r["distancia"].replace(" km", "")),
                "elev_m": int(r["elevacao"].replace(" m", "") or 0),
                "tempo": r["tempo"],
                "data": iso_date(r["data"]),
            })

out = {"gerado": datetime.now().isoformat(timespec="minutes"), "linhas": rows}
OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"{len(rows)} linhas -> {OUT}")
