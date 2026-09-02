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

- **Analítico** para niveles, monedas y edad: se conoce la fórmula, así que sale directo de
  cuánto falta sobre cuánto rinde el tick.
- **Media móvil** para net/día: no tiene fórmula cerrada, sube a saltos cuando el job sube de
  nivel. Se mide la pendiente real con alpha 0,05 (unos 20 ticks de memoria) y no se muestra
  nada hasta tener 20 muestras. Sin ese suavizado el número saltaba 199% entre lecturas; con
  él, 35%.

El muestreo va **una vez por tick**, no al pintar el panel: si se hiciera al pintar, el "por
tick" sería en realidad "por render" y el ETA saldría escalado por la diferencia de
frecuencias. En pausa no se muestrea, para que el ETA de las otras filas no se desvanezca.

Una tarea que no estás haciendo igual proyecta un ETA con su xp/día actual. Es un "si la
pusieras ahora", así que se muestra como `~2m si la activás`.

## Costo real en el Shop

`gameData.currentProperty` es una sola: comprar una property reemplaza la anterior, y el
net/día ya viene con el gasto de la actual descontado. Por eso el umbral de una Property es
la **diferencia**, que es lo mismo que pedir que el net *después* de comprarla siga siendo
positivo. Los Misc se acumulan (`currentMisc` es un array), así que van al precio entero, y a
cero si ya los tenés. El umbral se recalcula en cada tick, de modo que acompaña los descuentos
de Bargaining e Intimidation.

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
  no traen `description` y los Misc sí.
