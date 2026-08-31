import asyncio
import json
from playwright.async_api import async_playwright

import _pk
SCRIPT = _pk.SCRIPT
srv = _pk.serve()
R=[]
def ck(n,c): R.append((n,bool(c)))

async def main():
    async with async_playwright() as p:
        b = await _pk.launch(p)
        pg = await b.new_page()
        errs=[]
        pg.on("pageerror", lambda e: errs.append(str(e)))
        await pg.goto(_pk.URL)
        # sembrar una config vieja v1.0 para probar migración
        await pg.evaluate("""localStorage.setItem('pkHitos_v1', JSON.stringify({
            milestones:[{id:'a',type:'task',target:'Knight',field:'level',value:10,done:false},
                        {id:'b',type:'task',target:'Concentration',field:'level',value:10,done:false}]}))""")
        await pg.reload()
        await pg.wait_for_function("window.gameData && Object.keys(gameData.taskData).length>0")
        await pg.evaluate(SCRIPT)
        await pg.wait_for_selector("#pkHitos")

        # migración v1.0 -> v1.1
        cfg = json.loads(await pg.evaluate("localStorage.getItem('pkHitos_v1')"))
        types = {m['target']: m['type'] for m in cfg['milestones']}
        ck("migración: Knight -> job", types.get('Knight')=='job')
        ck("migración: Concentration -> skill", types.get('Concentration')=='skill')
        txt = await pg.inner_text("#pkList")
        ck("listado muestra [Job]/[Skill]", "[Job] Knight" in txt and "[Skill] Concentration" in txt)

        # selects separados
        await pg.select_option("#pkType","job")
        jobs = await pg.evaluate("[...document.querySelectorAll('#pkTarget option')].map(o=>o.value)")
        jgroups = await pg.evaluate("[...document.querySelectorAll('#pkTarget optgroup')].map(o=>o.label)")
        ck("lista Jobs sin skills", "Knight" in jobs and "Concentration" not in jobs)
        ck("Jobs agrupados por categoría", "Military" in jgroups and "The Arcane Association" in jgroups)
        await pg.select_option("#pkType","skill")
        sk = await pg.evaluate("[...document.querySelectorAll('#pkTarget option')].map(o=>o.value)")
        sgroups = await pg.evaluate("[...document.querySelectorAll('#pkTarget optgroup')].map(o=>o.label)")
        ck("lista Skills sin jobs", "Concentration" in sk and "Knight" not in sk)
        ck("Skills agrupadas por categoría", "Magic" in sgroups and "Dark magic" in sgroups)

        # tipo net: lista de items agrupada
        await pg.select_option("#pkType","net")
        items = await pg.evaluate("[...document.querySelectorAll('#pkTarget option')].map(o=>o.value)")
        igroups = await pg.evaluate("[...document.querySelectorAll('#pkTarget optgroup')].map(o=>o.label)")
        ck("lista Shop completa", "Tent" in items and "Grand palace" in items and "Book" in items)
        ck("Shop agrupado Properties/Misc", "Properties" in igroups and "Misc" in igroups)

        # hito net contra Tent (15/día). Al inicio el net es menor -> queda pendiente
        await pg.evaluate("gameData.paused=false")
        await pg.select_option("#pkTarget","Tent")
        await pg.fill("#pkValue","")   # margen por defecto = 1
        await pg.click("#pkAdd")
        await pg.wait_for_timeout(600)
        st = await pg.evaluate("""JSON.parse(localStorage.getItem('pkHitos_v1')).milestones.find(m=>m.type==='net')""")
        ck("hito net creado con margen 1", st and st['value']==1 and st['target']=='Tent')
        ck("hito net no dispara de entrada", (await pg.evaluate("gameData.paused"))==False and st['done']==False)
        prog = await pg.inner_text("#pkList")
        ck("progreso net muestra umbral del item", "Net/día ≥ Tent" in prog)

        # subir ingresos hasta superar el gasto de Tent
        await pg.evaluate("gameData.taskData[gameData.currentJob.name].level = 5000")
        await pg.wait_for_function("gameData.paused === true", timeout=5000)
        ck("pausa cuando net/día alcanza el producto", True)
        ban = await pg.inner_text("#pkBanner")
        ck("banner nombra el producto", "Tent" in ban)

        # umbral dinámico: con margen 3 el mismo net no alcanza
        await pg.evaluate("gameData.paused=false")
        await pg.select_option("#pkType","net"); await pg.select_option("#pkTarget","Grand palace")
        await pg.fill("#pkValue","1"); await pg.click("#pkAdd")
        await pg.wait_for_timeout(700)
        ck("hito caro queda pendiente", (await pg.evaluate("gameData.paused"))==False)

        # hito de job por nivel máximo
        await pg.select_option("#pkType","job"); await pg.select_option("#pkTarget","Farmer")
        await pg.select_option("#pkField","maxLevel"); await pg.fill("#pkValue","40")
        await pg.click("#pkAdd")
        await pg.evaluate("gameData.taskData['Farmer'].maxLevel = 50")
        await pg.wait_for_function("gameData.paused === true", timeout=4000)
        ck("pausa por nivel máximo de job", True)

        # el juego sigue corriendo si no hay nada que disparar
        await pg.evaluate("gameData.paused=false; window.__d0=gameData.days")
        await pg.wait_for_timeout(1000)
        ck("juego avanza normal", await pg.evaluate("gameData.days > window.__d0"))
        await b.close()
    print("\n=== RESULTADOS ===")
    ok=True
    for n,r in R:
        print(("PASS " if r else "FAIL ")+n); ok = ok and r
    print("errores JS:", errs or "ninguno")
    print("TOTAL:", "OK" if ok and not errs else "REVISAR")
asyncio.run(main())
srv.terminate()
