# -*- coding: utf-8 -*-
"""Harness de regressão: compara o comportamento actual com tests/baseline.json.

    python tests/harness.py           # compara com a baseline
    python tests/harness.py --update  # regrava a baseline

Sem rede: o Strava é simulado com HTML sintético e o site corre no Edge
(Playwright) com todos os pedidos servidos localmente. Os scripts correm
numa cópia temporária, por isso os JSON do repo não são tocados.
Saídas grandes ficam como contagem + hash.
"""
import contextlib
import difflib
import hashlib
import importlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import requests

RAIZ = Path(__file__).resolve().parent.parent
BASELINE = Path(__file__).parent / "baseline.json"
BASE = "https://www.strava.com"
# commit com o data.json/prs.json usados como fixture do site (dados reais congelados)
COMMIT_DADOS = "fb9f990"


def resumo(v):
    """Valores pequenos ficam como estão; grandes passam a contagem + hash."""
    s = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False, sort_keys=True)
    if len(s) <= 160:
        return v
    n = len(v) if isinstance(v, (list, dict)) else s.count("\n") + 1
    return {"n": n, "sha": hashlib.sha256(s.encode()).hexdigest()[:16]}


# ---------------------------------------------------------------- Strava falso

def linha(seg, pos=1, tipo="Run", nome="Seg", dist="1.23 km", elev="15 m",
          tempo="2:29", data="Jul 10, 2025", effort=True, icon=True):
    icone = (f'<img src="https://x/icon-segment-effort-{pos:02d}.svg">' if icon else "")
    ef = f'<a href="/segment_efforts/{seg}9">{tempo}</a>' if effort else ""
    nowrap = "".join(f'<td class="no-wrap">{x}</td>' for x in (dist, elev) if x is not None)
    t = f"<time>{data}</time>" if data else ""
    return (f'<tr><td class="icon">{icone}</td><td>{tipo}</td>'
            f'<td><a href="/segments/{seg}">{nome}</a></td>{nowrap}<td>{ef}</td><td>{t}</td></tr>')


def tabela_leader(linhas):
    if not linhas:
        return "<html><body><p>No results</p></body></html>"
    return f'<table class="my-segments"><tbody>{"".join(linhas)}</tbody></table>'


LEADER = {  # (athlete_id, top_tens, página) -> linhas
    ("100300630", False, 1): [
        linha("1001", 1, "Run", "Subida A", tempo="25s"),
        linha("30832045", 1, "Run", "Ignorado"),
        linha("1002", 1, "Ride", "Recta B", "0.80 km", "8 m", effort=False, data="Aug 3, 2025"),
        '<tr><td class="icon"></td><td>Run</td><td>sem link</td></tr>',
    ],
    ("100300630", True, 1): [
        linha("1003", 4, "Trail Run", "Serra & <C>", "12.40 km", "310 m", "1:20:16", "September 5, 2024"),
        linha("1004", 10, "Walk", "Passeio", "0.30 km", "", "4:05", "Yesterday"),
    ],
    ("222", False, 1): [linha("1003", 1, "Trail Run", "Serra & <C>", "12.40 km", "310 m", "1:15:00", "Mar 1, 2025")],
    ("222", True, 1): [
        linha("1001", 3, "Run", "Subida A", tempo="31s", icon=False),
        linha("1005", 2, "Run", "Falha", "2.00 km", None, "9:59", "Dec 24, 2023"),
    ],
    ("333", False, 1): [linha("1006", 1, "Run", "Cache", "5.00 km", "20 m", "19:59"),
                        linha("1002", 1, "Ride", "Recta B", "0.80 km", "8 m", "1:01")],
    ("333", False, 2): [linha("1007", 1, "Run", "Pág 2", "1.00 km", "0 m", "3:00", "Jan 2, 2026")],
}

MEMBROS = ('<a href="/athletes/100300630">José Silva</a><a href="/athletes/222">Ana Costa</a>'
           '<a href="/athletes/222"><img></a><a href="/athletes/222/follows">x</a>'
           '<a href="/athletes/333">Inês Santos</a><a href="/athletes/444">Bruno Dias</a>')

TITULOS = {"1001": "Subida A Run Segment in Lisboa, Lisbon, Portugal",
           "1002": "Recta B Ride Segment in Sintra, Lisbon",
           "1003": "Serra Trail Run Segment in Madrid, Spain",
           "1004": None, "1007": "Pág 2 Run Segment in Porto"}


def run_tabela(sport, linhas):
    rows = "".join(
        f"<tr><td>{lab}</td><td>{f'<a href=\"/activities/{act}/best-efforts\">{t}</a>' if act else t}</td>"
        f"<td>9:99</td></tr>" for lab, t, act in linhas)
    return (f'<table><thead><tr><th><button class="sport-{sport.lower()} selected" title="{sport}">'
            f'</button></th></tr></thead><tbody><tr><th><span data-glossary-term="definition-best-efforts">'
            f'Best Efforts</span></th></tr>{rows}</tbody></table>')


SIDEBAR = {
    "100300630": run_tabela("Ride", [("40K", "1:05:00", "7001")]) + run_tabela("Run", [
        ("400m", "1:03", "9001"), ("5K", "19:26", "9002"), ("Half-Marathon", "1:32:10", "9003"),
        ("Longest Run", "21.1 km", "9003"), ("1K", "3:30", None), ("", "5:00", "9001")]),
    "222": run_tabela("Ride", [("5K", "8:00", "7002")]),
    "333": run_tabela("Run", [("1 mile", "6:10", "9004"), ("10K", "45:00", "9005")]),
    "444": run_tabela("Run", [("5K", "25:00", "9002")]),
}
ACTIVIDADES = {"9002": "<div>This activity has been flagged</div>",
               "9005": '<div class="inset flagged error"></div>'}


class Resposta:
    def __init__(self, url, text="", status=200):
        self.url, self.text, self.status_code = url, text, status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} {self.url}")


class SessaoFalsa:
    """Substitui requests.Session. Regista cada pedido para a baseline."""
    pedidos = []
    cenario = "normal"

    def __init__(self):
        self.cookies = requests.cookies.RequestsCookieJar()

    def get(self, url, headers=None, timeout=None):
        SessaoFalsa.pedidos.append([url.replace(BASE, ""), sorted((headers or {}).items()), timeout,
                                    self.cookies.get("_strava4_session", "")])
        caminho, _, query = url.replace(BASE, "").partition("?")
        params = dict(p.split("=") for p in query.split("&") if p)
        c = SessaoFalsa.cenario
        partes = caminho.strip("/").split("/")
        if c == "expira-membros" or (c == "expira-leader" and caminho.endswith("/leader")) \
                or (c == "expira-sidebar" and "sidebar" in caminho):
            return Resposta(BASE + "/login")
        if caminho == "/clubs/nozes/members":
            return Resposta(url, MEMBROS)
        if caminho.endswith("/segments/leader"):
            if c == "vazio":
                return Resposta(url, tabela_leader([]))
            chave = (partes[1], params.get("top_tens") == "true", int(params["page"]))
            return Resposta(url, tabela_leader(LEADER.get(chave, [])))
        if partes[0] == "segments":
            if partes[1] == "1005":
                raise requests.ConnectionError("rede")
            t = TITULOS.get(partes[1])
            return Resposta(url, f"<html><head><title>{t}</title></head></html>" if t else "<html></html>")
        if caminho.endswith("/profile_sidebar_comparison"):
            return Resposta(url, "" if c == "sem-prs" else SIDEBAR.get(partes[1], ""))
        if partes[0] == "activities":
            if partes[1] == "9004":
                raise requests.Timeout("lento")
            return Resposta(url, ACTIVIDADES.get(partes[1], "<div>ok</div>"))
        return Resposta(url, "", 404)


@contextlib.contextmanager
def sandbox():
    """Cópia dos scripts numa pasta temporária, com rede e sleep simulados."""
    tmp = Path(tempfile.mkdtemp(prefix="folha-harness-"))
    for f in ("comum.py", "scrape.py", "scrape_prs.py", "ignorar.py"):
        shutil.copy(RAIZ / f, tmp / f)
    (tmp / "localizacoes.json").write_text(json.dumps(
        {"1006": {"cidade": "Cache", "pais": "Portugal"}, "9999": {"cidade": "X", "pais": "Y"}}), encoding="utf-8")
    (tmp / "flagged.json").write_text(json.dumps({"9003": False, "8888": True}), encoding="utf-8")
    originais = (requests.Session, time.sleep, list(sys.path), os.environ.get("STRAVA_SESSION"))
    requests.Session, time.sleep = SessaoFalsa, lambda s: None
    sys.path.insert(0, str(tmp))
    for m in ("comum", "scrape", "scrape_prs", "ignorar"):
        sys.modules.pop(m, None)
    SessaoFalsa.pedidos, SessaoFalsa.cenario = [], "normal"
    os.environ["STRAVA_SESSION"] = "  cookie-teste  "
    try:
        yield tmp
    finally:
        requests.Session, time.sleep, sys.path[:] = originais[0], originais[1], originais[2]
        if originais[3] is None:
            os.environ.pop("STRAVA_SESSION", None)
        else:
            os.environ["STRAVA_SESSION"] = originais[3]
        for m in ("comum", "scrape", "scrape_prs", "ignorar"):
            sys.modules.pop(m, None)
        shutil.rmtree(tmp, ignore_errors=True)


def correr(modulo, cenario="normal", env=True):
    """Corre main() de um script na sandbox; devolve saída, erro e ficheiros escritos."""
    with sandbox() as tmp:
        SessaoFalsa.cenario = cenario
        if not env:
            os.environ["STRAVA_SESSION"] = " "
        out, saida = io.StringIO(), None
        with contextlib.redirect_stdout(out):
            try:
                importlib.import_module(modulo).main()
            except SystemExit as e:
                saida = str(e.code)
        r = {"exit": saida, "stdout": resumo(out.getvalue()), "pedidos": resumo(sorted(map(str, SessaoFalsa.pedidos)))}
        for f in ("data.json", "prs.json", "localizacoes.json", "flagged.json"):
            p = tmp / f
            if p.exists():
                texto = p.read_text(encoding="utf-8")
                if f in ("data.json", "prs.json"):
                    d = json.loads(texto)
                    r[f + ":gerado_formato"] = len(d.pop("gerado")) == len("2026-01-01T00:00Z")
                    texto = json.dumps(d, ensure_ascii=False, indent=1)
                r[f] = resumo(texto)
        return r


def casos_python():
    r = {}
    r["scrape"] = correr("scrape")
    r["scrape_prs"] = correr("scrape_prs")
    for c in ("expira-membros", "expira-leader", "vazio"):
        r[f"scrape:{c}"] = correr("scrape", c)["exit"]
    for c in ("expira-sidebar", "sem-prs"):
        r[f"scrape_prs:{c}"] = correr("scrape_prs", c)["exit"]
    r["scrape:sem-env"] = correr("scrape", env=False)["exit"]
    r["scrape_prs:sem-env"] = correr("scrape_prs", env=False)["exit"]

    with sandbox():
        comum = importlib.import_module("comum")
        scrape = importlib.import_module("scrape")
        r["iso_date"] = [comum.iso_date(s) for s in
                         ("Jul 10, 2025", "September 5, 2024", " Dec 1, 2023 ", "Yesterday", "")]
        r["normalizar_tempo"] = [comum.normalizar_tempo(s) for s in
                                 ("25s", "59s", "2:29", "0:05", "1:20:16", "61:00", "3600s")]
        r["_normalizar_local"] = [comum._normalizar_local(c, p) for c, p in
                                  (("Sintra", "Lisbon"), ("Faro", " Évora "), ("Madrid", "Spain"), ("", ""))]
        r["extrair_seg_id"] = [comum.extrair_seg_id(u) for u in
                               ("https://www.strava.com/segments/123", "/segments/9?x", "/athletes/1", "")]
        r["parse_rows:vazio"] = scrape.parse_rows("<html></html>")
        r["IGNORAR"] = sorted(scrape.IGNORAR)
        r["ALCUNHAS"] = scrape.ALCUNHAS

    r.update(casos_ignorar())
    return r


def casos_ignorar():
    r, argv_original = {}, list(sys.argv)
    for nome, argv in (("sem-args", []), ("url", ["https://www.strava.com/segments/27218238", "distancia", "errada"]),
                       ("id", ["27218238"]), ("repetido", ["30832045"]), ("sem-id", ["abc"])):
        with sandbox() as tmp:
            antes = (tmp / "scrape.py").read_text(encoding="utf-8").splitlines()
            ign = importlib.import_module("ignorar")
            cmds = []

            def falso_run(cmd, **kw):
                cmds.append(cmd)
                # como o git real: pull --rebase recusa com mudanças por commitar
                if list(cmd[:2]) == ["git", "pull"] and (tmp / "scrape.py").read_text(encoding="utf-8").splitlines() != antes:
                    return subprocess.CompletedProcess(cmd, 1, "", "error: cannot pull with rebase: You have unstaged changes.")
                return subprocess.CompletedProcess(cmd, 0, "", "")
            ign.subprocess.run, antigo = falso_run, subprocess.run
            sys.argv, out, saida = ["ignorar.py", *argv], io.StringIO(), None
            try:
                with contextlib.redirect_stdout(out):
                    ign.main()
            except SystemExit as e:
                saida = str(e.code)
            finally:
                subprocess.run, sys.argv = antigo, argv_original
            r[f"ignorar:{nome}"] = {"exit": resumo(saida) if saida else None, "stdout": out.getvalue(),
                                    "cmds": cmds, "scrape.py": [l for l in difflib.unified_diff(
                                        antes, (tmp / "scrape.py").read_text(encoding="utf-8").splitlines(),
                                        lineterm="", n=0) if l[:1] in "+-" and l[:3] not in ("+++", "---")]}
    return r


# ------------------------------------------------------------------ site

SQUADRATS = {"atualizado": "2026-09-25T06:07:24Z", "atletas": {
    "Zé": {"squadrats": 481, "squadratinhos": 5853, "yard": 102, "yardinho": 483, "ubersquadrat": 8, "ubersquadratinho": 13},
    "Xeira": {"squadrats": 471, "squadratinhos": 6100, "yard": 116, "yardinho": 145, "ubersquadrat": 9, "ubersquadratinho": 9},
    "Inês S.": {"squadrats": 120, "squadratinhos": 900, "yard": None, "yardinho": 30, "ubersquadrat": 3, "ubersquadratinho": 5},
    "Pedro": {"squadrats": 480, "squadratinhos": 10, "yard": 5, "yardinho": 1, "ubersquadrat": 2},
    "Novo": {"squadrats": 1, "squadratinhos": 2, "yard": 0, "yardinho": 0, "ubersquadrat": 1, "ubersquadratinho": 1},
}}
GANHOS = {"gerado": "2026-09-25T06:07:26Z", "dias": [
    {"data": "2026-09-01", "atletas": {"Zé": {"squadrats": 9}}},
    {"data": "2026-09-14", "atletas": {"Zé": {"squadrats": 2, "squadratinhos": 30}, "Xeira": {"squadrats": 2}}},
    {"data": "2026-09-20", "atletas": {"Pedro": {"squadrats": -1, "yard": 3}, "Inês S.": {"squadratinhos": 7}}},
    {"data": "2026-09-25", "atletas": {"Carolina": {"squadrats": 2, "squadratinhos": 23}}},
]}
CORES = {"cores": {"Zé": "#e03131", "Xeira": "#9c46d8", "Carolina": "#c99a00", "Inês S.": "#e8710a",
                   "Inês": "#e8710a", "Ana": "#12889c", "Pedro": "#010203"}}

SNAP_JS = r"""async () => {
  await document.fonts.ready;
  document.getAnimations().forEach(a => a.finish());  // transições a meio mudam os estilos
  const q = s => document.querySelector(s);
  const html = s => { const e = q(s); return e ? e.outerHTML : null; };
  const r = {hash: location.hash};
  for (const s of ["#tabs", "#gerado", "#ranking", "#f-atleta", "#f-tipo", "#f-pais", "#f-cidade",
    "#f-trofeu", "#conta", "#tabela", "#prs", "#prs-gerado", "#podio-metrica-nome", "#squadrats-podio",
    "#squadrats", "#squadrats-gerado", "#ganhos-wrap", "#ganhos-metrica-nome"]) r[s] = html(s);
  r.paineis = [...document.querySelectorAll(".panel")].map(p => p.id + ":" + p.classList.contains("active"));
  const props = ["display","color","background-color","background-image","font-family","font-size",
    "font-weight","text-align","padding","margin","border","width","height","opacity","position",
    "text-decoration","cursor","white-space","order","transform","box-shadow","gap","flex","letter-spacing"];
  const est = [];
  for (const e of document.body.querySelectorAll("*")) {
    const c = getComputedStyle(e), b = e.getBoundingClientRect();
    est.push(e.tagName + "|" + props.map(p => c.getPropertyValue(p)).join("|") +
      "|" + Math.round(b.width) + "x" + Math.round(b.height));
  }
  r.estilos = est.join("\n");
  return r;
}"""


ORDEM_JSON = ("membros_cores.json", "data.json", "prs.json", "squadrats.json", "daily_gains.json")


def casos_site():
    from playwright.sync_api import sync_playwright

    dados = {n: subprocess.run(["git", "show", f"{COMMIT_DADOS}:{n}"], cwd=RAIZ, capture_output=True,
                               check=True).stdout for n in ("data.json", "prs.json")}
    raw = "https://raw.githubusercontent.com/JustAnotherDud/squadrats-club/"
    externos = {raw + "main/data/membros_cores.json": CORES,
                raw + "data/data/squadrats.json": SQUADRATS,
                raw + "data/data/daily_gains.json": GANHOS}

    def abrir(browser, falhas=(), largura=1280):
        ctx = browser.new_context(viewport={"width": largura, "height": 900}, locale="pt-PT",
                                  timezone_id="Europe/Lisbon", reduced_motion="reduce")
        erros = []

        pendentes = {}

        def servir(route):
            url = route.request.url.split("#")[0]
            nome = url.replace("http://folha.test/", "") or "index.html"
            if url in externos or nome in dados:
                pendentes[url] = route    # respondido em ORDEM_JSON, ver abaixo
                return None
            if url.startswith("http://folha.test/"):
                p = RAIZ / nome
                if p.is_file():
                    return route.fulfill(path=str(p))
                return route.fulfill(status=404, body="")
            erros.append("pedido externo inesperado: " + url)
            return route.abort()
        ctx.route("**/*", servir)
        page = ctx.new_page()
        page.on("console", lambda m: m.type in ("error", "warning") and erros.append(m.text))
        page.on("pageerror", lambda e: erros.append(str(e)))
        page.clock.set_fixed_time("2026-09-25T12:00:00Z")
        page.goto("http://folha.test/", wait_until="commit")
        # O site pede 5 JSON em paralelo e o resultado depende da ordem de chegada
        # (as cores podem chegar depois do squadrats.json). Responde sempre pela
        # mesma ordem para a baseline ser estável.
        while len(pendentes) < len(ORDEM_JSON):
            page.wait_for_timeout(20)
        for fim in ORDEM_JSON:
            url, route = next((u, r) for u, r in pendentes.items() if u.endswith(fim))
            if any(f in url for f in falhas):
                route.fulfill(status=500, body="erro")
            elif url in externos:
                route.fulfill(json=externos[url])
            else:
                route.fulfill(body=dados[fim], content_type="application/json")
            page.wait_for_timeout(100)
        page.wait_for_load_state("networkidle")
        return ctx, page, erros

    r = {}

    def snap(page, nome):
        for k, v in page.evaluate(SNAP_JS).items():
            r[f"{nome} {k}"] = resumo(v)

    with sync_playwright() as p:
        canal = os.environ.get("HARNESS_BROWSER", "msedge")
        browser = p.chromium.launch(channel=canal or None)

        ctx, page, erros = abrir(browser)
        snap(page, "inicial")
        for k in page.eval_on_selector_all("#tabela th[data-k]", "ths => ths.map(t => t.dataset.k)"):
            page.click(f'#tabela th[data-k="{k}"]')
            r[f"ordem {k} asc #tabela"] = resumo(page.inner_html("#tabela"))
        page.click('#tabela th[data-k="data"]')
        r["ordem data desc #tabela"] = resumo(page.inner_html("#tabela"))
        for sel in ("#f-tipo", "#f-pais", "#f-cidade", "#f-trofeu"):
            for v in page.eval_on_selector_all(f"{sel} option", "os => os.map(o => o.value)"):
                page.select_option(sel, v)
                r[f"filtro {sel}={v}"] = resumo(page.inner_html("#tabela tbody") + page.inner_text("#conta"))
            page.select_option(sel, "")
        page.fill("#f-busca", "a")
        r["filtro busca=a"] = resumo(page.inner_html("#tabela tbody") + page.inner_text("#conta"))
        page.fill("#f-busca", "")
        page.check("#f-multi")
        snap(page, "multi")
        page.click('#tabela th[data-k="atleta"]')
        r["multi apos-clique #tabela"] = resumo(page.inner_html("#tabela"))
        page.uncheck("#f-multi")
        pills = page.eval_on_selector_all("#f-atleta .pill", "ps => ps.map(p => p.dataset.atleta)")
        for a in pills[1:3] + pills[1:2] + [""]:
            page.click(f'#f-atleta .pill[data-atleta="{a}"]')
            r[f"pill {a}"] = resumo(page.inner_html("#f-atleta") + page.inner_text("#conta"))
        page.click('.tab[data-tab="best-efforts"]')
        snap(page, "best-efforts")
        page.click('.tab[data-tab="squadrats"]')
        snap(page, "squadrats")
        for c in page.eval_on_selector_all("#squadrats th[data-c]", "ts => ts.map(t => t.dataset.c)"):
            page.click(f'#squadrats th[data-c="{c}"]')
            r[f"metrica {c}"] = resumo(page.inner_html("#tab-squadrats"))
        page.focus('#squadrats th[data-c="yard"]')
        page.keyboard.press("Enter")
        r["metrica teclado yard"] = resumo(page.inner_html("#tab-squadrats"))
        page.hover('#squadrats th[data-c="squadrats"]')
        r["tooltip"] = page.evaluate("""() => { const c = getComputedStyle(
            document.querySelector('#squadrats th[data-c="squadrats"]'), '::after');
            return [c.content, c.top, c.width, c.backgroundColor].join('|'); }""")
        page.goto("http://folha.test/#invalido")
        r["hash invalido"] = page.evaluate("[...document.querySelectorAll('.panel.active')].map(p => p.id)")
        r["consola"] = erros
        ctx.close()

        ctx, page, erros = abrir(browser, largura=375)
        snap(page, "mobile")
        ctx.close()

        for nome, falhas in (("sem-data", ["data.json"]), ("sem-prs", ["prs.json"]),
                             ("sem-cores", ["membros_cores"]), ("sem-squadrats", ["squadrats.json"]),
                             ("sem-ganhos", ["daily_gains"])):
            ctx, page, erros = abrir(browser, falhas)
            page.click('.tab[data-tab="squadrats"]')
            snap(page, "falha " + nome)
            r[f"falha {nome} consola"] = erros
            ctx.close()
        browser.close()
    return r


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    gravar = "--update" in sys.argv
    atual = {"python": casos_python(), "site": casos_site()}
    if gravar:
        BASELINE.write_text(json.dumps(atual, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
                            encoding="utf-8")
        print(f"baseline gravada: {sum(len(v) for v in atual.values())} casos")
        return
    base = json.loads(BASELINE.read_text(encoding="utf-8"))
    atual = json.loads(json.dumps(atual, ensure_ascii=False))
    difs = [f"{g} / {k}:\n  antes: {base[g].get(k)}\n  agora: {atual[g].get(k)}"
            for g in base for k in sorted(set(base[g]) | set(atual[g])) if base[g].get(k) != atual[g].get(k)]
    total = sum(len(v) for v in base.values())
    if difs:
        print("\n".join(difs))
        sys.exit(f"FALHOU: {len(difs)} de {total} casos diferentes da baseline")
    print(f"OK: {total} casos iguais à baseline")


if __name__ == "__main__":
    main()
