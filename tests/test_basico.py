import asyncio

from playwright.async_api import async_playwright

import _pk

SCRIPT = _pk.SCRIPT
srv = _pk.serve()

async def main():
    results = []
    async with async_playwright() as p:
        b = await _pk.launch(p)
        pg = await b.new_page()
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.on("console", lambda m: errs.append("console."+m.type+": "+m.text) if m.type=="error" else None)
        await pg.goto(_pk.URL)
        await pg.wait_for_function("window.gameData && Object.keys(gameData.taskData).length>0")
        await pg.evaluate(SCRIPT)
        await pg.wait_for_selector("#pkHitos", timeout=5000)
        results.append(("panel inyectado", True))

        # 1) hito de monedas: agregar via UI
        await pg.select_option("#pkType", "coins")
        await pg.fill("#pkValue", "5k")
        await pg.click("#pkAdd")
        n = await pg.evaluate("document.querySelectorAll('#pkList li').length")
        results.append(("hito monedas agregado", n == 1))
        paused_before = await pg.evaluate("gameData.paused")
        await pg.evaluate("gameData.coins = 9999")
        await pg.wait_for_function("gameData.paused === true", timeout=4000)
        results.append(("pausa al superar monedas", (not paused_before) and True))
        banner = await pg.inner_text("#pkBanner")
        results.append(("banner mostrado", "Monedas" in banner))

        # 2) persistencia
        cfg = await pg.evaluate("localStorage.getItem('pkHitos_v1')")
        results.append(("config persistida", cfg is not None and "coins" in cfg))

        # 3) hito de nivel de task
        await pg.evaluate("gameData.paused=false")
        await pg.select_option("#pkType", "skill")
        await pg.select_option("#pkTarget", "Concentration")
        await pg.select_option("#pkField", "level")
        await pg.fill("#pkValue", "25")
        await pg.click("#pkAdd")
        await pg.evaluate("gameData.taskData['Concentration'].level = 30")
        await pg.wait_for_function("gameData.paused === true", timeout=4000)
        results.append(("pausa por nivel de skill", True))

        # 4) desbloqueo nuevo
        await pg.evaluate("gameData.paused=false; document.querySelector('#pkAnyUnlock').checked=true; document.querySelector('#pkAnyUnlock').dispatchEvent(new Event('change'))")
        await pg.evaluate("""
            const k = Object.keys(gameData.requirements).find(x => !gameData.requirements[x].completed);
            window.__k = k; gameData.requirements[k].completed = true;
        """)
        await pg.wait_for_function("gameData.paused === true", timeout=4000)
        banner = await pg.inner_text("#pkBanner")
        results.append(("pausa por desbloqueo nuevo", "desbloqueo" in banner.lower()))

        # 5) hito ya cumplido no pausa de una
        await pg.evaluate("gameData.paused=false")
        await pg.select_option("#pkType", "age")
        await pg.fill("#pkValue", "5")
        await pg.click("#pkAdd")
        await pg.wait_for_timeout(800)
        still = await pg.evaluate("gameData.paused")
        results.append(("hito ya cumplido no pausa", still == False))

        # 6) recarga: config sobrevive
        await pg.reload()
        await pg.wait_for_function("window.gameData && Object.keys(gameData.taskData).length>0")
        await pg.evaluate(SCRIPT)
        await pg.wait_for_selector("#pkHitos")
        n = await pg.evaluate("document.querySelectorAll('#pkList li').length")
        results.append(("hitos sobreviven al reload", n >= 3))

        # 7) el juego sigue avanzando cuando no hay hitos pendientes
        await pg.evaluate("gameData.paused=false; window.__d0=gameData.days")
        await pg.wait_for_timeout(1200)
        adv = await pg.evaluate("gameData.days > window.__d0")
        results.append(("juego avanza normal sin pausar", adv))

        await b.close()
    print("\n=== RESULTADOS ===")
    ok = True
    for name, res in results:
        print(("PASS " if res else "FAIL ") + name)
        ok = ok and res
    real_errs = [e for e in errs if "favicon" not in e.lower()]
    print("errores JS:", real_errs if real_errs else "ninguno")
    print("TOTAL:", "OK" if ok and not real_errs else "REVISAR")

asyncio.run(main())
srv.terminate()
