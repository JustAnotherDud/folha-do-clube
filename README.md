# Club KOMs

PoC: ranking de KOMs/CRs e Top10s do clube, a partir de scraping das paginas
/segments/leader do Strava (ver D:\sync_hub\scripts\strava_koms_fetch.py).

Actualizar dados:
1. python strava_koms_fetch.py [--athlete-id ID --nome NOME]  (por atleta)
2. python make_data.py
3. git commit + push — o GitHub Pages publica automaticamente.

Pontos: posicao 1 = 10 pts ... posicao 10 = 1 pt (11 - posicao).

## Campos novos (cidade/país + ritmo)

`scrape.py` e `make_data.py` agora também preenchem `cidade` e `pais` por
linha, a partir do `<title>` da página pública `/segments/<id>` (não precisa
de login). Resultado fica em cache em `localizacoes.json` — só se pede à
Strava o que ainda não está lá, por isso convém manter esse ficheiro versionado
(o workflow já faz commit dele). Para forçar reconsulta de um segmento, apaga
a entrada correspondente nesse ficheiro.

`tempo` vem sempre normalizado para `M:SS` ou `H:MM:SS` (antes vinha misto,
ex. `"25s"` vs `"2:29"`). O ritmo (min/km para Run/Walk, km/h para Ride) é
calculado no `index.html` a partir de `dist_km` + `tempo` — não está guardado
no `data.json`. Nota: para segmentos muito curtos (sprints/rampas <300m) o
ritmo calculado não é muito representativo, é normal parecer estranho.

Lógica partilhada entre `scrape.py` e `make_data.py` está em `comum.py`.

## Best Efforts / PRs de corrida (`scrape_prs.py`)

Extrai o widget "Best Efforts" da sidebar do perfil de cada atleta
(`/athletes/<id>`, separador Run) e escreve `prs.json` — a mesma tabela que
antes era mantida à mão na folha de cálculo do clube. Corre com a mesma
sessão do `scrape.py`:

    STRAVA_SESSION=<cookie _strava4_session> python scrape_prs.py

Não é o "All-Time PRs" (esse é preenchido manualmente pelo atleta) nem cobre
bike — a Strava não tem um widget agregado de Best Efforts por distância
para Ride, só a Power Curve, que é outra coisa. O `index.html` mostra o
resultado numa tabela "Best Efforts 🏃" abaixo do ranking de KOMs, com o
melhor tempo por distância destacado; carrega `prs.json` de forma opcional —
a página de KOMs continua a funcionar normalmente antes da 1ª corrida do
script (ficheiro ainda não existe).

O workflow do GitHub Actions já corre os dois scrapers e faz commit de
`prs.json` junto com `data.json`.

