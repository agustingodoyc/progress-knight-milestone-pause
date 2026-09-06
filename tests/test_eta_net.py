"""El ETA de los hitos de net/día, contra el tiempo que tardan de verdad."""
import asyncio
import re

from playwright.async_api import async_playwright

import _pk

SCRIPT = _pk.SCRIPT
srv = _pk.serve()
R = []
def ck(n, c, info=""): R.append((n, bool(c), info))

def eta_segundos(texto):
    m = re.search(r'~(?:(\d+)d|(\d+)h (\d+)m|(\d+)m (\d+)s|(\d+)s|<1s)', texto)
    if not m:
        return None
    d, h, hm, mm, ms, s = m.groups()
    if d:  return int(d) * 86400
    if h:  return int(h) * 3600 + int(hm) * 60
    if mm: return int(mm) * 60 + int(ms)
    if s:  return int(s)
    return 0.5

async def fresh(pg, extra=""):
    await pg.evaluate("localStorage.clear()")
    await pg.reload()
    await pg.wait_for_function("window.gameData && Object.keys(gameData.taskData).length>0")
    await pg.evaluate(SCRIPT)
    await pg.wait_for_selector("#pkHitos")
    await pg.evaluate("gameData.paused = true")
    if extra:
        await pg.evaluate(extra)

async def fila(pg):
    return await pg.evaluate(
        "[...document.querySelectorAll('#pkList li')].pop().innerText.replace(/\\n/g, ' ')")

async def agregar(pg, tipo, target, valor):
    await pg.select_option("#pkType", tipo)
    if target:
        await pg.select_option("#pkTarget", target)
    await pg.fill("#pkValue", valor)
    await pg.click("#pkAdd")

# El job sube de nivel y el ingreso con él; Homeless no gasta nada, así que el net
# es el ingreso puro y el umbral de Wooden hut son 100 limpios.
ESCENARIO = """
    gameData.currentProperty = gameData.itemData['Homeless'];
    gameData.currentMisc = [];
    gameData.currentJob = gameData.taskData['Beggar'];
    gameData.currentSkill = gameData.taskData['Concentration'];
    gameData.taskData['Beggar'].level = 0;
    gameData.taskData['Beggar'].xp = 0;
    gameData.taskData['Beggar'].xpMultipliers.push(() => 10);
    gameData.taskData['Beggar'].incomeMultipliers.push(() => 10);
    gameData.coins = 1e9;
"""

async def main():
    async with async_playwright() as p:
        b = await _pk.launch(p)
        pg = await b.new_page(); errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        await pg.goto(_pk.URL)

        # --- producto del Shop: predicción contra el reloj --------------------
        await fresh(pg, ESCENARIO)
        await agregar(pg, "net", "Wooden hut", "")
        await pg.evaluate("gameData.paused = false")
        await pg.wait_for_timeout(300)
        f = await fila(pg)
        pred = eta_segundos(f)
        ck("el hito de Shop muestra ETA", pred is not None, f[:80])
        await pg.evaluate("window.__t0 = performance.now()")
        await pg.wait_for_function("gameData.paused === true", timeout=60000)
        real = await pg.evaluate("(performance.now() - window.__t0) / 1000")
        est = await pg.evaluate("""({net: getIncome() - getExpense(),
                                     nivel: gameData.taskData['Beggar'].level})""")
        ck("le pega al tiempo real", abs(pred - real) / max(real, 1) < 0.20,
           f"predicho {pred:.0f}s vs real {real:.1f}s (Beggar llegó a {est['nivel']}, net {est['net']:.0f})")

        # --- el ETA baja parejo, no salta con cada level-up -------------------
        await fresh(pg, ESCENARIO)
        await agregar(pg, "net", "Wooden hut", "")
        await pg.evaluate("gameData.paused = false")
        lecturas = []
        for _ in range(8):
            await pg.wait_for_timeout(250)
            v = eta_segundos(await fila(pg))
            if v is not None:
                lecturas.append(v)
        await pg.evaluate("gameData.paused = true")
        saltos = [abs(lecturas[i + 1] - lecturas[i]) for i in range(len(lecturas) - 1)]
        baja = all(lecturas[i + 1] <= lecturas[i] + 1 for i in range(len(lecturas) - 1))
        ck("el ETA baja parejo en vez de saltar", baja and max(saltos) <= 2,
           f"lecturas: {lecturas}")

        # --- hito de net/día por cantidad ------------------------------------
        await fresh(pg, ESCENARIO)
        await agregar(pg, "netval", None, "110")
        await pg.evaluate("gameData.paused = false")
        await pg.wait_for_timeout(300)
        pred2 = eta_segundos(await fila(pg))
        await pg.evaluate("window.__t0 = performance.now()")
        await pg.wait_for_function("gameData.paused === true", timeout=60000)
        real2 = await pg.evaluate("(performance.now() - window.__t0) / 1000")
        ck("net/día por cantidad: también le pega",
           abs(pred2 - real2) / max(real2, 1) < 0.20,
           f"predicho {pred2:.0f}s vs real {real2:.1f}s")

        # --- objetivo inalcanzable: sin ETA en vez de uno inventado -----------
        await fresh(pg, ESCENARIO)
        await agregar(pg, "net", "Grand palace", "")
        await pg.evaluate("gameData.paused = false")
        await pg.wait_for_timeout(1500)
        f = await fila(pg)
        ck("un objetivo que este job no alcanza no muestra ETA", "~" not in f, f[:80])

        # --- Bargaining abarata el objetivo mientras sube ---------------------
        await fresh(pg, ESCENARIO.replace("gameData.taskData['Concentration']",
                                          "gameData.taskData['Bargaining']"))
        await pg.evaluate("gameData.taskData['Bargaining'].xpMultipliers.push(() => 400)")
        await agregar(pg, "net", "Wooden hut", "")
        await pg.evaluate("gameData.paused = false")
        await pg.wait_for_timeout(300)
        pred3 = eta_segundos(await fila(pg))
        await pg.evaluate("window.__t0 = performance.now()")
        await pg.wait_for_function("gameData.paused === true", timeout=60000)
        real3 = await pg.evaluate("(performance.now() - window.__t0) / 1000")
        barg = await pg.evaluate("gameData.taskData['Bargaining'].level")
        ck("con Bargaining subiendo, el umbral que se mueve también entra en la cuenta",
           abs(pred3 - real3) / max(real3, 1) < 0.20,
           f"predicho {pred3:.0f}s vs real {real3:.1f}s (Bargaining llegó a {barg})")

        # --- rendimiento -----------------------------------------------------
        await fresh(pg, ESCENARIO)
        await pg.evaluate("gameData.paused = false; window.__d0 = gameData.days")
        await pg.wait_for_timeout(1200)
        libre = await pg.evaluate("(gameData.days - window.__d0) / 1.2")
        for prod in ("Grand palace", "Small palace", "Library"):
            await agregar(pg, "net", prod, "")
        await pg.evaluate("window.__d1 = gameData.days")
        await pg.wait_for_timeout(1200)
        con = await pg.evaluate("(gameData.days - window.__d1) / 1.2")
        ck("simular miles de level-ups no frena el juego", con > libre * 0.9,
           f"{libre:.1f} vs {con:.1f} días/s")

        await b.close()
    _pk.report(R, errs)

asyncio.run(main())
srv.terminate()
