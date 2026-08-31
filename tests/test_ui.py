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

async def add(pg, t, target, field, val):
    await pg.select_option("#pkType", t)
    if target: await pg.select_option("#pkTarget", target)
    if field: await pg.select_option("#pkField", field)
    if val is not None: await pg.fill("#pkValue", val)
    await pg.click("#pkAdd")

async def main():
    async with async_playwright() as p:
        b = await _pk.launch(p)
        pg = await b.new_page(viewport={"width":1100,"height":950}); errs=[]
        pg.on("pageerror", lambda e: errs.append(str(e)))
        await pg.goto(_pk.URL)

        # el juego corriendo => el panel se está repintando mientras clickeamos
        await fresh(pg, "gameData.currentSkill=gameData.taskData['Concentration']; gameData.paused=false")
        await add(pg,"coins",None,None,"1M")
        await add(pg,"age",None,None,"60")
        await add(pg,"evil",None,None,"50")
        n0 = await pg.evaluate("document.querySelectorAll('#pkHitos li').length")

        # 1) un click normal
        await pg.click("#pkHitos li:nth-child(2) button[title='Eliminar']")
        await pg.wait_for_timeout(300)
        n1 = await pg.evaluate("document.querySelectorAll('#pkHitos li').length")
        ck("un solo click elimina", n0==3 and n1==2, f"{n0} -> {n1}")

        # 2) click lento: mousedown, 400ms de repintados, mouseup
        box = await pg.locator("#pkHitos li:nth-child(1) button[title='Eliminar']").bounding_box()
        await pg.mouse.move(box['x']+box['width']/2, box['y']+box['height']/2)
        await pg.mouse.down()
        await pg.wait_for_timeout(400)
        await pg.mouse.up()
        await pg.wait_for_timeout(200)
        n2 = await pg.evaluate("document.querySelectorAll('#pkHitos li').length")
        ck("click lento (400ms entre down y up) también elimina", n2==1, f"{n1} -> {n2}")

        # 3) las filas no se recrean entre repintados
        await fresh(pg, "gameData.paused=false")
        await add(pg,"coins",None,None,"1M")
        await pg.evaluate("window.__li = document.querySelector('#pkHitos li'); window.__t0 = document.querySelector('#pkHitos li .prog').textContent")
        await pg.wait_for_timeout(1200)
        same = await pg.evaluate("window.__li === document.querySelector('#pkHitos li')")
        moved = await pg.evaluate("window.__t0 !== document.querySelector('#pkHitos li .prog').textContent")
        ck("la fila es el mismo nodo tras 1,2s de repintados", same)
        ck("pero el progreso/ETA se sigue actualizando", moved,
           await pg.evaluate("document.querySelector('#pkHitos li .prog').textContent.trim()"))

        # 4) alta y baja siguen reconstruyendo bien
        await add(pg,"age",None,None,"60")
        n3 = await pg.evaluate("document.querySelectorAll('#pkHitos li').length")
        await pg.click("#pkHitos li:nth-child(1) button[title='Eliminar']")
        await pg.wait_for_timeout(250)
        n4 = await pg.evaluate("document.querySelectorAll('#pkHitos li').length")
        txt = await pg.inner_text("#pkList")
        ck("alta y baja actualizan la lista", n3==2 and n4==1 and "Edad" in txt, f"{n3} -> {n4}")

        # 5) re-armar de un click
        await fresh(pg, "gameData.paused=false")
        await add(pg,"coins",None,None,"1M")
        await pg.evaluate("gameData.coins = 2e6")
        await pg.wait_for_function("gameData.paused === true", timeout=6000)
        await pg.wait_for_timeout(400)   # el panel repinta como mucho cada 200ms
        # se baja el valor primero: re-armar un hito que sigue cumplido vuelve a dispararlo
        await pg.evaluate("gameData.coins = 0; gameData.paused = false")
        await pg.click("#pkHitos li:nth-child(1) button[title='Re-armar']")
        await pg.wait_for_timeout(250)
        done = await pg.evaluate("JSON.parse(localStorage.getItem('pkHitos_v1')).milestones[0].done")
        has_rearm = await pg.evaluate("!!document.querySelector('#pkHitos li button[title=\\'Re-armar\\']')")
        ck("re-armar funciona de un click", done==False and has_rearm==False)

        # 6) el scroll de la lista no se reinicia
        await fresh(pg, "gameData.paused=false")
        for i in range(9): await add(pg,"coins",None,None,str(1000*(i+1)*1000))
        await pg.evaluate("document.querySelector('#pkList').scrollTop = 60")
        await pg.wait_for_timeout(900)
        sc = await pg.evaluate("document.querySelector('#pkList').scrollTop")
        ck("el scroll de la lista se mantiene", sc > 0, f"scrollTop={sc}")

        # 7) regresión: sigue pausando y el hito cumplido se tacha
        await fresh(pg, "gameData.paused=false")
        await add(pg,"coins",None,None,"1M")
        await pg.evaluate("gameData.coins = 2e6")
        await pg.wait_for_function("gameData.paused === true", timeout=6000)
        await pg.wait_for_timeout(400)
        cls = await pg.evaluate("document.querySelector('#pkHitos li').className")
        ck("el hito cumplido se marca y el juego pausa", "done" in cls, cls)

        await b.close()
    print("\n=== RESULTADOS ===")
    ok=True
    for n,r,info in R:
        print(("PASS " if r else "FAIL ")+n+(f"   [{info}]" if info else "")); ok=ok and r
    real=[e for e in errs if "favicon" not in e.lower()]
    print("errores JS:", real or "ninguno"); print("TOTAL:", "OK" if ok and not real else "REVISAR")
asyncio.run(main())
srv.terminate()
