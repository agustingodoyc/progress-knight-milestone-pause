import asyncio
from playwright.async_api import async_playwright

import _pk
SCRIPT = _pk.SCRIPT
srv = _pk.serve()
R=[]
def ck(n,c,info=""): R.append((n,bool(c),info))

async def fresh(pg, precise=True, extra=""):
    await pg.evaluate("localStorage.clear()")
    await pg.reload()
    await pg.wait_for_function("window.gameData && Object.keys(gameData.taskData).length>0")
    await pg.evaluate(SCRIPT)
    await pg.wait_for_selector("#pkHitos")
    if not precise: await pg.uncheck("#pkPrecise")
    if extra: await pg.evaluate(extra)

# xp x5000 => un tick entero vale miles de xp: sin tick parcial se pasa varios niveles
FAST_XP = """
  gameData.currentSkill = gameData.taskData['Concentration'];
  gameData.taskData['Concentration'].xpMultipliers.push(() => 5000);
  gameData.paused = false;
"""
FAST_COINS = """
  gameData.currentJob = gameData.taskData['Beggar'];
  gameData.taskData['Beggar'].incomeMultipliers.push(() => 100000);
  gameData.coins = 0; gameData.paused = false;
"""
# el time warping del juego es logarítmico; para un reloj rápido se pisa getEffect
FAST_CLOCK = """
  gameData.taskData['Time warping'].getEffect = () => 5000;
  gameData.timeWarpingEnabled = true;
  gameData.paused = false;
"""

async def main():
    async with async_playwright() as p:
        b = await _pk.launch(p)
        pg = await b.new_page(); errs=[]
        pg.on("pageerror", lambda e: errs.append(str(e)))
        await pg.goto(_pk.URL)

        await fresh(pg)
        st = await pg.inner_text("#pkStatus")
        ck("hooks al tick instalados", "tick a tick" in st and "exacto" in st, st)

        # ---------- precisión en niveles ----------
        async def level_case(precise):
            await fresh(pg, precise=precise, extra="gameData.currentSkill=gameData.taskData['Concentration']; gameData.paused=false")
            await pg.select_option("#pkType","skill"); await pg.select_option("#pkTarget","Concentration")
            await pg.select_option("#pkField","level"); await pg.fill("#pkValue","20"); await pg.click("#pkAdd")
            await pg.evaluate(FAST_XP)
            await pg.wait_for_function("gameData.paused === true", timeout=15000)
            return await pg.evaluate("""({lvl:gameData.taskData['Concentration'].level,
                                          xp:gameData.taskData['Concentration'].xp,
                                          maxXp:gameData.taskData['Concentration'].getMaxXp()})""")
        ex = await level_case(True)
        lo = await level_case(False)
        ck("preciso: nivel exacto", ex['lvl']==20, f"nivel={ex['lvl']}")
        ck("preciso: sin xp de sobra", ex['xp']/ex['maxXp'] < 0.001, f"xp={ex['xp']:.3f}/{ex['maxXp']}")
        ck("sin tick parcial se pasa de largo", lo['lvl']>20, f"nivel={lo['lvl']} (objetivo 20)")

        # ---------- precisión en monedas ----------
        async def coin_case(precise):
            await fresh(pg, precise=precise, extra="gameData.currentJob=gameData.taskData['Beggar']; gameData.coins=0; gameData.paused=false")
            await pg.select_option("#pkType","coins"); await pg.fill("#pkValue","1M"); await pg.click("#pkAdd")
            await pg.evaluate("gameData.taskData['Beggar'].incomeMultipliers.push(() => 100000)")
            await pg.wait_for_function("gameData.paused === true", timeout=15000)
            return await pg.evaluate("gameData.coins")
        ce, cl = await coin_case(True), await coin_case(False)
        ck("preciso: monedas justo en el umbral", 1e6 <= ce < 1e6+1, f"{ce:.4f}")
        ck("sin tick parcial las monedas se pasan", cl > ce, f"preciso={ce:.4f} vs suelto={cl:.4f}")

        # ---------- precisión en edad ----------
        async def age_case(precise):
            await fresh(pg, precise=precise, extra="gameData.paused=false")
            await pg.select_option("#pkType","age"); await pg.fill("#pkValue","20"); await pg.click("#pkAdd")
            await pg.evaluate(FAST_CLOCK)
            await pg.wait_for_function("gameData.paused === true", timeout=15000)
            return await pg.evaluate("gameData.days")
        ae, al = await age_case(True), await age_case(False)
        ck("preciso: edad justo al cumplir años", 7300 <= ae < 7301, f"días={ae:.3f} (20 años = 7300)")
        ck("sin tick parcial la edad se pasa", al > 7301, f"días={al:.0f}")

        # ---------- tipo nuevo: net/día por cantidad ----------
        await fresh(pg, extra="gameData.currentJob = gameData.taskData['Beggar']; gameData.paused=false")
        await pg.select_option("#pkType","netval")
        hint = await pg.inner_text("#pkHint")
        ck("netval muestra el net actual", "Ahora estás en" in hint, hint[-28:])
        await pg.fill("#pkValue","2k"); await pg.click("#pkAdd")
        ck("netval queda pendiente", (await pg.evaluate("gameData.paused"))==False)
        await pg.evaluate("gameData.taskData['Beggar'].incomeMultipliers.push(() => 100000)")
        await pg.wait_for_function("gameData.paused === true", timeout=8000)
        netf = await pg.evaluate("getIncome() - getExpense()")
        ban = await pg.inner_text("#pkBanner")
        ck("netval pausa al alcanzar la cantidad", netf >= 2000 and "Net/día ≥ 2" in ban, f"net={netf:.0f}")

        # netval negativo (quedarse en rojo)
        await fresh(pg, extra="gameData.paused=false")
        await pg.select_option("#pkType","netval"); await pg.fill("#pkValue","-5"); await pg.click("#pkAdd")
        v = await pg.evaluate("JSON.parse(localStorage.getItem('pkHitos_v1')).milestones[0]")
        ck("netval acepta valores negativos", v['value']==-5, str(v['value']))

        # ---------- ETA ----------
        await fresh(pg, extra="gameData.currentSkill = gameData.taskData['Concentration']; gameData.paused=false")
        await pg.select_option("#pkType","skill"); await pg.select_option("#pkTarget","Concentration")
        await pg.fill("#pkValue","300"); await pg.click("#pkAdd")
        await pg.wait_for_timeout(800)
        txt = await pg.inner_text("#pkList")
        ck("el panel muestra ETA", "~" in txt, txt.replace("\n"," ")[:64])

        # ---------- el juego no se arrastra ----------
        await fresh(pg, extra="gameData.paused=false")
        await pg.evaluate("window.__d0=gameData.days"); await pg.wait_for_timeout(1000)
        libre = await pg.evaluate("gameData.days-window.__d0")
        await pg.select_option("#pkType","skill"); await pg.select_option("#pkTarget","Concentration")
        await pg.fill("#pkValue","999999"); await pg.click("#pkAdd")
        await pg.evaluate("window.__d1=gameData.days"); await pg.wait_for_timeout(1000)
        conhito = await pg.evaluate("gameData.days-window.__d1")
        ck("velocidad normal con un hito lejano", conhito > libre*0.9, f"{libre:.1f} vs {conhito:.1f} días/s")

        # ---------- velocidad tras reanudar ----------
        await fresh(pg, extra="gameData.currentJob=gameData.taskData['Beggar']; gameData.coins=0; gameData.paused=false")
        await pg.select_option("#pkType","coins"); await pg.fill("#pkValue","1M"); await pg.click("#pkAdd")
        await pg.evaluate("gameData.taskData['Beggar'].incomeMultipliers.push(() => 100000)")
        await pg.wait_for_function("gameData.paused === true", timeout=10000)
        await pg.evaluate("gameData.paused=false; window.__d2=gameData.days"); await pg.wait_for_timeout(1000)
        post = await pg.evaluate("gameData.days-window.__d2")
        ck("velocidad normal tras reanudar", post > libre*0.9, f"{post:.1f} días/s")

        # ---------- regresiones ----------
        await fresh(pg, extra="gameData.paused=false")
        await pg.evaluate("document.querySelector('#pkAnyUnlock').checked=true; document.querySelector('#pkAnyUnlock').dispatchEvent(new Event('change'))")
        await pg.evaluate("const k=Object.keys(gameData.requirements).find(x=>!gameData.requirements[x].completed); gameData.requirements[k].completed=true")
        await pg.wait_for_function("gameData.paused === true", timeout=6000)
        ck("desbloqueos siguen pausando", True)

        await fresh(pg, extra="gameData.paused=false")
        await pg.select_option("#pkType","net"); await pg.select_option("#pkTarget","Tent")
        await pg.fill("#pkValue",""); await pg.click("#pkAdd")
        await pg.evaluate("gameData.taskData[gameData.currentJob.name].level=5000")
        await pg.wait_for_function("gameData.paused === true", timeout=6000)
        ck("net vs producto del shop sigue pausando", True)

        await fresh(pg, extra="gameData.paused=false")
        await pg.select_option("#pkType","job")
        jobs = await pg.evaluate("[...document.querySelectorAll('#pkTarget option')].map(o=>o.value)")
        ck("jobs y skills siguen separados", "Knight" in jobs and "Concentration" not in jobs)

        await b.close()
    print("\n=== RESULTADOS ===")
    ok=True
    for n,r,info in R:
        print(("PASS " if r else "FAIL ")+n+(f"   [{info}]" if info else "")); ok = ok and r
    real=[e for e in errs if "favicon" not in e.lower()]
    print("errores JS:", real or "ninguno"); print("TOTAL:", "OK" if ok and not real else "REVISAR")
asyncio.run(main())
srv.terminate()
