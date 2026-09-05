"""El ETA de un hito de nivel contra el tiempo que tarda de verdad.

Hay skills que se potencian a sí mismas, así que la xp/día de ahora no vale para
todo el tramo. Estas pruebas comparan la predicción del panel con el tiempo real
—medido en ticks a partir de los días transcurridos, que no depende del reloj de
pared— y contra la estimación plana que se usaba antes.
"""
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

# Estimación plana: la que salía de dividir la xp que falta por la tasa de ahora.
PLANA = """(skill, target) => {
    const t = gameData.taskData[skill];
    const maxXpAt = (task, L) => Math.round(task.baseData.maxXp * (L + 1) * Math.pow(1.01, L));
    let falta = maxXpAt(t, t.level) - t.xp;
    for (let L = t.level + 1; L < target; L++) falta += maxXpAt(t, L);
    const porTick = t.getXpGain() * getGameSpeed() / updateSpeed;
    return falta / porTick / updateSpeed;   // en segundos
}"""

async def correr(pg, skill, nivel_inicial, target, multiplicador):
    """Prepara, lee la predicción, corre de verdad y devuelve (predicho, plano, real) en s."""
    await pg.evaluate("localStorage.clear()")
    await pg.reload()
    await pg.wait_for_function("window.gameData && Object.keys(gameData.taskData).length>0")
    await pg.evaluate(SCRIPT)
    await pg.wait_for_selector("#pkHitos")
    await pg.evaluate(f"""
        gameData.paused = true;
        gameData.currentSkill = gameData.taskData['{skill}'];
        gameData.taskData['{skill}'].level = {nivel_inicial};
        gameData.taskData['{skill}'].xp = 0;
        gameData.taskData['{skill}'].xpMultipliers.push(() => {multiplicador});
    """)
    await pg.select_option("#pkType", "skill")
    await pg.select_option("#pkTarget", skill)
    await pg.select_option("#pkField", "level")
    await pg.fill("#pkValue", str(target))
    await pg.click("#pkAdd")
    await pg.wait_for_timeout(350)

    # las dos estimaciones se leen con el juego ya corriendo: getGameSpeed() vale 0
    # en pausa y dejaría las cuentas en infinito
    await pg.evaluate("gameData.paused = false")
    fila = await pg.evaluate("document.querySelector('#pkList li').innerText.replace(/\\n/g, ' ')")
    predicho = eta_segundos(fila)
    plano = await pg.evaluate(f"({PLANA})('{skill}', {target})")

    # se mide en ticks vía los días transcurridos: inmune a la cadencia del navegador
    await pg.evaluate("window.__d0 = gameData.days; window.__v = getGameSpeed() / updateSpeed")
    await pg.wait_for_function("gameData.paused === true", timeout=90000)
    real = await pg.evaluate("((gameData.days - window.__d0) / window.__v) / updateSpeed")
    return predicho, plano, real, fila

async def main():
    async with async_playwright() as p:
        b = await _pk.launch(p)
        pg = await b.new_page(); errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        await pg.goto(_pk.URL)

        # --- Concentration se potencia a sí misma ---------------------------
        pred, plano, real, fila = await correr(pg, 'Concentration', 100, 300, 20000)
        err_nuevo = abs(pred - real) / real
        err_plano = abs(plano - real) / real
        ck("Concentration: la predicción le pega al tiempo real", err_nuevo < 0.15,
           f"predicho {pred:.0f}s vs real {real:.0f}s → {err_nuevo*100:.0f}% de error")
        ck("Concentration: la estimación plana se quedaba larga", err_plano > 0.35,
           f"plana {plano:.0f}s vs real {real:.0f}s → {err_plano*100:.0f}% de error")
        ck("y la nueva es claramente mejor que la plana", err_nuevo < err_plano / 2,
           f"{err_nuevo*100:.0f}% contra {err_plano*100:.0f}%")

        # --- Strength no se potencia a sí misma: no debería cambiar nada -----
        pred2, plano2, real2, _ = await correr(pg, 'Strength', 50, 150, 20000)
        ck("Strength: sin auto-boost, la predicción sigue siendo buena",
           abs(pred2 - real2) / real2 < 0.15,
           f"predicho {pred2:.0f}s vs real {real2:.0f}s")
        ck("Strength: predicción integrada y plana coinciden",
           abs(pred2 - plano2) / max(plano2, 1) < 0.10,
           f"integrada {pred2:.0f}s vs plana {plano2:.0f}s")

        # --- objetivos absurdos: ni exponenciales ni cuentas caras -----------
        await pg.evaluate("localStorage.clear()")
        await pg.reload()
        await pg.wait_for_function("window.gameData && Object.keys(gameData.taskData).length>0")
        await pg.evaluate(SCRIPT)
        await pg.wait_for_selector("#pkHitos")
        await pg.evaluate("gameData.paused = false")
        await pg.evaluate("window.__d0 = gameData.days")
        await pg.wait_for_timeout(1200)
        libre = await pg.evaluate("(gameData.days - window.__d0) / 1.2")
        for skill in ('Concentration', 'Meditation', 'Strength'):
            await pg.select_option("#pkType", "skill")
            await pg.select_option("#pkTarget", skill)
            await pg.select_option("#pkField", "level")
            await pg.fill("#pkValue", "9000")
            await pg.click("#pkAdd")
        await pg.evaluate("window.__d1 = gameData.days")
        await pg.wait_for_timeout(1200)
        con = await pg.evaluate("(gameData.days - window.__d1) / 1.2")
        fila = await pg.evaluate("document.querySelector('#pkList li').innerText.replace(/\\n/g, ' ')")
        ck("un objetivo inalcanzable no imprime notación exponencial",
           'e+' not in fila and '>999d' in fila, fila[:70])
        ck("integrar miles de niveles no frena el juego", con > libre * 0.9,
           f"{libre:.1f} vs {con:.1f} días/s")

        await b.close()
    _pk.report(R, errs)

asyncio.run(main())
srv.terminate()
