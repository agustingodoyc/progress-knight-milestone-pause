# Cómo se construyó

Notas del desarrollo: por qué el script quedó como quedó, qué se midió para decidirlo y con
qué me choqué en el camino. Está acá porque varias de esas cosas no se deducen leyendo el
código, y porque los dos o tres errores que costaron más tiempo fueron todos de diagnóstico,
no de programación.

## Método

El juego es [Progress Knight](https://github.com/ihtasham42/progress-knight) de ihtasham42,
publicado bajo Unlicense. Nunca se lo modifica: el script lee `gameData` y escribe
`gameData.paused`, que es lo mismo que hace el botón Pause.

Cada cambio se verificó end-to-end con Playwright sobre una copia local del juego: se levanta
un servidor estático, se inyecta el userscript con `page.evaluate()` —que corre en el mismo
contexto que `gameData`, igual que `@grant none`— y se manipula el estado del juego desde
afuera para forzar cada situación. Las suites fueron creciendo con el proyecto hasta las 93
pruebas de [`tests/`](../tests).

Ese enfoque se pagó solo: las tres cosas de abajo salieron de correr las pruebas, no de leer
el código.

## Tres diagnósticos que costaron

### Un freno que no existía

Al probar la primera versión del tick parcial, el juego parecía arrastrarse: los días avanzaban
veinte veces más lento de lo que yo esperaba. Estuve un rato buscando un bug en el escalado.

No había ninguno: `getGameSpeed()` devuelve días por **segundo**, y yo lo estaba leyendo como
días por tick. A 20 ticks por segundo, el factor 20 era exactamente eso. En el mismo rato
descubrí que el Time warping tampoco es lineal —es `1 + log₁₃(nivel+1)`—, así que el escenario
de prueba que había armado, con nivel un millón, nunca llegaba ni a x6,4 y por eso el hito
tardaba veintidós segundos en cumplirse en lugar de uno.

**La lección quedó en el código**: los escenarios de prueba aceleran el juego empujando
multiplicadores a `xpMultipliers` / `incomeMultipliers`, que sí son lineales, en vez de tocar
el time warping.

### Un filtro que no filtraba nada

En una tanda de cambios hecha con Gemini
([conversación](https://share.gemini.google/1NePbyIn1umL)) se agregó, dentro de
`suggestedLevel`, una línea para considerar solo los requisitos ya desbloqueados:

```js
if (!isUnlocked(key)) continue;        // exige requirements[key].completed === true
...
if (reqLvl > lvl && !r.completed)      // ...y acá exige que sea false
```

`isUnlocked(key)` es literalmente `r.completed`, así que las dos condiciones no pueden
cumplirse a la vez y `best` quedaba en `null` **siempre**. Como esa función también alimenta
el autocompletado del formulario, el síntoma visible fue otro: al elegir una Skill el campo de
nivel quedaba vacío y el hint sin explicación. Contado sobre la partida: cero requisitos
sobreviven a ese filtro, y en 4000 de 4000 estados aleatorios el resultado cambiaba.

### Un filtro que sí filtraba, pero daba igual

Después vino la pregunta de si la selección automática de skill debía descartar las skills
todavía bloqueadas. En vez de discutirlo, lo medí: sobre 4000 estados de juego al azar
—niveles aleatorios en todas las tareas, evil y monedas variables, recalculando los
desbloqueos desde cero— el filtro **nunca** cambió el resultado.

Tiene una explicación bonita: el grafo de requisitos del juego es una cadena. Toda skill
bloqueada está trabada por otra skill que a su vez tiene un requisito pendiente más chico, así
que esa otra gana igual. Meditation se desbloquea justo cuando Productivity llega a 20, que es
exactamente el nivel en que Productivity deja de ser candidata.

El criterio que sí cambia las cosas es otro, y es el que quedó: mirar solo los requisitos
**visibles en pantalla**. Con Concentration en 200 y Bargaining en 0, el número más chico de
toda la tabla es "Merchant pide Bargaining 50" — pero Merchant está último en Common work y no
lo tenés ni a la vista. Lo que el juego te está mostrando en esa situación es "Apprentice mage
pide Mana control 400", y ese es el objetivo útil.

## Decisiones con número

**Pausado exacto.** Mismo escenario con y sin el escalado del último tick:

| Hito | Sin tick parcial | Con tick parcial |
|---|---|---|
| Concentration nivel 20 | nivel 23 | nivel 20, xp 0.000 |
| 1.000.000 monedas | 1.000.002 | 1.000.000,0001 |
| Edad 20 años | 8111 días (22,2 años) | 7300,000 días exactos |

**Suavizado del ETA de net/día.** El net sube a saltos en cada level-up del job, así que la
medición cruda saltaba en cada uno:

| | salto medio entre lecturas | máximo |
|---|---|---|
| muestreo crudo | 199% | 497% |
| media móvil (alpha 0,05) | 35% | 95% |

**Clicks perdidos.** El panel reconstruía la lista entera unas 9 veces por segundo, y un click
solo existe si el `mousedown` y el `mouseup` caen sobre el mismo elemento. Hay una prueba que
reproduce el caso: aprieta el botón, espera 400 ms de repintados y recién ahí suelta.

## Referencias

- Conversación principal de desarrollo: Claude (Cowork), donde se escribieron el script y las
  pruebas, y se hicieron las mediciones de arriba.
- [Conversación en Gemini](https://share.gemini.google/1NePbyIn1umL): la tanda que agregó el
  auto-posicionamiento del formulario y el ETA de tareas inactivas, incorporada en la 3.2 con
  correcciones, y la 3.4 descartada.
- [Progress Knight](https://github.com/ihtasham42/progress-knight): el juego.
