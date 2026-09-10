# Cómo funciona por dentro

Notas sobre el motor de Progress Knight y sobre las decisiones del script. Sirven tanto para
retocarlo como para escribir cualquier otro userscript sobre este juego.

## Dónde se engancha

El juego guarda todo su estado en una única global, `gameData`, y calcula su velocidad así:

```js
var gameSpeed = baseGameSpeed * +!gameData.paused * +isAlive() * timeWarpingSpeed
```

Escribir `gameData.paused = true` congela el juego exactamente igual que el botón Pause. El
script no modifica ni un byte del juego: lee `gameData` y escribe esa bandera.

Para enterarse de lo que pasa hay dos vías:

1. **Enganche al tick.** `update()` llama *por nombre* a `increaseDays()` al principio y a
   `updateUI()` al final. Las *function declarations* de nivel superior sí quedan como
   propiedades de `window`, así que reemplazarlas da un hook pre-tick y otro post-tick sin
   tocar el código original.
2. **Polling de respaldo**, cada 250 ms, por si algún día ese enganche falla. El panel indica
   abajo a la derecha en qué modo está corriendo.

## Pausado exacto

Un tick puede valer varios niveles cuando el time warping está alto. Chequear después del
hecho te deja pasado de largo.

Todo lo que avanza en un tick —xp, monedas, gastos, días— pasa por `applySpeed()`.
Envolviéndola con un factor `f ∈ (0,1)` se obtiene literalmente **medio tick**, consistente
entre todas las magnitudes, porque el factor es el mismo para las cuatro. Entonces, antes de
cada tick:

1. Para cada hito pendiente se calcula cuánto falta y cuánto rinde el tick.
   Para niveles, la xp que falta se suma con la misma fórmula del juego,
   `round(maxXp * (nivel+1) * 1.01^nivel)`, sin tener que mutar la tarea.
2. Si el hito cae **dentro** del próximo tick, se escala ese único tick para aterrizar justo
   en el umbral.
3. El factor lleva un épsilon (`f * (1 + 1e-9)`) que garantiza cruzar el umbral en vez de
   quedarse a un float de distancia repitiendo ticks infinitesimales. Y hay una guarda: si se
   escalan más de 20 ticks seguidos, uno entero, para que el juego no quede arrastrándose si
   la estimación no converge.

Medido, mismo escenario con y sin la segunda capa:

| Hito | Sin tick parcial | Con tick parcial |
|---|---|---|
| Concentration nivel 20 | nivel 23 | nivel 20, xp 0.000 |
| 1.000.000 monedas | 1.000.002 | 1.000.000,0001 |
| Edad 20 años | 8111 días (22,2 años) | 7300,000 días exactos |

Lo que **no** crece de forma continua —net/día, evil, desbloqueos, nivel máximo— cruza su
umbral en un instante discreto, normalmente un level-up. Ahí el chequeo por tick ya es exacto
y no hace falta escalar nada.

## ETA

Dos caminos según el tipo de hito:

- **Integrado nivel por nivel** para los hitos de nivel. La xp/día no es constante a lo largo
  del tramo: `addMultipliers()` le mete a toda Skill el efecto de Concentration —Concentration
  incluida—, a toda tarea `getHappiness`, que depende de Meditation, y Dark influence y Demon
  training dan "All xp" y se alcanzan a sí mismas. Proyectar la tasa de ahora hasta el final
  deja el ETA largo de más: de nivel 100 a 300 en Concentration, la cuenta plana erraba 67% y
  la integrada erra 1%.

  Y la otra tarea activa también empuja. Solo las skills dan efectos de xp —los jobs solo dan
  ingreso— y solo hay una skill activa por vez, así que el único acople posible es un hito
  sobre el job actual mientras la skill actual le sube la xp (Productivity, Meditation vía
  felicidad, Battle tactics, Mana control, Dark influence, Demon training). Ahí se avanzan las
  dos a la vez: entre level-ups las dos tasas son constantes, así que se salta de level-up en
  level-up en vez de simular tick por tick, con un tope de saltos por si una sube muchísimo
  más rápido que la otra. Con Beggar a nivel 60 mientras Productivity sube en paralelo,
  congelar la skill erraba 75%; acoplado, 3%.

  En vez de modelar cada caso se evalúa el `getXpGain()` real con los niveles hipotéticos —se
  pisan los `.level`, se pregunta y se restauran en un `finally`—, así entran todas las
  dependencias sin enumerarlas, y una sonda comprueba si la otra tarea influye en algo antes
  de molestarse en acoplar.

  Para una tarea que no estás haciendo no hay acople: el ETA es un "si la activás", y
  activarla significa dejar de hacer la otra.
- **Analítico** para monedas y edad: se conoce la fórmula, así que sale directo de cuánto
  falta sobre cuánto rinde el tick.
- **Simulado por level-ups** para net/día. Que suba a saltos, que al principio parecía el
  problema, es en realidad la solución: entre un level-up y el siguiente el net es constante,
  así que el cruce del umbral SIEMPRE cae en un level-up. Se salta de level-up en level-up
  —del job y de la skill actual— y se comprueba después de cada uno. El umbral se recalcula en
  cada tramo, porque Bargaining e Intimidation abaratan los items mientras suben, y eso acerca
  el objetivo solo. Si con el job actual no se llega, no se muestra ETA en lugar de inventar
  uno. Medido: 6s predichos contra 6,0s reales.
- **Media móvil** como respaldo, para lo que no se puede simular. Se mide la pendiente con
  alpha 0,05 (unos 20 ticks de memoria) y no se muestra nada hasta tener 20 muestras.

El muestreo va **una vez por tick**, no al pintar el panel: si se hiciera al pintar, el "por
tick" sería en realidad "por render" y el ETA saldría escalado por la diferencia de
frecuencias. En pausa no se muestrea, para que el ETA de las otras filas no se desvanezca.

Una tarea que no estás haciendo igual proyecta un ETA con su xp/día actual. Es un "si la
pusieras ahora", así que se muestra como `~2m si la activás`.

## Muerte y saldo en cero

Dos cuentas que se muestran arriba de la lista y que se resuelven con la misma técnica que el
ETA: saltar de level-up en level-up, que es donde cambian las tasas.

`getLifespan()` depende de Immortality y de Super immortality, y la velocidad del juego de
Time warping. Si alguna es tu skill actual, el final se corre mientras la subís, así que la
cuenta de muerte se simula; si no, es una división. La sonda de siempre decide cuál de los dos
caminos tomar.

Para el saldo, el ingreso sube con el nivel del job (`getLevelMultiplier`) y la skill actual
puede empujar la xp del job, el ingreso (Strength en militar, Demon's wealth) o los gastos
(Bargaining e Intimidation abaratan los items), así que se avanzan las dos tareas a la vez
recalculando el net en cada tramo. Si en algún punto el net se vuelve positivo, no vas a
quebrar y se dice eso en lugar de una fecha.

El freno antes de la quiebra usa el mismo tick parcial que los hitos, pero **al revés**: los
hitos escalan el tick con un épsilon por encima para garantizar cruzar el umbral, y este lo
escala un épsilon por debajo para garantizar NO cruzarlo. La diferencia importa porque
`applyExpenses()` llama a `goBankrupt()` en cuanto las monedas quedan negativas, y eso te
devuelve a Homeless y te vacía `currentMisc`.

## La condición de los hitos del Shop

Desde la v4.2 no es "el net alcanza el costo" sino "sobrevivís a la compra". Se simula
comprándolo —la Property reemplaza a la actual, un Misc se suma, y en los dos casos se apagan
los boosts puntuales— y se pregunta lo mismo que el cartel de arriba del panel: si el net
queda en verde, o si queda en rojo pero aguantás. Aguantar es que el ingreso alcance antes de
vaciarte o que la vida se acabe antes: vaciarte después de muerto no es vaciarte.

Simular en vez de calcular importa más de lo que parece. La felicidad depende de la Property
(`getHappiness` la incluye) y multiplica la xp de todas las tareas: comprar una casa mejor
hace que el job suba más rápido y que el ingreso alcance antes. Haciendo la cuenta a mano eso
se pasa por alto; evaluando el `getXpGain()` real bajo la compra, entra solo.

El margen encarece el producto simulado en vez de multiplicar un umbral, que es la forma
natural de pedir colchón: sobrevivir a algo que cuesta el doble.

La simulación anidada (supervivencia dentro de cada tramo del ETA) lleva topes propios más
chicos, porque la condición se cumple mucho antes que el umbral estricto y no hace falta
recorrer miles de level-ups.

## Costo real en el Shop

El umbral es lo que te falta de verdad: el precio del producto menos todo lo que dejarías de
pagar al comprarlo.

`gameData.currentProperty` es una sola, así que comprar otra reemplaza la anterior y su gasto
se descuenta —y el net/día ya viene con él restado—. Los Misc se acumulan (`currentMisc` es un
array), así que ahí no hay reemplazo: van al precio entero, y a cero si ya los tenés.

Además se descuentan los **boosts puntuales activos**, los que potencian una rama concreta y
uno apaga al cambiar de foco. El juego no los marca como tales, pero los describe: en
`itemBaseData`, Dumbbells dice "Strength xp", Steel longsword "Military xp" y Sapphire charm
"Magic xp", mientras que los que sirven siempre dicen "Skill xp", "Job xp" o "Happiness". El
script trata como puntual cualquier descripción fuera de esas tres, así que un item nuevo de
rama específica entra solo.

Con Tent y Dumbbells puestos, "Wooden hut" pide `100 − 15 − 50 = 35`. La cuenta se muestra
armada en la fila del hito.

El umbral se recalcula en cada tick, así que acompaña los descuentos de Bargaining e
Intimidation y cualquier cambio en lo que tengas equipado.

## Desbloqueos y renacer

`rebirthReset()` pone `completed = false` en todas las requirements menos las de
`permanentUnlocks`, así que después de renacer se vuelve a desbloquear toda la vida anterior.
Para que eso funcione bien, el set de referencia se re-basea en cada tick: si solo creciera,
dentro de la misma sesión nada volvería a contar como nuevo tras un rebirth.

El instante del renacer no dispara nada: lo que vuelve a completarse ahí mismo (Beggar,
Concentration, lo que depende del evil) ya estaba en el set del tick anterior, así que no
figura como transición.

Aparte se lleva una lista de lo desbloqueado **alguna vez**, guardada en el localStorage del
script, que sobrevive al renacer y a recargar. Solo se usa con la sub-opción "ignorar los ya
vistos en vidas anteriores".

## Qué propone al cumplir un hito

- **Skills.** La skill con el menor nivel pendiente **entre los requisitos que se ven en
  pantalla**. El juego pinta una sola fila de requisitos por categoría —la del primer
  elemento todavía no completado—, y las categorías con candado propio no muestran ninguna.
  Un requisito más chico pedido por algo que aún no aparece no cuenta. La skill en sí no se
  filtra: puede estar bloqueada mientras algo visible la esté pidiendo. Los empates se
  resuelven por orden visual, de arriba hacia abajo.
- **Jobs.** Entre los jobs desbloqueados en nivel 0, el de menor ingreso base, con el nivel
  que pide el siguiente (10).
- **Shop.** El producto más barato que todavía no te bancás. Buscar el de costo más parecido
  al recién cumplido caía casi siempre en algo que ya podés pagar, y el hito nacía cumplido.

## El panel

Está anclado abajo a la derecha y crece hacia arriba, así que se topa en `calc(100vh - 28px)`
con el cuerpo scrolleando: el encabezado nunca se va de la pantalla y siempre se puede plegar.
Las ayudas largas viven en el `title` en lugar del cuerpo, para que explicar no cueste altura.

## Almacenamiento

Los hitos y la configuración viven en `localStorage`, bajo la clave propia `pkHitos_v1`,
separada del save del juego. El Reset del propio juego hace `localStorage.clear()` y también
se los lleva.

## Rarezas del juego que conviene saber

- `getGameSpeed()` devuelve días por **segundo**, no por tick. Para el tick hay que dividir
  por `updateSpeed`. Confundirlas hace ver frenos que no existen.
- El efecto del Time warping no es lineal sino `1 + log₁₃(nivel+1)`, definido en
  `setCustomEffects()`. Ni con nivel un millón pasás de x6,4. Immortality y Bargaining también
  tienen efectos logarítmicos propios.
- Las tablas de categorías y las constantes (`jobCategories`, `itemCategories`, `updateSpeed`,
  `baseGameSpeed`…) están declaradas con `const`, y un `const` de nivel superior **no** queda
  como propiedad de `window`: vive en el global lexical environment. Se leen con un eval
  indirecto, con respaldo a una lista plana por si alguna CSP lo bloqueara.
- `isAlive()` no es una consulta inocente: escribe en el DOM y clampea `gameData.days`. Para
  saber si el personaje vive conviene comparar `gameData.days < getLifespan()`.
- `getNet()` devuelve el valor **absoluto** de ingreso menos gastos; el signo se muestra
  aparte. Para saber si estás en verde hay que restar a mano.
- Los items no tienen categoría marcada en su `baseData`: las Properties se distinguen porque
  no traen `description` y los Misc sí. Esa misma `description` es lo único que separa un boost
  de rama específica de uno que sirve siempre.
- `goBankrupt()` no es solo un cartel: cuando las monedas llegan a cero con el net en rojo, el
  juego te devuelve a Homeless y te vacía `currentMisc`. Cualquier escenario con gastos
  mayores al ingreso se desarma solo si no hay monedas suficientes para sostenerlo.
