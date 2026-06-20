# -*- coding: utf-8 -*-
"""make_data.py — converte os CSVs do strava_koms_fetch.py em data.json p/ o site.

Uso: python make_data.py
Lê todos os D:\\sync_hub\\output\\strava_koms*.csv e escreve data.json aqui.
"""
import csv
import json
from datetime import datetime
from pathlib import Path

from comum import extrair_seg_id, iso_date, localizar_segmentos, normalizar_tempo

CSV_DIR = Path(r"D:\sync_hub\output")
OUT = Path(__file__).parent / "data.json"

# normalizar nomes do CSV -> nomes da sheet
NOMES = {"Ze": "Zé", "Joao": "Xeira"}


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
                "tempo": normalizar_tempo(r["tempo"]),
                "data": iso_date(r["data"]),
            })

ids = {extrair_seg_id(r["url"]) for r in rows} - {None}
locais = localizar_segmentos(ids)
for r in rows:
    info = locais.get(extrair_seg_id(r["url"]), {})
    r["cidade"] = info.get("cidade", "")
    r["pais"] = info.get("pais", "")

out = {"gerado": datetime.now().isoformat(timespec="minutes"), "linhas": rows}
OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"{len(rows)} linhas -> {OUT}")
