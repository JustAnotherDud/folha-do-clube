# -*- coding: utf-8 -*-
"""Screenshots das três tabs a 390px e 1280px, com os dados reais do repo.

    python tests/screenshots.py docs/design-polish/antes
    python tests/screenshots.py docs/design-polish/depois

Os JSON do squadrats-club (cores, squadrats, ganhos) são pedidos ao raw.githubusercontent
uma vez; se não houver rede, usa uma cópia local em --cache <pasta>.
Mesmas variáveis do harness: HARNESS_BROWSER (vazio = Chromium) e HARNESS_EXECUTABLE.
"""
import json
import os
import sys
from pathlib import Path

import requests
from playwright.sync_api import sync_playwright

RAIZ = Path(__file__).resolve().parent.parent
RAW = "https://raw.githubusercontent.com/JustAnotherDud/squadrats-club/"
EXTERNOS = {RAW + "main/data/membros_cores.json": "cores.json",
            RAW + "data/data/squadrats.json": "squadrats.json",
            RAW + "data/data/daily_gains.json": "daily_gains.json"}
TABS = ("koms", "best-efforts", "squadrats")
LARGURAS = (390, 1280)


def carregar(cache):
    cache.mkdir(parents=True, exist_ok=True)
    dados = {}
    for url, nome in EXTERNOS.items():
        f = cache / nome
        if not f.exists():
            f.write_text(requests.get(url, timeout=30).text, encoding="utf-8")
        dados[url] = json.loads(f.read_text(encoding="utf-8"))
    return dados


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    saida = Path(args[0]) if args else RAIZ / "docs" / "design-polish" / "depois"
    saida.mkdir(parents=True, exist_ok=True)
    cache = Path(os.environ.get("SCREENSHOTS_CACHE", RAIZ / ".screenshots-cache"))
    externos = carregar(cache)
    with sync_playwright() as p:
        browser = p.chromium.launch(channel=os.environ.get("HARNESS_BROWSER", "msedge") or None,
                                    executable_path=os.environ.get("HARNESS_EXECUTABLE") or None)
        for w in LARGURAS:
            ctx = browser.new_context(viewport={"width": w, "height": 900}, locale="pt-PT",
                                      timezone_id="Europe/Lisbon", reduced_motion="reduce",
                                      device_scale_factor=2)

            def servir(route):
                url = route.request.url.split("#")[0]
                if url in externos:
                    return route.fulfill(json=externos[url])
                if url.startswith("http://folha.test/"):
                    p_ = RAIZ / (url.replace("http://folha.test/", "") or "index.html")
                    if p_.is_file():
                        return route.fulfill(path=str(p_))
                    return route.fulfill(status=404, body="")
                return route.abort()
            ctx.route("**/*", servir)
            page = ctx.new_page()
            page.clock.set_fixed_time("2026-11-10T12:00:00Z")
            for t in TABS:
                page.goto(f"http://folha.test/#{t}")
                page.wait_for_load_state("networkidle")
                page.evaluate("document.fonts.ready")
                page.wait_for_timeout(300)
                page.screenshot(path=str(saida / f"{t}-{w}.png"), full_page=True)
            ctx.close()
        browser.close()
    print("screenshots em", saida)


if __name__ == "__main__":
    main()
