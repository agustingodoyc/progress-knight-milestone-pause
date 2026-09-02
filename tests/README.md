# Pruebas

Pruebas end-to-end con Playwright. Cada suite levanta una copia local del juego en un
servidor estático, inyecta el userscript con `page.evaluate()` —que corre en el mismo
contexto que `gameData`, igual que `@grant none`— y maneja el estado del juego desde afuera
para forzar cada situación.

## Correr

```bash
pip install playwright
playwright install chromium

cd tests
python3 test_precision.py                    # una suite
for f in test_*.py; do python3 "$f"; done    # todas
```

La primera corrida clona el juego en `../.game`. Cada suite imprime una línea `PASS`/`FAIL`
por caso y un `TOTAL`.

## Variables de entorno

| Variable | Para qué |
|---|---|
| `PK_GAME` | usar una copia del juego ya clonada en vez de `.game` |
| `PK_CHROMIUM` | usar un Chromium del sistema en vez del de Playwright |
| `PK_PORT` | puerto del servidor estático (por defecto 8899) |

## Las suites

| Archivo | Cubre |
|---|---|
| `test_basico.py` | alta de hitos, pausa, persistencia, que el juego siga corriendo |
| `test_tipos.py` | jobs y skills separados, agrupación por categoría, net vs producto |
| `test_precision.py` | tick parcial: nivel, monedas y edad exactos, contra el mismo escenario sin él |
| `test_shop_niveles.py` | costo incremental de las Properties, nivel sugerido por requisitos |
| `test_ui.py` | que un click alcance para borrar mientras el panel se repinta |
| `test_desbloqueos.py` | desbloqueos a través del rebirth y la sub-opción de filtrado |
| `test_skill_visible.py` | que la selección automática de Skill mire solo requisitos visibles en pantalla |

## Escribir una prueba nueva

El patrón de todas: acelerar el juego **después** de crear el hito. Si se acelera antes, el
umbral ya está superado cuando el hito se agrega y entra marcado como cumplido, y la prueba
espera para siempre una pausa que no va a llegar.

```python
await add(pg, "coins", None, None, "1M")      # primero el hito
await pg.evaluate("gameData.taskData['Beggar'].incomeMultipliers.push(() => 100000)")
await pg.wait_for_function("gameData.paused === true", timeout=10000)
```

Después de que el juego pausa, esperá ~400 ms antes de leer el DOM: el panel repinta como
mucho cada 200 ms.
