# Registro de cambios

Todo el desarrollo ocurrió en una sola sesión de trabajo, así que las versiones van sin
fecha. El salto de la 1.6 a la 3.2 es real: esa numeración vino de una tanda de cambios
hecha aparte con Gemini (ver [docs/desarrollo.md](docs/desarrollo.md)).

## 3.8

- El ETA de un hito de nivel se integra nivel por nivel en vez de proyectar la xp/día actual
  sobre todo el tramo. Importa para las tareas que se potencian a sí mismas: cada Skill lleva
  el efecto de Concentration —Concentration incluida—, todas llevan `getHappiness`, que
  depende de Meditation, y Dark influence y Demon training dan "All xp". Medido sobre
  Concentration de nivel 100 a 300: la predicción pasó de errar 67% a errar 1%.
- El ETA de un objetivo inalcanzable se muestra como `>999d` en vez de en notación
  exponencial.

## 3.7

- El umbral de un producto del Shop descuenta los **boosts puntuales activos** que darías de
  baja al comprarlo: Dumbbells, Steel longsword y Sapphire charm. Con una Tent y unas
  Dumbbells puestas, "Wooden hut" pide 35 en vez de 100. Los boosts que sirven siempre (Book,
  Study desk, Library, Personal squire, Butler) se conservan y no se descuentan.
- La fila del hito muestra la cuenta armada: `(100 −15 de Tent −50 de Dumbbells)`.
- El log de arranque deja de repetir el número de versión, que había quedado en v3.3 mientras
  el `@version` iba por 3.6.

## 3.6

- La selección automática de Skill mira **solo los requisitos que el juego muestra en
  pantalla**. `updateRequiredRows()` pinta una sola fila por categoría —la del primer
  elemento todavía no completado—, así que un requisito más chico pedido por algo que aún
  no aparece ("Merchant pide Bargaining 50" antes de desbloquear Farmer) deja de contar.
- Las categorías con candado propio (The Arcane Association, Dark magic) no aportan
  requisitos hasta que se abren.
- Nueva suite `tests/test_skill_visible.py`, que además verifica que el criterio coincida
  categoría por categoría con lo que el DOM está mostrando.

## 3.5

- La selección automática de Skill deja de descartar las skills bloqueadas. Medido sobre
  4000 estados de juego aleatorios, ese filtro nunca cambiaba el resultado: toda skill
  bloqueada está trabada por otra cuyo propio requisito pendiente es más chico y gana igual.

## 3.4 — descartada

Versión generada aparte que agregó `if (!isUnlocked(key)) continue;` en `suggestedLevel`.
La condición contradice a la de más abajo (`!r.completed`), así que `best` quedaba en `null`
siempre: se rompió el nivel sugerido del formulario para jobs y skills. No se publicó.

## 3.3

- Vuelve el ETA de los hitos de Net/día, ahora con media móvil lenta (alpha 0,05 y un mínimo
  de 20 muestras). El salto medio entre lecturas bajó de 199% a 35%.
- El ETA de una tarea que no estás haciendo se marca como *"si la activás"*, porque es una
  proyección con su xp/día actual y no una cuenta regresiva.
- El siguiente producto del Shop que se propone es el más barato que **todavía no** te
  bancás, en vez del de costo más parecido al recién cumplido, que solía nacer ya cumplido.

## 3.2

Tanda hecha con Gemini, incorporada con correcciones:

- Al cumplirse un hito de skill, job o producto, el formulario queda precargado con el
  siguiente objetivo.
- Los hitos de tareas inactivas muestran ETA proyectado en vez de ninguno.
- El escalado del tick parcial se limita explícitamente a las tareas activas.
- Un solo `AudioContext` reutilizado en vez de uno por aviso.

## 1.6

- Vuelve a pausar ante **todo** desbloqueo, incluidos los que se recuperan al renacer.
- El filtro por vidas anteriores queda como sub-opción apagada.

## 1.5

- Los desbloqueos que reaparecen tras un rebirth dejan de contar como nuevos: `rebirthReset()`
  re-bloquea todo salvo `permanentUnlocks`. Se agrega un registro de lo desbloqueado alguna
  vez, guardado aparte del save del juego.

## 1.4

- La ✕ y el ↺ responden al primer click. El panel reconstruía la lista entera ~9 veces por
  segundo y el `<li>` desaparecía entre el `mousedown` y el `mouseup`; ahora las filas se
  crean una sola vez y solo se les cambia el texto.

## 1.3

- El umbral de una Property es la diferencia contra la que ya tenés puesta, no su precio de
  lista: comprarla reemplaza la anterior y el net/día ya viene con ese gasto descontado.
- Los hitos de Job precargan el nivel que pide el siguiente job (10), leído de
  `gameData.requirements` en vez de estar escrito a mano.

## 1.2

- **Pausado exacto**: enganche al tick real (`increaseDays` y `updateUI`) y escalado del
  último tick a través de `applySpeed` para aterrizar justo en el umbral.
- Nuevo tipo de hito Net/día ≥ cantidad.
- ETA por hito en el panel.

## 1.1

- Jobs y Skills pasan a ser tipos de hito separados, agrupados por las categorías del juego.
- Nuevo tipo de hito Net/día ≥ producto del Shop.

## 1.0

- Panel de hitos sobre la página del juego, con hitos de nivel, monedas, edad, evil y
  desbloqueos. Chequeo por polling cada 250 ms.
