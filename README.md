# Folha do Clube

Ranking de KOMs/CRs e Top10s do clube, a partir de scraping das páginas `/segments/leader` do Strava — mais Best Efforts de corrida e estatísticas Squadrats. Publicado via GitHub Pages.

## Como os dados são actualizados

**Automático**, via `.github/workflows/update.yml`: corre todos os dias às 05:30 UTC (e também por `workflow_dispatch`, manualmente), executa `scrape.py` + `scrape_prs.py`, e só dá commit/push se algo mudou de facto. Não é preciso fazer nada à mão no dia a dia.

Manual, só se precisares de forçar uma actualização fora da hora do cron ou testar localmente:

```
STRAVA_SESSION=<cookie _strava4_session> python scrape.py
STRAVA_SESSION=<cookie _strava4_session> python scrape_prs.py
```

`make_data.py` é um caminho manual antigo, anterior ao workflow automático — não corre no CI, mantido só por referência.

Pontos do ranking: posição 1 = 10 pts ... posição 10 = 1 pt (11 − posição).

## Campos novos (cidade/país + ritmo)

`scrape.py` também preenche `cidade` e `pais` por linha, a partir do `<title>` da página pública `/segments/<id>` (não precisa de login). Resultado fica em cache em `localizacoes.json` — só se pede à Strava o que ainda não está lá, por isso convém manter esse ficheiro versionado (o workflow já faz commit dele). Para forçar reconsulta de um segmento, apaga a entrada correspondente nesse ficheiro.

`tempo` vem sempre normalizado para `M:SS` ou `H:MM:SS` (antes vinha misto, ex. `"25s"` vs `"2:29"`). O ritmo (min/km para Run/Walk/Trail Run, km/h para Ride) é calculado no `index.html` a partir de `dist_km` + `tempo` + `tipo` — não está guardado no `data.json`. Nota: para segmentos muito curtos (sprints/rampas <300m) o ritmo calculado não é muito representativo, é normal parecer estranho.

Lógica partilhada entre `scrape.py` e `make_data.py` está em `comum.py`.

## Best Efforts / PRs de corrida (`scrape_prs.py`)

Extrai o widget "Best Efforts" da sidebar do perfil de cada atleta e escreve `prs.json` — a mesma tabela que antes era mantida à mão na folha de cálculo do clube. A página `/athletes/<id>` é React (a tabela vem por JS, não está no HTML servido), por isso os dados vêm do endpoint AJAX `/athletes/<id>/profile_sidebar_comparison?hl=en-GB`, que só responde com o header `X-Requested-With: XMLHttpRequest`. Corre com a mesma sessão do `scrape.py`.

Não é o "All-Time PRs" (esse é preenchido manualmente pelo atleta) nem cobre bike — a Strava não tem um widget agregado de Best Efforts por distância para Ride, só a Power Curve, que é outra coisa. O `index.html` mostra o resultado numa tabela "Best Efforts 🏃" abaixo do ranking de KOMs, com o melhor tempo por distância destacado; carrega `prs.json` de forma opcional — a página de KOMs continua a funcionar normalmente antes da 1ª corrida do script (ficheiro ainda não existe).
