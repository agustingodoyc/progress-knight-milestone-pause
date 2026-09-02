"""La selección automática de Skill mira solo los requisitos visibles en pantalla."""
import asyncio

from playwright.async_api import async_playwright

import _pk

SCRIPT = _pk.SCRIPT
srv = _pk.serve()
R = []
def ck(n, c, info=""): R.append((n, bool(c), info))

# Recalcula los desbloqueos desde cero para los niveles actuales, como haría el
# juego al arrancar con ese save.
RECOMPUTE = """
  for (const k in gameData.requirements)
    if (!permanentUnlocks.includes(k)) gameData.requirements[k].completed = false;
  for (const k in gameData.requirements) gameData.requirements[k].isCompleted();
  hideEntities(); updateRequiredRows(gameData.taskData, jobCategories);
  updateRequiredRows(gameData.taskData, skillCategories);
"""

# Qué filas de requisito muestra realmente el juego, leído del DOM. Una fila puede
# no tener 'hiddenTask' y aun así no verse, porque hideEntities() le pone 'hidden'
# al bloque entero de la categoría (The Arcane Association, Dark magic).
DOM_VISIBLES = """
(() => {
  const tapado = el => { for (let n = el; n; n = n.parentElement)
                           if (n.classList && n.classList.contains('hidden')) return true;
                         return false; };
  const out = [];
  for (const group of [jobCategories, skillCategories, itemCategories])
    for (const cat in group) {
      const row = document.getElementById(cat);
      if (row && !row.classList.contains('hiddenTask') && !tapado(row)) out.push(cat);
    }
  return out;
})()
"""

async def fresh(pg, extra=""):
    await pg.evaluate("localStorage.clear()")
    await pg.reload()
    await pg.wait_for_function("window.gameData && Object.keys(gameData.taskData).length>0")
    await pg.evaluate(SCRIPT)
    await pg.wait_for_selector("#pkHitos")
    if extra:
        await pg.evaluate(extra)
    await pg.evaluate("gameData.paused = true")

async def auto_target(pg, skill="Concentration"):
    """Cumple un hito de skill y devuelve lo que el script dejó precargado.

    El acelerador se aplica DESPUÉS de crear el hito: si no, el umbral ya está
    superado al agregarlo, entra marcado como cumplido y nunca dispara el
    auto-posicionamiento.
    """
    lvl = await pg.evaluate(f"gameData.taskData['{skill}'].level")
    await pg.evaluate(f"gameData.currentSkill = gameData.taskData['{skill}']; gameData.paused = false")
    await pg.select_option("#pkType", "skill")
    await pg.select_option("#pkTarget", skill)
    await pg.select_option("#pkField", "level")
    await pg.fill("#pkValue", str(lvl + 1))
    await pg.click("#pkAdd")
    await pg.evaluate(f"gameData.taskData['{skill}'].xpMultipliers.push(() => 5000)")
    await pg.wait_for_function("gameData.paused === true", timeout=10000)
    await pg.wait_for_timeout(400)
    return await pg.evaluate("({type: pkType.value, target: pkTarget.value, val: pkValue.value, hint: pkHint.innerText})")


VISIBLES = """(() => {
    const out = [];
    for (const group of [jobCategories, skillCategories, itemCategories])
      for (const cat in group) {
        const cr = gameData.requirements[cat];
        if (cr && !cr.completed) continue;
        for (const n of group[cat]) { const r = gameData.requirements[n];
          if (r && !r.completed) { out.push(n); break; } }
      }
    return out; })()"""

async def main():
    async with async_playwright() as p:
        b = await _pk.launch(p)
        pg = await b.new_page(); errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        await pg.goto(_pk.URL)

        # --- lo que el script considera visible coincide con el DOM ---------
        await fresh(pg)
        dom = await pg.evaluate(DOM_VISIBLES)
        ck("las categorías con candado propio no muestran requisitos",
           "Common work" in dom and "Fundamentals" in dom
           and "The Arcane Association" not in dom and "Dark magic" not in dom,
           ", ".join(dom))
        # el criterio del script tiene que dar exactamente las mismas categorías
        cats_script = await pg.evaluate("""(() => {
            const out = [];
            for (const group of [jobCategories, skillCategories, itemCategories])
              for (const cat in group) {
                const cr = gameData.requirements[cat];
                if (cr && !cr.completed) continue;
                for (const n of group[cat]) { const r = gameData.requirements[n];
                  if (r && !r.completed) { out.push(cat); break; } }
              }
            return out; })()""")
        ck("el criterio del script coincide con lo que se ve en pantalla",
           sorted(cats_script) == sorted(dom),
           f"script={sorted(cats_script)} dom={sorted(dom)}")

        # --- caso donde el filtro cambia la elección ------------------------
        # Bargaining 50 lo pide Merchant, que está al final de Common work y no se
        # ve. Mana control 400 lo pide Apprentice mage, que sí está en pantalla.
        ESTADO = """
          gameData.taskData['Concentration'].level = 200;
          gameData.taskData['Meditation'].level = 200;
          gameData.taskData['Productivity'].level = 20;
          gameData.taskData['Strength'].level = 300;
          gameData.taskData['Battle tactics'].level = 40;
          gameData.taskData['Bargaining'].level = 0;
          gameData.taskData['Mana control'].level = 0;
        """ + RECOMPUTE
        await fresh(pg, ESTADO)
        dom = await pg.evaluate(DOM_VISIBLES)
        ck("con ese estado, Common work sigue mostrando su fila (Farmer)", "Common work" in dom, ", ".join(dom))
        vis = await pg.evaluate(VISIBLES)
        ck("Merchant no está entre los requisitos visibles", "Merchant" not in vis, ", ".join(vis))
        ck("Apprentice mage sí lo está", "Apprentice mage" in vis)

        f = await auto_target(pg)
        ck("elige la skill que pide algo visible, no la del Z más chico global",
           f['target'] == 'Mana control' and f['val'] == '400',
           f"{f['target']} nivel {f['val']} — {f['hint'][:52]}")
        ck("el hint nombra el elemento visible que lo pide", "Apprentice mage" in f['hint'], f['hint'][:60])

        # --- en una partida nueva la elección sigue siendo la razonable -----
        await fresh(pg)
        f2 = await auto_target(pg)
        ck("partida nueva: elige Concentration nivel 5",
           f2['target'] == 'Concentration' and f2['val'] == '5', f"{f2['target']} {f2['val']}")
        ck("y lo justifica con Productivity, que se ve en Fundamentals",
           "Productivity" in f2['hint'], f2['hint'][:60])

        # --- la propiedad general, sobre varios estados ---------------------
        ESTADOS = [
            ("temprano", "gameData.taskData['Concentration'].level = 6;"),
            ("medio",    "gameData.taskData['Concentration'].level = 30;"
                         "gameData.taskData['Strength'].level = 20;"),
            ("avanzado", "gameData.taskData['Concentration'].level = 199;"
                         "gameData.taskData['Productivity'].level = 20;"
                         "gameData.taskData['Strength'].level = 300;"
                         "gameData.taskData['Battle tactics'].level = 150;"),
        ]
        for nombre, estado in ESTADOS:
            await fresh(pg, estado + RECOMPUTE)
            visibles = await pg.evaluate(VISIBLES)
            f = await auto_target(pg)
            quien = f['hint'].split(' pide ')[0] if ' pide ' in f['hint'] else None
            ck(f"[{nombre}] el nivel elegido lo pide algo que está en pantalla",
               quien is not None and quien in visibles,
               f"{quien} → {f['target']} nivel {f['val']}")

        await b.close()
    _pk.report(R, errs)

asyncio.run(main())
srv.terminate()
