import asyncio
from playwright.async_api import async_playwright

import _pk
SCRIPT = _pk.SCRIPT
srv = _pk.serve()
R=[]
def ck(n,c,info=""): R.append((n,bool(c),info))

async def fresh(pg, extra=""):
    await pg.evaluate("localStorage.clear()"); await pg.reload()
    await pg.wait_for_function("window.gameData && Object.keys(gameData.taskData).length>0")
    await pg.evaluate(SCRIPT); await pg.wait_for_selector("#pkHitos")
    if extra: await pg.evaluate(extra)

async def main():
    async with async_playwright() as p:
        b = await _pk.launch(p)
        pg = await b.new_page(); errs=[]
        pg.on("pageerror", lambda e: errs.append(str(e)))
        await pg.goto(_pk.URL)

        # ---------- Property: umbral = diferencia contra la actual ----------
        await fresh(pg, "gameData.currentProperty = gameData.itemData['Cottage']; gameData.paused=true")
        exp = await pg.evaluate("""({house: gameData.itemData['Large house'].getExpense(),
                                     cottage: gameData.itemData['Cottage'].getExpense()})""")
        await pg.select_option("#pkType","net"); await pg.select_option("#pkTarget","Large house")
        await pg.fill("#pkValue",""); await pg.click("#pkAdd")
        await pg.wait_for_timeout(400)
        txt = await pg.inner_text("#pkList")
        delta = exp['house'] - exp['cottage']
        # el umbral mostrado debe ser la diferencia, no el precio de lista
        ok_delta = "/ 24.3k" in txt and "/ 25.0k" not in txt
        ck("Property: umbral = precio − property actual", ok_delta,
           f"{exp['house']:.0f} − {exp['cottage']:.0f} = {delta:.0f} | panel: {txt.replace(chr(10),' ')[:70]}")
        ck("Property: el panel muestra el desglose", "de Cottage" in txt, txt.replace(chr(10),' ')[:70])

        # con Homeless (gasto 0) el umbral vuelve a ser el precio entero
        await fresh(pg, "gameData.currentProperty = gameData.itemData['Homeless']; gameData.paused=true")
        await pg.select_option("#pkType","net"); await pg.select_option("#pkTarget","Large house")
        await pg.fill("#pkValue",""); await pg.click("#pkAdd")
        await pg.wait_for_timeout(300)
        txt2 = await pg.inner_text("#pkList")
        ck("Property: sin property previa el umbral es el precio entero",
           "de Cottage" not in txt2 and "25.0k" in txt2.replace(",", "."), txt2.replace(chr(10),' ')[:60])

        # umbral negativo (bajar de property): se cumple si el net POSTERIOR queda >= 0
        await fresh(pg, """gameData.currentProperty = gameData.itemData['Cottage'];
                           gameData.taskData['Beggar'].incomeMultipliers.push(() => 160);
                           gameData.currentJob = gameData.taskData['Beggar']; gameData.paused=true;""")
        await pg.select_option("#pkType","net"); await pg.select_option("#pkTarget","Tent")
        await pg.fill("#pkValue",""); await pg.click("#pkAdd")
        await pg.select_option("#pkTarget","House"); await pg.fill("#pkValue",""); await pg.click("#pkAdd")
        await pg.wait_for_timeout(300)
        ms = await pg.evaluate("JSON.parse(localStorage.getItem('pkHitos_v1')).milestones")
        info = await pg.evaluate("({net: getIncome()-getExpense(), tent: gameData.itemData['Tent'].getExpense(), cottage: gameData.itemData['Cottage'].getExpense()})")
        ck("Bajar de property: se cumple si el net posterior queda en verde",
           ms[0]['done'] == True and ms[1]['done'] == False,
           f"net={info['net']:.0f}, Tent={info['tent']:.0f}, Cottage actual={info['cottage']:.0f}")

        # ---------- Misc: precio entero, y 0 si ya lo tenés ----------
        await fresh(pg, "gameData.currentMisc = []; gameData.paused=true")
        await pg.select_option("#pkType","net"); await pg.select_option("#pkTarget","Sapphire charm")
        await pg.fill("#pkValue",""); await pg.click("#pkAdd")
        await pg.wait_for_timeout(300)
        t3 = await pg.inner_text("#pkList")
        ck("Misc: umbral = precio entero", "50.0k" in t3.replace(",", "."), t3.replace(chr(10),' ')[:60])
        await fresh(pg, "gameData.currentMisc = [gameData.itemData['Book']]; gameData.paused=true")
        await pg.select_option("#pkType","net"); await pg.select_option("#pkTarget","Book")
        await pg.fill("#pkValue",""); await pg.click("#pkAdd")
        await pg.wait_for_timeout(300)
        t4 = await pg.inner_text("#pkList")
        ck("Misc ya comprado: umbral 0", "ya lo tenés" in t4, t4.replace(chr(10),' ')[:60])

        # ---------- nivel por defecto en Jobs ----------
        await fresh(pg, "gameData.paused=true")
        await pg.select_option("#pkType","job")
        v = await pg.input_value("#pkValue"); h = await pg.inner_text("#pkHint")
        ck("Job: nivel 10 por defecto", v == "10", f"valor={v!r}")
        ck("Job: el hint explica de dónde sale el 10", "nivel 10" in h, h[:70])
        await pg.select_option("#pkTarget","Knight")
        v2 = await pg.input_value("#pkValue"); h2 = await pg.inner_text("#pkHint")
        ck("Job: se recalcula al cambiar de job", v2 == "10" and "Knight" in h2, f"{v2} · {h2[:50]}")
        # editable
        await pg.fill("#pkValue","250"); await pg.click("#pkAdd")
        m = await pg.evaluate("JSON.parse(localStorage.getItem('pkHitos_v1')).milestones[0]")
        ck("Job: el valor sigue siendo editable", m['value'] == 250, str(m['value']))

        # skills: sugiere el requisito real, no 10
        await pg.select_option("#pkType","skill"); await pg.select_option("#pkTarget","Concentration")
        v3 = await pg.input_value("#pkValue"); h3 = await pg.inner_text("#pkHint")
        ck("Skill: sugiere el primer requisito real", v3 == "5" and "Productivity" in h3, f"{v3} · {h3[:50]}")
        await pg.select_option("#pkTarget","Mana control")
        v4 = await pg.input_value("#pkValue")
        ck("Skill: distinto requisito, distinta sugerencia", v4 == "400", f"valor={v4!r}")
        await pg.select_option("#pkField","maxLevel")
        v5 = await pg.input_value("#pkValue")
        ck("Nivel máximo: no precarga nada", v5 == "", f"valor={v5!r}")

        # si ya pasaste ese nivel, se mantiene el 10 pero el hint lo aclara
        await fresh(pg, "gameData.taskData['Beggar'].level = 40; gameData.paused=true")
        await pg.select_option("#pkType","job"); await pg.select_option("#pkTarget","Beggar")
        v6 = await pg.input_value("#pkValue"); h6 = await pg.inner_text("#pkHint")
        ck("Job ya pasado de nivel: avisa que el requisito está cumplido",
           v6 == "10" and "ya cumplido" in h6, f"{v6} · {h6[:60]}")
        # y con un job que sí tiene requisito pendiente más alto, lo usa
        await fresh(pg, "gameData.paused=true")
        await pg.select_option("#pkType","skill"); await pg.select_option("#pkTarget","Strength")
        v7 = await pg.input_value("#pkValue")
        ck("Sugiere el menor requisito pendiente", v7 == "5", f"valor={v7!r} (Squire pide Strength 5)")

        # ---------- regresión: sigue pausando ----------
        await fresh(pg, "gameData.currentProperty = gameData.itemData['Tent']; gameData.paused=false")
        await pg.select_option("#pkType","net"); await pg.select_option("#pkTarget","Wooden hut")
        await pg.fill("#pkValue",""); await pg.click("#pkAdd")
        pend = await pg.evaluate("gameData.paused")
        await pg.evaluate("gameData.taskData[gameData.currentJob.name].incomeMultipliers.push(() => 100000)")
        await pg.wait_for_function("gameData.paused === true", timeout=8000)
        net = await pg.evaluate("getIncome()-getExpense()")
        need = await pg.evaluate("gameData.itemData['Wooden hut'].getExpense() - gameData.itemData['Tent'].getExpense()")
        ck("net vs property sigue pausando, con el umbral incremental",
           pend == False and net >= need, f"net={net:.0f} ≥ Δ={need:.0f}")

        await b.close()
    print("\n=== RESULTADOS ===")
    ok=True
    for n,r,info in R:
        print(("PASS " if r else "FAIL ")+n+(f"   [{info}]" if info else "")); ok = ok and r
    real=[e for e in errs if "favicon" not in e.lower()]
    print("errores JS:", real or "ninguno"); print("TOTAL:", "OK" if ok and not real else "REVISAR")
asyncio.run(main())
srv.terminate()
