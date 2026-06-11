# Club KOMs

PoC: ranking de KOMs/CRs e Top10s do clube, a partir de scraping das paginas
/segments/leader do Strava (ver D:\sync_hub\scripts\strava_koms_fetch.py).

Actualizar dados:
1. python strava_koms_fetch.py [--athlete-id ID --nome NOME]  (por atleta)
2. python make_data.py
3. git commit + push — o GitHub Pages publica automaticamente.

Pontos: posicao 1 = 10 pts ... posicao 10 = 1 pt (11 - posicao).
