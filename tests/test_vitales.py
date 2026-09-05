"""Cuenta regresiva de muerte y de saldo en cero, y la pausa antes de quebrar."""
import asyncio
import re

from playwright.async_api import async_playwright

import _pk

SCRIPT = _pk.SCRIPT
srv = _pk.serve()
R = []
def ck(n, c, info=""): R.append((n, bool(c), info))

# El time warping del juego es logarítmico y no pasa de x6,4; para que los días
# vuelen en una prueba se pisa su efecto.
RELOJ = "gameData.taskData['Time warping'].getEffect = () => 200; gameData.timeWarpingEnabled = true;"

# Transcripción literal del tick del juego, como referencia independiente de las
# fórmulas del script. Corre entre ticks reales, así que es atómica.
SIM_MUERTE = """(() => {
    const skill = gameData.currentSkill;
    const L0 = skill.level, X0 = skill.xp, D0 = gameData.days;
    let ticks = 0;
    try {
        while (gameData.days < getLifespan() && ticks < 5e5) {
            gameData.days += applySpeed(1);
            skill.xp += applySpeed(skill.getXpGain());
            while (skill.xp >= skill.getMaxXp()) { skill.xp -= skill.getMaxXp(); skill.level++; }
            ticks++;
        }
    } finally { skill.level = L0; skill.xp = X0; gameData.days = D0; }
    return ticks / updateSpeed;   // en segundos
})()"""

def eta_segundos(texto):
    m = re.search(r'~(?:(\d+)d|(\d+)h (\d+)m|(\d+)m (\d+)s|(\d+)s|<1s|>999d)', texto)
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

async def vitales(pg):
    return await pg.evaluate("document.querySelector('#pkVitals').innerText.replace(/\\n/g, ' § ')")


def linea(texto, clave):
    """El bloque tiene dos líneas; devuelve la que contiene `clave`."""
    for parte in texto.split(' § '):
        if clave in parte:
            return parte
    return ''

async def main():
    async with async_playwright() as p:
        b = await _pk.launch(p)
        pg = await b.new_page(); errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        await pg.goto(_pk.URL)

        # --- muerte: predicción contra el tiempo real ------------------------
        await fresh(pg, RELOJ + "gameData.days = getLifespan() - 4000;")
        await pg.evaluate("gameData.paused = false")
        await pg.wait_for_timeout(400)
        v = await vitales(pg)
        pred = eta_segundos(v)
        ck("el panel muestra la cuenta regresiva de muerte",
           "Muerte en" in v and "años" in v, v[:70])
        await pg.evaluate("window.__t0 = performance.now()")
        await pg.wait_for_function("gameData.days >= getLifespan()", timeout=40000)
        real = await pg.evaluate("(performance.now() - window.__t0) / 1000")
        ck("la muerte llega cuando decía", abs(pred - real) / max(real, 1) < 0.30,
           f"predicho {pred:.0f}s vs real {real:.1f}s")

        # --- muerte con Immortality subiendo: contra la simulación literal ----
        await fresh(pg, RELOJ + """
            gameData.days = getLifespan() - 8000;
            gameData.currentSkill = gameData.taskData['Immortality'];
            gameData.taskData['Immortality'].level = 0;
            gameData.taskData['Immortality'].xpMultipliers.push(() => 40);
        """)
        await pg.evaluate("gameData.paused = false")
        await pg.wait_for_timeout(400)
        v = await vitales(pg)
        pred2 = eta_segundos(v)
        sim = await pg.evaluate(SIM_MUERTE)
        ingenua = await pg.evaluate(
            "((getLifespan() - gameData.days) / (getGameSpeed() / updateSpeed)) / updateSpeed")
        await pg.evaluate("gameData.paused = true")
        ck("subiendo Immortality, la predicción coincide con la simulación",
           abs(pred2 - sim) / max(sim, 1) < 0.10,
           f"predicho {pred2:.0f}s vs simulado {sim:.1f}s")
        ck("no tenerlo en cuenta se quedaba corto", ingenua < sim * 0.75,
           f"ingenua {ingenua:.0f}s vs simulado {sim:.1f}s")

        # --- saldo en cero con el job subiendo -------------------------------
        await fresh(pg, """
            gameData.currentProperty = gameData.itemData['Tent'];
            gameData.currentJob = gameData.taskData['Beggar'];
            gameData.currentSkill = gameData.taskData['Concentration'];
            gameData.taskData['Beggar'].level = 0;
            gameData.taskData['Beggar'].xpMultipliers.push(() => 60);
            gameData.coins = 100;
        """)
        await pg.evaluate("gameData.paused = false")
        await pg.wait_for_timeout(400)
        v = await vitales(pg)
        pred3 = eta_segundos(linea(v, 'Saldo en cero'))
        ingenua3 = await pg.evaluate("""(() => { const net = getIncome() - getExpense();
            return net >= 0 ? null
                 : (gameData.coins / (-net * (getGameSpeed()/updateSpeed))) / updateSpeed; })()""")
        ck("el panel avisa del saldo en cero", "Saldo en cero" in v, v[:80])
        await pg.evaluate("window.__t0 = performance.now()")
        await pg.wait_for_function("gameData.paused === true", timeout=60000)
        real3 = await pg.evaluate("(performance.now() - window.__t0) / 1000")
        estado = await pg.evaluate("""({coins: gameData.coins, prop: gameData.currentProperty.name,
                                        banner: document.querySelector('#pkBanner').innerText,
                                        nivel: gameData.taskData['Beggar'].level})""")
        ck("pausa al llegar a cero", "sin monedas" in estado['banner'], estado['banner'][:50])
        ck("frena ANTES de quebrar: no te saca la property",
           estado['coins'] >= 0 and estado['prop'] == 'Tent',
           f"monedas={estado['coins']:.6f}, property={estado['prop']}")
        ck("la predicción del saldo le pega al tiempo real",
           abs(pred3 - real3) / max(real3, 1) < 0.30,
           f"predicho {pred3:.0f}s vs real {real3:.1f}s (Beggar llegó a {estado['nivel']})")
        ck("ignorar la suba del job se quedaba corto", ingenua3 < real3 * 0.75,
           f"ingenua {ingenua3:.0f}s vs real {real3:.1f}s")

        # --- si el ingreso lo alcanza, avisa que no vas a quebrar ------------
        await fresh(pg, """
            gameData.currentProperty = gameData.itemData['Tent'];
            gameData.currentJob = gameData.taskData['Beggar'];
            gameData.taskData['Beggar'].level = 0;
            gameData.taskData['Beggar'].xpMultipliers.push(() => 5000);
            gameData.coins = 1e6;
        """)
        await pg.evaluate("gameData.paused = false")
        await pg.wait_for_timeout(600)
        v = await vitales(pg)
        ck("con el ingreso creciendo, avisa que el net se recupera antes",
           "lo alcanza antes" in v or "Saldo en cero" not in v, v[:90])

        # --- con la opción apagada no pausa ----------------------------------
        await fresh(pg, """
            gameData.currentProperty = gameData.itemData['Cottage'];
            gameData.currentJob = gameData.taskData['Beggar'];
            gameData.coins = 50;
        """)
        await pg.evaluate("""const e = document.querySelector('#pkBroke');
                             e.checked = false; e.dispatchEvent(new Event('change'));
                             gameData.paused = false;""")
        await pg.wait_for_timeout(2500)
        st = await pg.evaluate("({paused: gameData.paused, prop: gameData.currentProperty.name})")
        ck("con la opción apagada el juego sigue y te funde",
           st['paused'] is False and st['prop'] == 'Homeless', str(st))

        await b.close()
    _pk.report(R, errs)

asyncio.run(main())
srv.terminate()
