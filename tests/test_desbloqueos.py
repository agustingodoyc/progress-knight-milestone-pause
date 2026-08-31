import asyncio
from playwright.async_api import async_playwright

import _pk
SCRIPT = _pk.SCRIPT
srv = _pk.serve()
R=[]
def ck(n,c,info=""): R.append((n,bool(c),info))

async def check(pg, sel, on=True):
    await pg.evaluate(f"""const e=document.querySelector('{sel}'); e.checked={str(on).lower()};
                          e.dispatchEvent(new Event('change'));""")

async def inject(pg, ignore_seen=False):
    await pg.wait_for_function("window.gameData && Object.keys(gameData.taskData).length>0")
    await pg.evaluate(SCRIPT); await pg.wait_for_selector("#pkHitos")
    await check(pg, "#pkAnyUnlock", True)
    if ignore_seen: await check(pg, "#pkIgnoreSeen", True)
    await pg.evaluate("gameData.paused = false")

async def fresh(pg, ignore_seen=False):
    await pg.evaluate("localStorage.clear()"); await pg.reload(); await inject(pg, ignore_seen)

async def reload_keep(pg, ignore_seen=False):
    await pg.evaluate("saveGameData()"); await pg.reload(); await inject(pg, ignore_seen)

async def main():
    async with async_playwright() as p:
        b = await _pk.launch(p)
        pg = await b.new_page(); errs=[]
        pg.on("pageerror", lambda e: errs.append(str(e)))
        await pg.goto(_pk.URL)

        # 1) desbloqueo nuevo
        await fresh(pg)
        await pg.evaluate("gameData.taskData['Concentration'].level = 10")
        await pg.wait_for_function("gameData.paused === true", timeout=6000)
        ck("un desbloqueo nuevo pausa", "Productivity" in (await pg.inner_text("#pkBanner")))

        # 2) el instante del renacer no debe disparar nada por sí solo
        await pg.evaluate("gameData.paused=false; rebirthOne()")
        await pg.wait_for_timeout(900)
        ck("renacer no dispara por sí solo", (await pg.evaluate("gameData.paused")) == False,
           "re-completan Beggar/Concentration pero ya estaban en el set previo")

        # 3) POR DEFECTO: re-desbloquear tras renacer SÍ pausa
        relocked = await pg.evaluate("gameData.requirements['Productivity'].completed")
        await pg.evaluate("gameData.taskData['Concentration'].level = 10")
        await pg.wait_for_function("gameData.paused === true", timeout=6000)
        ck("re-desbloquear tras renacer pausa", relocked == False,
           (await pg.inner_text("#pkBanner"))[:60])

        # 4) y también después de recargar la página
        await pg.evaluate("gameData.paused=false; rebirthOne()")
        await reload_keep(pg)
        await pg.evaluate("gameData.taskData['Concentration'].level = 10")
        await pg.wait_for_function("gameData.paused === true", timeout=6000)
        ck("re-desbloquear tras renacer + recargar también pausa", True,
           (await pg.inner_text("#pkBanner"))[:60])

        # 5) varios desbloqueos del mismo tick van en un solo aviso
        await pg.evaluate("gameData.paused=false")
        await pg.evaluate("gameData.taskData['Concentration'].level=30; gameData.taskData['Strength'].level=30")
        await pg.wait_for_function("gameData.paused === true", timeout=6000)
        ban = await pg.inner_text("#pkBanner")
        ck("varios desbloqueos juntos = un solo aviso", ban.count("Nuevo desbloqueo") == 1 and "," in ban, ban[:80])

        # 6) con la sub-opción activada vuelve el filtro por vidas anteriores
        await fresh(pg, ignore_seen=True)
        await pg.evaluate("gameData.taskData['Concentration'].level = 10")
        await pg.wait_for_function("gameData.paused === true", timeout=6000)
        await pg.evaluate("gameData.paused=false; rebirthOne()")
        await pg.wait_for_timeout(400)
        await pg.evaluate("gameData.taskData['Concentration'].level = 10")
        await pg.wait_for_timeout(1300)
        ck("ignorar-ya-vistos: el re-desbloqueo no pausa", (await pg.evaluate("gameData.paused")) == False)
        await pg.evaluate("gameData.taskData['Strength'].level = 30; gameData.taskData['Concentration'].level = 30")
        await pg.wait_for_function("gameData.paused === true", timeout=6000)
        ck("ignorar-ya-vistos: lo inédito sí pausa", "Muscle memory" in (await pg.inner_text("#pkBanner")))

        # 7) la sub-opción se persiste y se esconde si el aviso general está apagado
        await reload_keep(pg, ignore_seen=False)
        st = await pg.evaluate("JSON.parse(localStorage.getItem('pkHitos_v1'))")
        vis = await pg.evaluate("!document.querySelector('#pkIgnoreSeen').parentElement.classList.contains('off')")
        ck("la sub-opción se persiste", st['ignoreSeen'] == True and st['anyUnlock'] == True)
        ck("la sub-opción se ve con el aviso encendido", vis == True)
        await check(pg, "#pkAnyUnlock", False)
        vis2 = await pg.evaluate("document.querySelector('#pkIgnoreSeen').parentElement.classList.contains('off')")
        ck("y se esconde con el aviso apagado", vis2 == True)

        # 8) apagado, no pausa
        await fresh(pg)
        await check(pg, "#pkAnyUnlock", False)
        await pg.evaluate("gameData.taskData['Concentration'].level = 10")
        await pg.wait_for_timeout(1200)
        ck("con el aviso apagado no pausa", (await pg.evaluate("gameData.paused")) == False)

        # 9) el hito de desbloqueo puntual sigue igual
        await fresh(pg)
        await check(pg, "#pkAnyUnlock", False)
        await pg.select_option("#pkType","unlock"); await pg.select_option("#pkTarget","Productivity")
        await pg.click("#pkAdd")
        await pg.evaluate("gameData.taskData['Concentration'].level = 10")
        await pg.wait_for_function("gameData.paused === true", timeout=6000)
        ck("el desbloqueo puntual sigue funcionando", "Se desbloquea: Productivity" in (await pg.inner_text("#pkBanner")))

        await b.close()
    print("\n=== RESULTADOS ===")
    ok=True
    for n,r,info in R:
        print(("PASS " if r else "FAIL ")+n+(f"   [{info}]" if info else "")); ok=ok and r
    real=[e for e in errs if "favicon" not in e.lower()]
    print("errores JS:", real or "ninguno"); print("TOTAL:", "OK" if ok and not real else "REVISAR")
asyncio.run(main())
srv.terminate()
