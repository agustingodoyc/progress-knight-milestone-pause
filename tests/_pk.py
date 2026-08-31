"""Utilidades compartidas por las pruebas.

Cada suite levanta una copia local del juego en un servidor estático, inyecta
el userscript en la página y maneja el estado del juego desde afuera. No hace
falta Tampermonkey: `page.evaluate(SCRIPT)` corre en el mismo contexto que
`gameData`, igual que `@grant none`.
"""
import atexit
import os
import pathlib
import subprocess
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPT_PATH = ROOT / "progress-knight-milestone-pause.user.js"
SCRIPT = SCRIPT_PATH.read_text(encoding="utf-8")

PORT = int(os.environ.get("PK_PORT", "8899"))
URL = f"http://localhost:{PORT}/index.html"
GAME_REPO = "https://github.com/ihtasham42/progress-knight.git"


def game_dir():
    """Carpeta con el juego. PK_GAME para apuntar a una copia propia."""
    env = os.environ.get("PK_GAME")
    if env:
        return pathlib.Path(env)
    local = ROOT / ".game"
    if not (local / "index.html").exists():
        print("[pk] clonando el juego en .game ...")
        subprocess.run(["git", "clone", "--depth", "1", GAME_REPO, str(local)], check=True)
    return local


def serve():
    srv = subprocess.Popen(
        ["python3", "-m", "http.server", str(PORT), "--directory", str(game_dir())],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    atexit.register(srv.terminate)
    time.sleep(1)
    return srv


async def launch(pw):
    """PK_CHROMIUM permite usar un Chromium ya instalado en el sistema."""
    exe = os.environ.get("PK_CHROMIUM")
    return await pw.chromium.launch(**({"executable_path": exe} if exe else {}))


def report(results, errors):
    """results: lista de (nombre, ok) o (nombre, ok, info)."""
    print("\n=== RESULTADOS ===")
    ok = True
    for row in results:
        name, res = row[0], row[1]
        info = row[2] if len(row) > 2 else ""
        print(("PASS " if res else "FAIL ") + name + (f"   [{info}]" if info else ""))
        ok = ok and res
    real = [e for e in errors if "favicon" not in e.lower() and "ERR_" not in e]
    print("errores JS:", real or "ninguno")
    print("TOTAL:", "OK" if ok and not real else "REVISAR")
    return ok and not real
