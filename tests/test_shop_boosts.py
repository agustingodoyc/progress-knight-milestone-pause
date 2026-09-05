"""El umbral del Shop descuenta los boosts puntuales que darías de baja."""
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
    if extra:
        await pg.evaluate(extra)
    await pg.evaluate("gameData.paused = true")

async def umbral(pg, target, margen=""):
    """Agrega un hito de Shop y devuelve el umbral y el texto de la fila."""
    await pg.select_option("#pkType", "net")
    await pg.select_option("#pkTarget", target)
    await pg.fill("#pkValue", margen)
    await pg.click("#pkAdd")
    await pg.wait_for_timeout(350)
    fila = await pg.evaluate("[...document.querySelectorAll('#pkList li')].pop().innerText.replace(/\\n/g,' ')")
    # el umbral es el segundo número de "actual / umbral"
    return fila

async def main():
    async with async_playwright() as p:
        b = await _pk.launch(p)
        pg = await b.new_page(); errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        await pg.goto(_pk.URL)

        # el caso del enunciado: Wooden hut con Tent y Dumbbells puestos
        await fresh(pg, """
          gameData.currentProperty = gameData.itemData['Tent'];
          gameData.currentMisc = [gameData.itemData['Dumbbells']];
        """)
        precios = await pg.evaluate("""({hut: gameData.itemData['Wooden hut'].getExpense(),
                                         tent: gameData.itemData['Tent'].getExpense(),
                                         dumb: gameData.itemData['Dumbbells'].getExpense()})""")
        fila = await umbral(pg, "Wooden hut")
        ck("Wooden hut = 100 − Tent 15 − Dumbbells 50 = 35",
           "/ 35" in fila,
           f"{precios['hut']:.0f}−{precios['tent']:.0f}−{precios['dumb']:.0f} · {fila[:70]}")
        ck("el panel muestra el desglose completo",
           "de Tent" in fila and "de Dumbbells" in fila, fila[:80])

        # los boosts que sirven siempre no se descuentan
        await fresh(pg, """
          gameData.currentProperty = gameData.itemData['Tent'];
          gameData.currentMisc = [gameData.itemData['Book'], gameData.itemData['Personal squire'],
                                  gameData.itemData['Butler']];
        """)
        fila = await umbral(pg, "Wooden hut")
        ck("Book, Personal squire y Butler no se descuentan", "/ 85" in fila, fila[:80])

        # Steel longsword y Sapphire charm sí
        await fresh(pg, """
          gameData.currentProperty = gameData.itemData['Homeless'];
          gameData.currentMisc = [gameData.itemData['Steel longsword'], gameData.itemData['Sapphire charm']];
        """)
        fila = await umbral(pg, "Grand palace")
        esperado = await pg.evaluate("""gameData.itemData['Grand palace'].getExpense()
            - gameData.itemData['Steel longsword'].getExpense()
            - gameData.itemData['Sapphire charm'].getExpense()""")
        ck("Steel longsword y Sapphire charm sí se descuentan",
           "de Steel longsword, Sapphire charm" in fila, f"esperado {esperado:.0f} · {fila[:90]}")

        # con un Misc como objetivo, la Property NO se descuenta
        await fresh(pg, """
          gameData.currentProperty = gameData.itemData['Cottage'];
          gameData.currentMisc = [gameData.itemData['Dumbbells']];
        """)
        fila = await umbral(pg, "Steel longsword")
        ck("objetivo Misc: descuenta Dumbbells pero no la Property",
           "/ 950" in fila and "de Cottage" not in fila, fila[:80])

        # el propio objetivo no se descuenta a sí mismo
        await fresh(pg, """
          gameData.currentProperty = gameData.itemData['Homeless'];
          gameData.currentMisc = [gameData.itemData['Dumbbells']];
        """)
        fila = await umbral(pg, "Dumbbells")
        ck("si ya lo tenés puesto sigue siendo 'ya lo tenés'", "ya lo tenés" in fila, fila[:70])

        # sin Misc activos, el umbral es el de siempre
        await fresh(pg, """
          gameData.currentProperty = gameData.itemData['Cottage'];
          gameData.currentMisc = [];
        """)
        fila = await umbral(pg, "Large house")
        ck("sin boosts activos no cambia nada", "/ 24.3k" in fila, fila[:80])

        # y el hito pausa con el umbral nuevo, no con el precio de lista
        await fresh(pg, """
          gameData.currentProperty = gameData.itemData['Tent'];
          gameData.currentMisc = [gameData.itemData['Dumbbells']];
          gameData.currentJob = gameData.taskData['Beggar'];
          gameData.coins = 1e9;
        """)
        # con monedas de sobra: si el net queda en rojo y las monedas llegan a 0,
        # goBankrupt() te saca la property y los misc, y el escenario se desarma
        await pg.evaluate("gameData.paused = false")
        await umbral(pg, "Wooden hut")
        # se pisa getIncome() para manejar el ingreso a mano: con multiplicadores el
        # nivel del job sigue creciendo solo y el net cruza el umbral de un salto
        await pg.evaluate("window.__income = 96; window.getIncome = () => window.__income;")
        await pg.wait_for_timeout(900)
        casi = await pg.evaluate("({paused: gameData.paused, net: getIncome() - getExpense()})")
        ck("con el net por debajo del umbral no pausa",
           casi['paused'] is False and casi['net'] < 35, f"net={casi['net']:.1f}")
        await pg.evaluate("window.__income = 130")               # net = 65
        await pg.wait_for_function("gameData.paused === true", timeout=8000)
        net = await pg.evaluate("getIncome() - getExpense()")
        ck("pausa con el umbral descontado, sin esperar al precio de lista",
           35 <= net < 100, f"net={net:.1f} (umbral 35, precio de lista 100)")

        await b.close()
    _pk.report(R, errs)

asyncio.run(main())
srv.terminate()
