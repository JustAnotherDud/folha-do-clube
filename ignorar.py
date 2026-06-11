# -*- coding: utf-8 -*-
"""ignorar.py — adiciona um segmento à blocklist IGNORAR e publica.

Uso:
    python ignorar.py <url-ou-id> [motivo...]
    python ignorar.py https://www.strava.com/segments/27218238 distancia errada
    python ignorar.py 27218238 KOM impossivel

Edita o set IGNORAR em scrape.py, faz commit+push e dispara o workflow
"actualizar dados" (precisa do gh autenticado). Em ~3 min o segmento
desaparece da tabela e do ranking.
"""
import re
import subprocess
import sys
from pathlib import Path

SCRAPE = Path(__file__).parent / "scrape.py"


def run(*cmd):
    r = subprocess.run(cmd, cwd=SCRAPE.parent, capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"falhou: {' '.join(cmd)}\n{r.stderr.strip()}")
    return r.stdout.strip()


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    m = re.search(r"(\d{4,})", sys.argv[1])
    if not m:
        sys.exit(f"não encontrei id numérico em: {sys.argv[1]}")
    seg_id = m.group(1)
    motivo = " ".join(sys.argv[2:]) or "bug no Strava"

    src = SCRAPE.read_text(encoding="utf-8")
    if f'"{seg_id}"' in src:
        sys.exit(f"segmento {seg_id} já está na blocklist.")
    novo = re.sub(r"(IGNORAR = \{\n)",
                  rf'\g<1>    "{seg_id}",  # {motivo}\n', src, count=1)
    if novo == src:
        sys.exit("não encontrei o set IGNORAR em scrape.py — formato mudou?")
    SCRAPE.write_text(novo, encoding="utf-8")
    print(f"adicionado {seg_id} ({motivo})")

    run("git", "pull", "--rebase")
    run("git", "add", "scrape.py")
    run("git", "commit", "-m", f"chore: ignorar segmento {seg_id} — {motivo}")
    run("git", "push")
    run("gh", "workflow", "run", "actualizar dados")
    print("publicado — site actualiza em ~3 min.")


if __name__ == "__main__":
    main()
