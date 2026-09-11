"""Los Misc que tenés puestos cuentan: no se descuentan ni se apagan.

Cuando el hito del Shop medía "¿me alcanza el net?" tenía sentido suponer que al
comprar algo ibas a apagar los boosts puntuales. Desde que la pregunta es cuánto
aguantás, hay que contar lo que realmente vas a seguir pagando — y encima a veces
conviene tenerlos puestos.
"""
import asyncio

from playwright.async_api import async_playwright

import _pk

SCRIPT = _pk.SCRIPT
srv = _pk.serve()
R = []
def ck(n, c, info=""): R.append((n, bool(c), info))

async def fresh(pg, extra=""):
    await pg.evaluate("localStorage.clear()")
    await pg.reload()
    await pg.wait_for_function("window.gameData && Object.keys(gameData.taskData).length>0")
    await pg.evaluate(SCRIPT)
    await pg.wait_for_selector("#pkHitos")
    await pg.evaluate("gameData.paused = true")
    if extra:
        await pg.evaluate(extra)

async def umbral(pg, target, margen=""):
    await pg.select_option("#pkType", "net")
    await pg.select_option("#pkTarget", target)
    await pg.fill("#pkValue", margen)
    await pg.click("#pkAdd")
    await pg.wait_for_timeout(350)
    return await pg.evaluate(
        "[...document.querySelectorAll('#pkList li')].pop().innerText.replace(/\\n/g,' ')")

# Simulación literal del bucle del juego, como referencia independiente.
SIM = """(prop, coins, misc) => {
    const g = gameData;
    const p0 = g.currentProperty, m0 = g.currentMisc, pa = g.paused, c0 = g.coins;
    const job = g.currentJob, skill = g.currentSkill;
    const LJ = job.level, XJ = job.xp, LS = skill.level, XS = skill.xp;
    g.paused = false;
    g.currentProperty = g.itemData[prop];
    g.coins = coins;
    g.currentMisc = misc.map(n => g.itemData[n]);
    try {
        let t = 0; const v = getGameSpeed() / updateSpeed;
        while (g.coins > 0 && t < 200000) {
            g.coins += (getIncome() - getExpense()) * v;
            job.xp += job.getXpGain() * v;
            while (job.xp >= job.getMaxXp()) { job.xp -= job.getMaxXp(); job.level++; }
            skill.xp += skill.getXpGain() * v;
            while (skill.xp >= skill.getMaxXp()) { skill.xp -= skill.getMaxXp(); skill.level++; }
            t++;
        }
        return t;
    } finally {
        g.currentProperty = p0; g.currentMisc = m0; g.paused = pa; g.coins = c0;
        job.level = LJ; job.xp = XJ; skill.level = LS; skill.xp = XS;
    }
}"""

# Squire con Strength de skill: Dumbbells acelera Strength y Strength paga en militar.
MILITAR = """
    gameData.currentJob = gameData.taskData['Squire'];
    gameData.currentSkill = gameData.taskData['Strength'];
    gameData.taskData['Squire'].level = 30;
    gameData.taskData['Strength'].level = 0;
    gameData.taskData['Squire'].incomeMultipliers.push(() => 40);
    gameData.taskData['Strength'].xpMultipliers.push(() => 30);
"""

async def main():
    async with async_playwright() as p:
        b = await _pk.launch(p)
        pg = await b.new_page(); errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        await pg.goto(_pk.URL)

        # --- el umbral que se muestra ya no descuenta los Misc ---------------
        await fresh(pg, """
          gameData.currentProperty = gameData.itemData['Tent'];
          gameData.currentMisc = [gameData.itemData['Dumbbells']];
          gameData.coins = 200;
        """)
        fila = await umbral(pg, "Wooden hut")
        ck("Wooden hut = 100 − Tent 15, sin descontar las Dumbbells",
           "/ 85" in fila and "Dumbbells" not in fila, fila[:85])
        ck("el desglose solo nombra la Property que se reemplaza",
           "de Tent" in fila, fila[:85])

        # --- y la Property sí se sigue reemplazando --------------------------
        await fresh(pg, """
          gameData.currentProperty = gameData.itemData['Cottage'];
          gameData.currentMisc = [];
          gameData.coins = 200;
        """)
        fila = await umbral(pg, "Large house")
        ck("la Property actual se sigue descontando", "/ 24.3k" in fila, fila[:85])

        # --- Dumbbells puestas alargan el aguante en militar -----------------
        await fresh(pg, MILITAR)
        con = await pg.evaluate(f"({SIM})('House', 2e6, ['Dumbbells'])")
        sin = await pg.evaluate(f"({SIM})('House', 2e6, [])")
        ck("con Dumbbells puestas se aguanta MÁS, aunque cuesten 50/día",
           con > sin, f"{con} ticks con, {sin} sin (Strength paga en militar)")

        # --- la cuenta del script coincide con la simulación literal ---------
        await fresh(pg, MILITAR + """
            gameData.currentProperty = gameData.itemData['Cottage'];
            gameData.currentMisc = [gameData.itemData['Dumbbells']];
            gameData.coins = 2e6;
        """)
        await pg.evaluate("gameData.paused = false")
        await pg.wait_for_timeout(250)
        cartel = await pg.evaluate(
            "document.querySelector('#pkVitals').innerText.replace(/\\n/g,' § ')")
        estado = await pg.evaluate("""({net: getIncome() - getExpense(),
                                        gasto: getExpense()})""")
        ck("el gasto que usa el panel incluye las Dumbbells",
           abs(estado['gasto'] - 800) < 1, f"gasto {estado['gasto']:.0f} (Cottage 750 + Dumbbells 50)")

        await b.close()
    _pk.report(R, errs)

asyncio.run(main())
srv.terminate()
