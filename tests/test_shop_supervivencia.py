"""El hito de Shop se cumple cuando sobrevivirías a la compra, no cuando la bancás.

La condición es la misma que decide el cartel de arriba del panel: comprándolo, o
no quedás en rojo, o quedás en rojo pero el ingreso del job te alcanza antes de
vaciarte.
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

async def agregar(pg, producto, margen=""):
    await pg.select_option("#pkType", "net")
    await pg.select_option("#pkTarget", producto)
    await pg.fill("#pkValue", margen)
    await pg.click("#pkAdd")

async def fila(pg):
    return await pg.evaluate(
        "[...document.querySelectorAll('#pkList li')].pop().innerText.replace(/\\n/g, ' ')")

# El cartel que el hito tiene que imitar, para comprobar que coinciden.
async def cartel(pg):
    return await pg.evaluate("document.querySelector('#pkVitals').innerText.replace(/\\n/g, ' § ')")

# Job que sube y con él el ingreso; Homeless no gasta, así que Wooden hut cuesta 100.
BASE = """
    gameData.currentProperty = gameData.itemData['Homeless'];
    gameData.currentMisc = [];
    gameData.currentJob = gameData.taskData['Beggar'];
    gameData.currentSkill = gameData.taskData['Concentration'];
    gameData.taskData['Beggar'].level = 0;
    gameData.taskData['Beggar'].xp = 0;
    gameData.taskData['Beggar'].xpMultipliers.push(() => 10);
    gameData.taskData['Beggar'].incomeMultipliers.push(() => 10);
"""

async def main():
    async with async_playwright() as p:
        b = await _pk.launch(p)
        pg = await b.new_page(); errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        await pg.goto(_pk.URL)

        # --- con caja de sobra, se cumple aunque el net no llegue al precio ---
        await fresh(pg, BASE + "gameData.coins = 1e7;")
        await agregar(pg, "Wooden hut")
        await pg.evaluate("gameData.paused = false")
        await pg.wait_for_timeout(500)
        est = await pg.evaluate("""({paused: gameData.paused,
            net: getIncome() - getExpense(), precio: gameData.itemData['Wooden hut'].getExpense(),
            hecho: JSON.parse(localStorage.getItem('pkHitos_v1')).milestones[0].done})""")
        ck("se cumple con el net todavía por debajo del precio",
           est['hecho'] is True and est['net'] < est['precio'],
           f"net {est['net']:.0f} < precio {est['precio']:.0f}, hito cumplido")

        # --- sin caja no se cumple: comprarlo te funde -----------------------
        await fresh(pg, BASE + "gameData.coins = 30;")
        await agregar(pg, "Wooden hut")
        await pg.wait_for_timeout(300)      # el panel repinta con el juego en pausa
        st = await pg.evaluate("""({paused: gameData.paused,
            hecho: JSON.parse(localStorage.getItem('pkHitos_v1')).milestones[0].done})""")
        f = await fila(pg)
        ck("con poca caja no se cumple todavía", st['hecho'] is False, f[:90])
        ck("y la fila dice cuánto aguantarías comprándolo", "te vaciás en" in f, f[:90])

        # --- coincide con el cartel de arriba --------------------------------
        # Se le da caja hasta que el cartel simulado diría "el ingreso lo alcanza".
        await fresh(pg, BASE + "gameData.coins = 30;")
        await agregar(pg, "Wooden hut")
        await pg.evaluate("gameData.paused = false")
        await pg.wait_for_function("gameData.paused === true", timeout=60000)
        # al pausar, comprarlo tiene que ser sobrevivible: se comprueba a mano
        veredicto = await pg.evaluate("""(() => {
            const g = gameData;
            const prop = g.currentProperty, misc = g.currentMisc, pausa = g.paused;
            g.paused = false;   // getGameSpeed() vale 0 en pausa y nada avanzaría
            try {
                g.currentProperty = g.itemData['Wooden hut'];
                const net = getIncome() - getExpense();
                if (net >= 0) return {seguro: true, motivo: 'ni en rojo quedás', net};
                // ¿el ingreso alcanza antes de vaciarte? simulación tick a tick
                const job = g.currentJob, L0 = job.level, X0 = job.xp;
                let coins = g.coins, t = 0;
                const v = getGameSpeed() / updateSpeed;
                try {
                    while (coins > 0 && t < 200000) {
                        const n = getIncome() - getExpense();
                        if (n >= 0) return {seguro: true, motivo: 'el ingreso lo alcanzó', net, ticks: t};
                        coins += n * v;
                        job.xp += job.getXpGain() * v;
                        while (job.xp >= job.getMaxXp()) { job.xp -= job.getMaxXp(); job.level++; }
                        t++;
                    }
                } finally { job.level = L0; job.xp = X0; }
                return {seguro: false, motivo: 'te vaciaste', net};
            } finally { g.currentProperty = prop; g.currentMisc = misc; g.paused = pausa; }
        })()""")
        ck("al pausar, comprarlo es efectivamente sobrevivible",
           veredicto['seguro'] is True,
           f"{veredicto['motivo']} (net comprándolo: {veredicto['net']:.0f})")

        # --- el margen sigue significando colchón ----------------------------
        await fresh(pg, BASE + "gameData.coins = 1500;")
        await agregar(pg, "Wooden hut")
        await pg.wait_for_timeout(150)
        sin_margen = await pg.evaluate("JSON.parse(localStorage.getItem('pkHitos_v1')).milestones[0].done")
        await fresh(pg, BASE + "gameData.coins = 1500;")
        await agregar(pg, "Wooden hut", "4")
        await pg.wait_for_timeout(150)
        con_margen = await pg.evaluate("JSON.parse(localStorage.getItem('pkHitos_v1')).milestones[0].done")
        ck("un margen alto exige más: pide sobrevivir a algo más caro",
           sin_margen != con_margen or con_margen is False,
           f"sin margen: {sin_margen}, con margen x4: {con_margen}")

        # --- lo que ya tenés puesto sigue contando como cumplido -------------
        await fresh(pg, BASE + "gameData.currentMisc = [gameData.itemData['Book']]; gameData.coins = 1e7;")
        await agregar(pg, "Book")
        await pg.wait_for_timeout(150)
        f = await fila(pg)
        ck("un Misc que ya tenés sigue dando por cumplido", "ya lo tenés" in f, f[:70])

        # --- vaciarte después de muerto no es vaciarte ------------------------
        # Grand palace es tan caro que el ingreso no lo alcanza nunca: lo único que
        # puede dar por cumplido el hito es que la vida se acabe antes que la caja.
        await fresh(pg, BASE + "gameData.coins = 1e9;")
        await agregar(pg, "Grand palace")
        await pg.wait_for_timeout(250)
        lejos = await pg.evaluate("""({
            hecho: JSON.parse(localStorage.getItem('pkHitos_v1')).milestones[0].done,
            diasDeVida: Math.round(getLifespan() - gameData.days)})""")
        ck("con vida por delante, un producto impagable no se cumple",
           lejos['hecho'] is False, f"quedan {lejos['diasDeVida']} días de vida")

        await fresh(pg, BASE + "gameData.coins = 1e9; gameData.days = getLifespan() - 50;")
        await agregar(pg, "Grand palace")
        await pg.wait_for_timeout(250)
        cerca = await pg.evaluate("""({
            hecho: JSON.parse(localStorage.getItem('pkHitos_v1')).milestones[0].done,
            diasDeVida: Math.round(getLifespan() - gameData.days)})""")
        ck("al final de la vida sí: no llegás a vaciarte",
           cerca['hecho'] is True, f"quedan {cerca['diasDeVida']} días de vida")

        # --- rendimiento ------------------------------------------------------
        await fresh(pg, BASE + "gameData.coins = 200;")
        await pg.evaluate("gameData.paused = false; window.__d0 = gameData.days")
        await pg.wait_for_timeout(1200)
        libre = await pg.evaluate("(gameData.days - window.__d0) / 1.2")
        for prod in ("Grand palace", "Small palace", "Library"):
            await agregar(pg, prod)
        await pg.evaluate("window.__d1 = gameData.days")
        await pg.wait_for_timeout(1200)
        con = await pg.evaluate("(gameData.days - window.__d1) / 1.2")
        ck("simular la compra en cada tick no frena el juego", con > libre * 0.9,
           f"{libre:.1f} vs {con:.1f} días/s")

        await b.close()
    _pk.report(R, errs)

asyncio.run(main())
srv.terminate()
