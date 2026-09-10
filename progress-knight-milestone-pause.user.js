// ==UserScript==
// @name         Progress Knight - Pausa automática por hitos
// @namespace    https://github.com/agustingodoyc
// @version      4.2
// @description  Pausa automática por hitos en Progress Knight con tick parcial exacto, ETA preciso y selección automática de Skill por el menor nivel que el juego te esté pidiendo en pantalla.
// @author       Agustín
// @match        https://ihtasham42.github.io/progress-knight/*
// @run-at       document-idle
// @grant        none
// @homepageURL  https://github.com/agustingodoyc/progress-knight-milestone-pause
// @supportURL   https://github.com/agustingodoyc/progress-knight-milestone-pause/issues
// @downloadURL  https://raw.githubusercontent.com/agustingodoyc/progress-knight-milestone-pause/main/progress-knight-milestone-pause.user.js
// @updateURL    https://raw.githubusercontent.com/agustingodoyc/progress-knight-milestone-pause/main/progress-knight-milestone-pause.user.js
// @license      MIT
// ==/UserScript==

(function () {
    'use strict';

    const W = (typeof unsafeWindow !== 'undefined') ? unsafeWindow : window;

    const STORE_KEY = 'pkHitos_v1';
    const FALLBACK_POLL_MS = 250;
    const RENDER_MS = 200;

    let state = {
        collapsed: false,
        sound: true,
        desktopNotif: false,
        anyUnlock: false,
        ignoreSeen: false,
        precise: true,
        pauseBroke: true,           // frenar justo antes de quedarte sin monedas
        everUnlocked: [],
        milestones: []
    };

    let knownUnlocks = null;
    let everSet = new Set();
    let originalTitle = document.title;
    let titleTimer = null;
    let hooksOk = false;
    let tickScale = 1;
    let lastRender = 0;

    // Tasa medida por tick para lo que no tiene fórmula (net/día, evil).
    const rates = {};
    const RATE_ALPHA = 0.05;       // ~20 ticks de memoria: absorbe los saltos de nivel
    const RATE_MIN_SAMPLES = 20;   // 1 segundo de datos antes de mostrar un ETA

    /* ================================================================== */
    /* Persistencia & Migración                                           */
    /* ================================================================== */

    function load() {
        try {
            const raw = localStorage.getItem(STORE_KEY);
            if (raw) Object.assign(state, JSON.parse(raw));
        } catch (e) { console.warn('[Hitos] no se pudo leer la config:', e); }
        migrate();
    }

    function migrate() {
        let touched = false;
        for (let i = 0; i < state.milestones.length; i++) {
            const m = state.milestones[i];
            if (m.type === 'task') {
                m.type = isJobName(m.target) ? 'job' : 'skill';
                touched = true;
            }
        }
        if (touched) save();
    }

    function save() {
        try { localStorage.setItem(STORE_KEY, JSON.stringify(state)); }
        catch (e) { console.warn('[Hitos] no se pudo guardar la config:', e); }
    }

    /* ================================================================== */
    /* Helpers de acceso al motor del juego                               */
    /* ================================================================== */

    function pageGlobal(name) {
        if (typeof W[name] !== 'undefined') return W[name];
        try { return W.eval(name); } catch (e) { return undefined; }
    }

    function gameReady() {
        const g = W.gameData;
        return !!(g && g.taskData && g.itemData && g.requirements &&
                  Object.keys(g.taskData).length > 0 &&
                  Object.keys(g.itemData).length > 0);
    }

    function updateSpeed() { return pageGlobal('updateSpeed') || 20; }

    function gameSpeed(ignorePause) {
        const g = W.gameData;
        try {
            if (!ignorePause || !g.paused) return W.getGameSpeed();
            const base = pageGlobal('baseGameSpeed') || 4;
            const alive = g.days < W.getLifespan() ? 1 : 0;
            const tw = g.timeWarpingEnabled ? g.taskData['Time warping'].getEffect() : 1;
            return base * alive * tw;
        } catch (e) { return 0; }
    }

    function perTick(value, ignorePause) {
        return value * gameSpeed(ignorePause) / updateSpeed();
    }

    function isJobName(name) {
        const jbd = pageGlobal('jobBaseData');
        if (jbd && name in jbd) return true;
        const t = W.gameData?.taskData?.[name];
        return !(!t?.baseData || !('income' in t.baseData));
    }

    function netPerDay() {
        try { return W.getIncome() - W.getExpense(); } catch (e) { return null; }
    }

    function itemExpense(name) {
        const it = W.gameData?.itemData?.[name];
        return typeof it?.getExpense === 'function' ? it.getExpense() : null;
    }

    function isPropertyName(name) {
        const cats = pageGlobal('itemCategories');
        if (cats?.Properties) return cats.Properties.includes(name);
        const it = W.gameData?.itemData?.[name];
        return !(!it?.baseData || ('description' in it.baseData));
    }

    // Los Misc que potencian una rama concreta no se tienen prendidos siempre: al
    // comprar otra cosa los apagás. Los que sirven hagas lo que hagas, no.
    // El juego no marca la diferencia, pero la describe: itemBaseData trae
    // "Strength xp", "Military xp", "Magic xp" para los puntuales, y "Skill xp",
    // "Job xp" o "Happiness" para los que valen siempre. Cualquier descripción
    // nueva se considera puntual, que es el caso más común.
    const BOOSTS_PERMANENTES = ['Skill xp', 'Job xp', 'Happiness'];

    function esMiscPuntual(name) {
        if (isPropertyName(name)) return false;
        const it = W.gameData?.itemData?.[name];
        const d = it?.baseData?.description;
        return !!d && !BOOSTS_PERMANENTES.includes(d);
    }

    // Gasto diario de los boosts puntuales que tenés activos y darías de baja.
    function miscDescartables(excludeName) {
        const activos = W.gameData?.currentMisc || [];
        let total = 0;
        const names = [];
        for (const it of activos) {
            if (!it?.name || it.name === excludeName || !esMiscPuntual(it.name)) continue;
            total += typeof it.getExpense === 'function' ? it.getExpense() : 0;
            names.push(it.name);
        }
        return { total, names };
    }

    function shopCost(name) {
        const g = W.gameData;
        const cost = itemExpense(name);
        if (cost === null) return null;
        const drop = miscDescartables(name);
        if (isPropertyName(name)) {
            const cur = typeof g.currentProperty?.getExpense === 'function' ? g.currentProperty.getExpense() : 0;
            return { delta: cost - cur - drop.total, cost, current: cur,
                     currentName: g.currentProperty?.name ?? null, property: true, dropped: drop };
        }
        const owned = (g.currentMisc || []).some(x => x?.name === name);
        return { delta: owned ? 0 : cost - drop.total, cost, current: 0, currentName: null,
                 property: false, owned, dropped: drop };
    }

    function isUnlocked(name) {
        const req = W.gameData?.requirements?.[name];
        return !req || req.completed;
    }

    function completedUnlocks() {
        const set = new Set();
        const reqs = W.gameData?.requirements || {};
        for (const k in reqs) {
            if (reqs[k]?.completed) set.add(k);
        }
        return set;
    }

    /* ================================================================== */
    /* Formatos & XP                                                      */
    /* ================================================================== */

    const SUFFIXES = { k: 1e3, m: 1e6, b: 1e9, t: 1e12, q: 1e15 };

    function parseNum(str) {
        const s = String(str).trim().replace(/[\s,]/g, '');
        const m = s.match(/^(-?\d*\.?\d+(?:e[+-]?\d+)?)\s*([kmbtq])?$/i);
        if (!m) return NaN;
        return parseFloat(m[1]) * (m[2] ? SUFFIXES[m[2].toLowerCase()] : 1);
    }

    function fmt(n) {
        if (n === null || n === undefined || isNaN(n)) return '?';
        if (typeof W.format === 'function' && Math.abs(n) >= 1000) {
            try { return W.format(n); } catch (e) { }
        }
        return String(Math.round(n * 100) / 100);
    }

    function fmtEta(ticks) {
        if (ticks === null || !isFinite(ticks) || ticks < 0) return null;
        if (ticks <= 0) return 'ya';
        const s = ticks / updateSpeed();
        if (s < 1) return '<1s';
        if (s < 60) return Math.round(s) + 's';
        if (s < 3600) return Math.floor(s / 60) + 'm ' + Math.round(s % 60) + 's';
        if (s < 86400) return Math.floor(s / 3600) + 'h ' + Math.round((s % 3600) / 60) + 'm';
        const dias = s / 86400;
        // Con objetivos absurdos la cuenta se va a 1e38 y salía en notación
        // exponencial; a partir de acá el número exacto no le sirve a nadie.
        return dias > 999 ? '>999d' : Math.round(dias) + 'd';
    }

    function maxXpAt(task, level) {
        return Math.round(task.baseData.maxXp * (level + 1) * Math.pow(1.01, level));
    }

    function xpNeeded(task, targetLevel) {
        if (task.level >= targetLevel) return 0;
        if (targetLevel - task.level > 10000) return null;
        let total = maxXpAt(task, task.level) - task.xp;
        for (let L = task.level + 1; L < targetLevel; L++) {
            total += maxXpAt(task, L);
        }
        return Math.max(total, 0);
    }

    /* ================================================================== */
    /* Hitos & Predicciones                                               */
    /* ================================================================== */

    function currentValue(m) {
        const g = W.gameData;
        switch (m.type) {
            case 'job':
            case 'skill': {
                const t = g.taskData[m.target];
                return t ? (m.field === 'maxLevel' ? t.maxLevel : t.level) : null;
            }
            case 'coins':  return g.coins;
            case 'age':    return typeof W.daysToYears === 'function' ? W.daysToYears(g.days) : Math.floor(g.days / 365);
            case 'evil':   return g.evil;
            case 'net':
            case 'netval': return netPerDay();
            case 'unlock': return g.requirements[m.target]?.completed ? 1 : 0;
            default: return null;
        }
    }

    function threshold(m) {
        if (m.type === 'unlock') return 1;
        if (m.type === 'net') {
            const c = shopCost(m.target);
            return c === null ? null : c.delta * (m.value || 1);
        }
        return m.value;
    }

    function isMet(m) {
        if (m.type === 'net') {
            const c = shopCost(m.target);
            if (c && c.owned) return true;
            const vivo = sobrevivisComprando(m.target, m.value || 1);
            if (vivo !== null) return vivo;
            // si no se pudo simular, la regla vieja: net actual contra el umbral
        }
        const v = currentValue(m), t = threshold(m);
        return v !== null && t !== null && v >= t;
    }

    function forecast(m, ignorePause) {
        const g = W.gameData;
        try {
            switch (m.type) {
                case 'job':
                case 'skill': {
                    if (m.field === 'maxLevel') return null;
                    const t = g.taskData[m.target];
                    if (!t) return null;
                    const need = xpNeeded(t, m.value);
                    if (need === null) return null;
                    const active = (g.currentJob?.name === t.name) || (g.currentSkill?.name === t.name);
                    const xpGain = typeof t.getXpGain === 'function' ? t.getXpGain() : 0;
                    return { remaining: need, rate: perTick(xpGain, ignorePause), active };
                }
                case 'coins': {
                    const net = W.getIncome() - W.getExpense();
                    return { remaining: m.value - g.coins, rate: perTick(net, ignorePause), active: true };
                }
                case 'age':
                    return { remaining: m.value * 365 - g.days, rate: perTick(1, ignorePause), active: true };
                default: return null;
            }
        } catch (e) { return null; }
    }

    // El net/día no tiene fórmula cerrada: sube a saltos cuando el job sube de
    // nivel. Se mide la pendiente real con una media móvil lenta, muestreada UNA
    // vez por tick desde afterTick() — al pintar el panel sería "por render" y el
    // ETA saldría escalado por la diferencia de frecuencias. El alpha bajo y el
    // mínimo de muestras son lo que evita el parpadeo entre level-ups.
    function sampleRates() {
        if (W.gameData.paused) return;   // en pausa se conserva la última tasa
        for (let i = 0; i < state.milestones.length; i++) {
            const m = state.milestones[i];
            if (m.done || forecast(m, true)) continue;
            const v = currentValue(m);
            if (v === null || v === undefined) continue;
            const prev = rates[m.id];
            if (!prev) { rates[m.id] = { value: v, rate: 0, samples: 0 }; continue; }
            prev.rate = prev.rate * (1 - RATE_ALPHA) + (v - prev.value) * RATE_ALPHA;
            prev.value = v;
            prev.samples++;
        }
    }

    function empiricalRate(m) {
        const r = rates[m.id];
        return (r && r.samples >= RATE_MIN_SAMPLES && r.rate > 0) ? r.rate : null;
    }

    // Ticks hasta llegar a targetLevel teniendo en cuenta que la xp/día cambia por
    // el camino. Dos motivos, y los dos importan:
    //
    // 1. La tarea se potencia a sí misma. addMultipliers() le mete a toda Skill el
    //    efecto de Concentration —Concentration incluida— y a toda tarea
    //    getHappiness, que depende de Meditation; Dark influence y Demon training
    //    dan "All xp" y también se alcanzan.
    // 2. La otra tarea activa la potencia. Solo las skills dan efectos de xp (los
    //    jobs solo dan ingreso), y solo hay una skill activa por vez, así que el
    //    único acople posible es: hito sobre el job actual mientras la skill actual
    //    le empuja la xp (Productivity, Meditation vía felicidad, Battle tactics,
    //    Mana control, Dark influence, Demon training).
    //
    // En vez de modelar cada caso se evalúa el getXpGain() real con los niveles
    // hipotéticos: se pisan los .level, se pregunta, y se restauran en un finally.
    // Es síncrono, nada corre en el medio.
    //
    // Para una tarea que NO estás haciendo el ETA es un "si la activás", y activarla
    // significa dejar de hacer la otra: ahí no se acopla nada.

    // Integra una sola tarea, desde un nivel y una xp dados.
    function ticksIntegrado(task, desdeNivel, desdeXp, target, porTick) {
        const real = task.level;
        let ticks = 0;
        try {
            for (let L = desdeNivel; L < target; L++) {
                task.level = L;
                const gain = task.getXpGain();
                if (!(gain > 0)) return null;
                const falta = maxXpAt(task, L) - (L === desdeNivel ? desdeXp : 0);
                ticks += Math.max(falta, 0) / (gain * porTick);
            }
        } finally { task.level = real; }
        return ticks;
    }

    // ¿El nivel de `otra` cambia en algo la xp/día de `task`? Se pregunta en vez de
    // enumerar qué potencia a qué.
    function influyeEn(task, otra) {
        const real = otra.level;
        try {
            const antes = task.getXpGain();
            otra.level = real + 1000;
            return task.getXpGain() !== antes;
        } catch (e) {
            return false;
        } finally { otra.level = real; }
    }

    // Avanza las dos tareas a la vez. Entre level-ups las dos tasas son constantes,
    // así que se salta de level-up en level-up en vez de simular tick por tick.
    const MAX_SALTOS = 20000;

    function ticksAcoplado(task, target, otra, porTick) {
        const nivelTask = task.level, nivelOtra = otra.level;
        let LT = task.level, XT = task.xp, LO = otra.level, XO = otra.xp;
        let ticks = 0, saltos = 0;
        try {
            while (LT < target) {
                task.level = LT; otra.level = LO;
                const gT = task.getXpGain() * porTick;
                const gO = otra.getXpGain() * porTick;
                if (!(gT > 0)) return null;

                if (++saltos > MAX_SALTOS) {
                    // La otra sube tantísimo más rápido que no vale la pena seguir
                    // saltando: se congela donde llegó y se integra el resto.
                    const resto = ticksIntegrado(task, LT, XT, target, porTick);
                    return resto === null ? null : ticks + resto;
                }

                const topeT = maxXpAt(task, LT);
                let dt = (topeT - XT) / gT;
                const topeO = maxXpAt(otra, LO);
                if (gO > 0) dt = Math.min(dt, (topeO - XO) / gO);
                if (!(dt > 0)) dt = 0;

                ticks += dt;
                XT += gT * dt;
                XO += gO * dt;
                if (XT >= topeT * (1 - 1e-12)) { LT++; XT = 0; }
                if (gO > 0 && XO >= topeO * (1 - 1e-12)) { LO++; XO = 0; }
            }
        } finally { task.level = nivelTask; otra.level = nivelOtra; }
        return ticks;
    }

    // ¿El nivel de `otra` cambia lo que devuelve `fn`? Misma sonda que influyeEn,
    // pero para magnitudes globales (la esperanza de vida, la velocidad del juego).
    function influyeEnValor(otra, fn) {
        if (!otra) return false;
        const real = otra.level;
        try {
            const antes = fn();
            otra.level = real + 1000;
            return fn() !== antes;
        } catch (e) {
            return false;
        } finally { otra.level = real; }
    }

    // Ticks que quedan de vida. getLifespan() depende de Immortality y de Super
    // immortality, y la velocidad depende de Time warping: si alguna de esas es tu
    // skill actual, el número se corre mientras la subís, así que se simula por
    // level-ups. Si no, es una división.
    function ticksHastaMorir() {
        const g = W.gameData;
        const skill = g.currentSkill;
        const simple = () => {
            const porTick = gameSpeed(true) / updateSpeed();
            if (!(porTick > 0)) return null;
            const faltan = W.getLifespan() - g.days;
            return faltan <= 0 ? 0 : faltan / porTick;
        };
        if (!skill) return simple();
        const importa = influyeEnValor(skill, () => W.getLifespan()) ||
                        influyeEnValor(skill, () => gameSpeed(true));
        if (!importa) return simple();

        const nivelReal = skill.level;
        let dias = g.days, LS = skill.level, XS = skill.xp, ticks = 0, saltos = 0;
        try {
            while (true) {
                skill.level = LS;
                const porTick = gameSpeed(true) / updateSpeed();
                if (!(porTick > 0)) return null;
                const vida = W.getLifespan();
                if (dias >= vida) return ticks;
                const hastaMorir = (vida - dias) / porTick;

                const gS = skill.getXpGain() * porTick;
                const hastaSubir = gS > 0 ? (maxXpAt(skill, LS) - XS) / gS : Infinity;

                if (hastaSubir >= hastaMorir || ++saltos > MAX_SALTOS) return ticks + hastaMorir;
                ticks += hastaSubir;
                dias += hastaSubir * porTick;
                LS++; XS = 0;
            }
        } finally { skill.level = nivelReal; }
    }

    // Ticks hasta que las monedas lleguen a cero, con el net actual en rojo. El
    // ingreso sube con el nivel del job (getLevelMultiplier), y la skill actual
    // puede empujar tanto la xp del job como el propio ingreso o los gastos
    // (Bargaining abarata, Strength paga más en militar), así que se avanzan las dos
    // saltando de level-up en level-up. Devuelve null si el net se recupera antes:
    // en ese caso no vas a quebrar.
    function ticksHastaSaldoCero(tope) {
        const limite = tope || MAX_SALTOS;
        const g = W.gameData;
        if (g.coins <= 0) return 0;
        const job = g.currentJob, skill = g.currentSkill;
        const nivelJob = job ? job.level : 0, nivelSkill = skill ? skill.level : 0;
        let coins = g.coins, LJ = nivelJob, XJ = job ? job.xp : 0;
        let LS = nivelSkill, XS = skill ? skill.xp : 0;
        let ticks = 0, saltos = 0;
        try {
            while (true) {
                if (job) job.level = LJ;
                if (skill) skill.level = LS;
                const porTick = gameSpeed(true) / updateSpeed();
                if (!(porTick > 0)) return null;
                const net = netPerDay();
                if (net === null) return null;
                if (net >= 0) return null;              // te recuperaste antes de quebrar

                const hastaCero = coins / (-net * porTick);
                const gJ = job ? job.getXpGain() * porTick : 0;
                const gS = skill ? skill.getXpGain() * porTick : 0;
                const subeJob = gJ > 0 ? (maxXpAt(job, LJ) - XJ) / gJ : Infinity;
                const subeSkill = gS > 0 ? (maxXpAt(skill, LS) - XS) / gS : Infinity;
                const proximo = Math.min(subeJob, subeSkill);

                if (proximo >= hastaCero || ++saltos > limite) return ticks + hastaCero;

                ticks += proximo;
                coins += net * porTick * proximo;
                if (gJ > 0) XJ += gJ * proximo;
                if (gS > 0) XS += gS * proximo;
                if (subeJob <= proximo) { LJ++; XJ = 0; }
                if (subeSkill <= proximo) { LS++; XS = 0; }
            }
        } finally {
            if (job) job.level = nivelJob;
            if (skill) skill.level = nivelSkill;
        }
    }

    // Ticks hasta que el net/día alcance el umbral de un hito de Shop o de
    // cantidad. El net no sube de a poco: pega un salto cada vez que el job sube de
    // nivel, porque el ingreso es base * (1 + log10(nivel+1)) * multiplicadores. Es
    // decir que el cruce SIEMPRE cae en un level-up, y entre uno y otro el net es
    // constante. Así que se salta de level-up en level-up y se comprueba después de
    // cada uno, avanzando también la skill actual, que puede empujar la xp del job,
    // el ingreso (Strength en militar, Demon's wealth) o los gastos (Bargaining e
    // Intimidation abaratan los items).
    //
    // El umbral se recalcula en cada tramo por lo mismo: si Bargaining sube, el
    // producto se abarata y el objetivo se acerca solo.
    //
    // Devuelve Infinity si con este job no se llega (no hay ETA que mostrar), y
    // null si directamente no se puede simular, para que el llamador use la media
    // móvil de siempre.
    const MAX_SALTOS_NET = 3000;
    // Los hitos de Shop preguntan por la supervivencia, que cuesta una simulación
    // anidada por cada level-up; se recorren menos tramos a propósito. Igual se
    // cumplen mucho antes que el umbral estricto, así que alcanza de sobra.
    const MAX_SALTOS_NET_SHOP = 300;

    function ticksHastaNet(m) {
        const g = W.gameData;
        const cumple = () => isMet(m);
        const tope = m.type === 'net' ? MAX_SALTOS_NET_SHOP : MAX_SALTOS_NET;
        if (cumple()) return 0;

        const job = g.currentJob, skill = g.currentSkill;
        if (!job && !skill) return null;
        if (!(gameSpeed(true) / updateSpeed() > 0)) return null;

        const nivelJob = job ? job.level : 0, nivelSkill = skill ? skill.level : 0;
        let LJ = nivelJob, XJ = job ? job.xp : 0;
        let LS = nivelSkill, XS = skill ? skill.xp : 0;
        let ticks = 0;
        try {
            for (let saltos = 0; saltos < tope; saltos++) {
                if (job) job.level = LJ;
                if (skill) skill.level = LS;
                const porTick = gameSpeed(true) / updateSpeed();
                if (!(porTick > 0)) return null;

                const gJ = job ? job.getXpGain() * porTick : 0;
                const gS = skill ? skill.getXpGain() * porTick : 0;
                const subeJob = gJ > 0 ? (maxXpAt(job, LJ) - XJ) / gJ : Infinity;
                const subeSkill = gS > 0 ? (maxXpAt(skill, LS) - XS) / gS : Infinity;
                const proximo = Math.min(subeJob, subeSkill);
                if (!isFinite(proximo)) return Infinity;   // nada sube: no se llega

                ticks += proximo;
                if (gJ > 0) XJ += gJ * proximo;
                if (gS > 0) XS += gS * proximo;
                if (subeJob <= proximo) { LJ++; XJ = 0; }
                if (subeSkill <= proximo) { LS++; XS = 0; }

                if (job) job.level = LJ;
                if (skill) skill.level = LS;
                if (cumple()) return ticks;
            }
            return Infinity;
        } finally {
            if (job) job.level = nivelJob;
            if (skill) skill.level = nivelSkill;
        }
    }

    // Corre `fn` como si el producto ya estuviera comprado: la Property reemplaza a
    // la actual, un Misc se suma, y en los dos casos se apagan los boosts puntuales
    // (los mismos que descuenta shopCost). El margen encarece el producto a
    // propósito, que es lo que significa pedir colchón: sobrevivir a algo un 50%
    // más caro. Se restaura todo en el finally.
    function conCompraSimulada(name, margen, fn) {
        const g = W.gameData;
        const it = g.itemData[name];
        if (!it) return null;

        const propReal = g.currentProperty, miscReal = g.currentMisc;
        const teniaPropio = Object.prototype.hasOwnProperty.call(it, 'getExpense');
        const gastoPropio = teniaPropio ? it.getExpense : null;
        try {
            if (margen && margen !== 1) {
                const base = it.getExpense.bind(it);
                it.getExpense = () => base() * margen;
            }
            const conservados = (miscReal || []).filter(x => x && !esMiscPuntual(x.name));
            if (isPropertyName(name)) {
                g.currentProperty = it;
                g.currentMisc = conservados;
            } else {
                g.currentMisc = conservados.concat(conservados.includes(it) ? [] : [it]);
            }
            return fn();
        } catch (e) {
            return null;
        } finally {
            g.currentProperty = propReal;
            g.currentMisc = miscReal;
            if (teniaPropio) it.getExpense = gastoPropio; else delete it.getExpense;
        }
    }

    // ¿Comprarlo ahora te deja de pie? Dos formas de que sí: que ni siquiera quedes
    // en rojo, o que quedes en rojo pero el ingreso del job te alcance antes de
    // vaciarte — exactamente lo que dice el cartel de arriba del panel.
    // null = no se pudo determinar.
    const TOPE_SUPERVIVENCIA = 500;

    function sobrevivisComprando(name, margen) {
        return conCompraSimulada(name, margen, () => {
            const net = netPerDay();
            if (net === null) return null;
            if (net >= 0) return true;                  // ni siquiera quedás en rojo
            if (W.gameData.coins <= 0) return false;
            if (!(gameSpeed(true) / updateSpeed() > 0)) return null;
            // null acá significa que el net se puso en verde antes de llegar a cero
            return ticksHastaSaldoCero(TOPE_SUPERVIVENCIA) === null;
        });
    }

    function ticksToLevel(task, targetLevel, ignorePause) {
        if (task.level >= targetLevel) return 0;
        if (targetLevel - task.level > 10000) return null;
        const porTick = gameSpeed(ignorePause) / updateSpeed();
        if (!(porTick > 0)) return null;

        const g = W.gameData;
        // Solo el job actual puede estar acoplado, y solo con la skill actual.
        const otra = (g.currentJob && g.currentJob.name === task.name) ? g.currentSkill : null;
        if (otra && otra.name !== task.name && influyeEn(task, otra)) {
            const r = ticksAcoplado(task, targetLevel, otra, porTick);
            if (r !== null) return r;
        }
        return ticksIntegrado(task, task.level, task.xp, targetLevel, porTick);
    }

    function ticksLeft(m) {
        // Los hitos de nivel llevan la cuenta integrada nivel por nivel...
        if ((m.type === 'job' || m.type === 'skill') && m.field !== 'maxLevel') {
            const t = W.gameData.taskData[m.target];
            if (t) {
                try { return ticksToLevel(t, m.value, true); }
                catch (e) { console.warn('[Hitos] ticksToLevel:', e); }
            }
        }
        // ...y los de net/día, la simulación de level-ups.
        if (m.type === 'net' || m.type === 'netval') {
            try {
                const t = ticksHastaNet(m);
                if (t !== null) return t;
            } catch (e) { console.warn('[Hitos] ticksHastaNet:', e); }
        }
        const f = forecast(m, true);
        if (f) {
            if (f.remaining <= 0) return 0;
            return f.rate > 0 ? f.remaining / f.rate : null;
        }
        const t = threshold(m), v = currentValue(m);
        if (t === null || v === null) return null;
        if (v >= t) return 0;
        const r = empiricalRate(m);
        return r ? (t - v) / r : null;
    }

    // Requisitos que el juego efectivamente te muestra. updateRequiredRows() pinta,
    // por cada categoría, UNA sola fila: la del primer elemento todavía no
    // completado ("Farmer: Beggar level 3/10"). Los de más abajo en la categoría
    // existen en gameData pero no están en pantalla, y las categorías con candado
    // propio (The Arcane Association, Dark magic) no muestran ninguna.
    function visibleRequesters() {
        const set = new Set();
        const reqs = W.gameData.requirements;
        const groups = [pageGlobal('jobCategories'), pageGlobal('skillCategories'), pageGlobal('itemCategories')];
        for (const group of groups) {
            if (!group) continue;
            for (const catName in group) {
                const catReq = reqs[catName];
                if (catReq && !catReq.completed) continue;
                for (const name of group[catName]) {
                    const r = reqs[name];
                    if (!r) continue;
                    if (!r.completed) { set.add(name); break; }
                }
            }
        }
        return set;
    }

    // `visibles`: si se pasa un Set, solo cuentan los requisitos de esos elementos.
    function suggestedLevel(name, visibles) {
        const g = W.gameData;
        const lvl = g.taskData[name]?.level ?? 0;
        let best = null, bestWhy = null;
        let any = null, anyWhy = null;

        const reqs = g.requirements;
        for (const key in reqs) {
            if (visibles && !visibles.has(key)) continue;
            const r = reqs[key];
            if (!r || !r.requirements) continue;

            const subReqs = Array.isArray(r.requirements) ? r.requirements : [r.requirements];
            for (let i = 0; i < subReqs.length; i++) {
                const req = subReqs[i];
                if (req?.task !== name || typeof req.requirement !== 'number') continue;
                const reqLvl = req.requirement;
                const why = `${key} pide ${name} nivel ${reqLvl}.`;

                if (any === null || reqLvl < any) { any = reqLvl; anyWhy = why; }
                if (reqLvl > lvl && !r.completed) {
                    if (best === null || reqLvl < best) {
                        best = reqLvl;
                        bestWhy = why;
                    }
                }
            }
        }
        if (best !== null) return { level: best, why: bestWhy };
        if (any !== null)  return { level: any,  why: anyWhy + ' (ya cumplido)' };
        return { level: null, why: null };
    }

    /* ------------------------------------------------------------------ */
    /* Algoritmos de Selección Automática                                 */
    /* ------------------------------------------------------------------ */

    // Obtiene todas las Skills en el orden visual de la interfaz (de arriba a abajo)
    function getAllSkillsInOrder() {
        const cats = pageGlobal('skillCategories');
        const list = [];
        if (cats) {
            for (const cat in cats) {
                const arr = cats[cat];
                if (Array.isArray(arr)) {
                    for (let i = 0; i < arr.length; i++) {
                        if (!list.includes(arr[i])) list.push(arr[i]);
                    }
                }
            }
        }
        const allTaskNames = Object.keys(W.gameData?.taskData || {}).filter(n => !isJobName(n));
        for (let i = 0; i < allTaskNames.length; i++) {
            if (!list.includes(allTaskNames[i])) list.push(allTaskNames[i]);
        }
        return list;
    }

    // Elige la Skill con el menor nivel pendiente ENTRE LOS REQUISITOS QUE SE VEN
    // en pantalla. Un requisito más chico pedido por algo que todavía no aparece
    // (por ejemplo "Merchant pide Bargaining 50" cuando ni Farmer desbloqueaste)
    // se ignora. La skill en sí no se filtra: puede estar bloqueada, lo que importa
    // es que algo visible la esté pidiendo. Los empates los resuelve el orden
    // visual, de arriba hacia abajo.
    function findNextSkillMilestoneTarget() {
        const skills = getAllSkillsInOrder();
        const visibles = visibleRequesters();
        let bestCandidate = null;
        let minZ = Infinity;

        for (let i = 0; i < skills.length; i++) {
            const name = skills[i];
            const s = suggestedLevel(name, visibles);
            const curLvl = W.gameData.taskData[name]?.level ?? 0;

            if (s.level !== null && s.level > curLvl) {
                // Al usar '<' estricto, si dos Skills tienen el mismo nivel Z mínimo,
                // se conserva la primera encontrada en el orden de arriba a abajo.
                if (s.level < minZ) {
                    minZ = s.level;
                    bestCandidate = { target: name, level: s.level, why: s.why };
                }
            }
        }

        return bestCandidate;
    }

    function findNextJobMilestoneTarget(excludeJobName) {
        const taskData = W.gameData.taskData;
        let bestCandidate = null;
        let minIncome = Infinity;

        for (const name in taskData) {
            if (name === excludeJobName || !isJobName(name) || !isUnlocked(name)) continue;
            const t = taskData[name];
            if (t.level !== 0) continue;

            const baseIncome = typeof t.baseData?.income === 'number' ? t.baseData.income : Infinity;
            if (baseIncome < minIncome) {
                minIncome = baseIncome;
                const s = suggestedLevel(name);
                const targetLvl = s.level !== null ? s.level : 10;
                bestCandidate = { target: name, level: targetLvl, why: s.why || 'Los jobs se desbloquean con el anterior en nivel 10.' };
            }
        }
        return bestCandidate;
    }

    // El siguiente escalón es el producto más barato que TODAVÍA no te bancás.
    // Buscar el delta más parecido al recién cumplido caía casi siempre en algo
    // que ya podés pagar, y el hito nacía tachado.
    function findNextShopMilestoneTarget(excludeItemName, completedCostRef) {
        const itemData = W.gameData.itemData;
        const net = netPerDay() ?? 0;
        const floor = Math.max(net, typeof completedCostRef === 'number' ? completedCostRef : -Infinity);
        let bestCandidate = null;
        let minDelta = Infinity;

        for (const name in itemData) {
            if (name === excludeItemName || !isUnlocked(name)) continue;
            const c = shopCost(name);
            if (!c || c.owned || c.delta <= 0) continue;
            if (c.delta <= floor) continue;          // ya te lo bancás: no es un objetivo
            if (c.delta < minDelta) {
                minDelta = c.delta;
                bestCandidate = { target: name, margin: 1, costDelta: c.delta };
            }
        }
        return bestCandidate;
    }

    function describe(m) {
        switch (m.type) {
            case 'job':   return `[Job] ${m.target} — ${m.field === 'maxLevel' ? 'nivel máx' : 'nivel'} ${fmt(m.value)}`;
            case 'skill': return `[Skill] ${m.target} — ${m.field === 'maxLevel' ? 'nivel máx' : 'nivel'} ${fmt(m.value)}`;
            case 'coins': return `Monedas ≥ ${fmt(m.value)}`;
            case 'age':   return `Edad ≥ ${fmt(m.value)} años`;
            case 'evil':  return `Evil ≥ ${fmt(m.value)}`;
            case 'netval':return `Net/día ≥ ${fmt(m.value)}`;
            case 'net':   return `Net/día ≥ ${m.target}${(m.value && m.value !== 1) ? ` (x${m.value})` : ''}`;
            case 'unlock':return `Se desbloquea: ${m.target}`;
            default:      return '?';
        }
    }

    function progressText(m) {
        if (m.type === 'unlock') return '';
        const v = currentValue(m), t = threshold(m);
        if (v === null || t === null) return '';
        let txt = `${fmt(v)} / ${fmt(t)}`;
        if (m.type === 'net') {
            const c = shopCost(m.target);
            if (c?.owned) {
                txt += ' (ya lo tenés)';
            } else if (c) {
                const partes = [];
                if (c.property && c.current > 0) partes.push(`−${fmt(c.current)} de ${c.currentName}`);
                if (c.dropped?.total > 0) partes.push(`−${fmt(c.dropped.total)} de ${c.dropped.names.join(', ')}`);
                if (partes.length) txt += ` (${fmt(c.cost)} ${partes.join(' ')})`;
                // Lo que decide el hito no es el umbral sino si sobrevivís a la
                // compra, así que se muestra cuánto aguantarías comprándolo hoy.
                if (!m.done) {
                    const aguante = conCompraSimulada(m.target, m.value || 1, () => {
                        const net = netPerDay();
                        if (net === null || net >= 0) return null;
                        return fmtEta(ticksHastaSaldoCero(TOPE_SUPERVIVENCIA));
                    });
                    if (aguante) txt += ` · comprándolo te vaciás en ~${aguante}`;
                }
            }
        }
        if (!m.done) {
            const eta = fmtEta(ticksLeft(m));
            if (eta) {
                // Una tarea que no estás haciendo igual proyecta un ETA con su
                // xp/día actual: es un "si la pusieras ahora", no una cuenta regresiva.
                const f = forecast(m, true);
                txt += ` · ~${eta}${(f && f.active === false) ? ' si la activás' : ''}`;
            }
        }
        return txt;
    }

    /* ================================================================== */
    /* Hooks al Tick y Precisión                                          */
    /* ================================================================== */

    function installHooks() {
        if (typeof W.applySpeed !== 'function' ||
            typeof W.updateUI !== 'function' ||
            typeof W.increaseDays !== 'function') return false;

        const origApplySpeed = W.applySpeed;
        W.applySpeed = function (value) {
            return origApplySpeed(value) * tickScale;
        };

        const origIncreaseDays = W.increaseDays;
        W.increaseDays = function () {
            try { beforeTick(); } catch (e) { tickScale = 1; console.warn('[Hitos] beforeTick:', e); }
            return origIncreaseDays.apply(this, arguments);
        };

        const origUpdateUI = W.updateUI;
        W.updateUI = function () {
            const r = origUpdateUI.apply(this, arguments);
            try { afterTick(); } catch (e) { console.warn('[Hitos] afterTick:', e); }
            tickScale = 1;
            return r;
        };

        return true;
    }

    let scaledStreak = 0;
    let frenoPorSaldo = false;   // este tick se acortó para no pasarse de cero
    let avisoSaldo = false;      // ya se avisó por este bajón; se rearma al recuperarse

    function beforeTick() {
        tickScale = 1;
        frenoPorSaldo = false;
        if (!gameReady() || W.gameData.paused) return;

        const porTick = gameSpeed(false) / updateSpeed();

        // Cuánto falta para quedarse sin monedas, en ticks. Acá no se puede pasar de
        // largo: apenas las monedas cruzan cero, applyExpenses() llama a goBankrupt()
        // y te saca la property y los misc. Por eso este tramo se acorta un pelo POR
        // DEBAJO en vez de por encima, al revés que los hitos.
        let fSaldo = Infinity;
        if (state.pauseBroke && porTick > 0) {
            const net = netPerDay();
            if (net !== null && net < 0 && W.gameData.coins > 0) {
                fSaldo = W.gameData.coins / (-net * porTick);
            }
        }

        let f = 1;
        if (state.precise && scaledStreak <= 20) {
            for (let i = 0; i < state.milestones.length; i++) {
                const m = state.milestones[i];
                if (m.done) continue;
                const fc = forecast(m, false);
                if (!fc || !fc.active || fc.rate <= 0 || fc.remaining <= 0) continue;
                const ticks = fc.remaining / fc.rate;
                if (ticks < 1) f = Math.min(f, ticks);
            }
        } else if (scaledStreak > 20) { scaledStreak = 0; }

        const escalaHito = (f > 0 && f < 1) ? f * (1 + 1e-9) : 1;
        const escalaSaldo = (fSaldo > 0 && fSaldo < 1) ? fSaldo * (1 - 1e-9) : 1;

        if (escalaSaldo < escalaHito) {
            tickScale = escalaSaldo;
            frenoPorSaldo = true;
            scaledStreak = 0;
        } else if (escalaHito < 1) {
            tickScale = escalaHito;
            scaledStreak++;
        } else {
            scaledStreak = 0;
        }
    }

    function afterTick() {
        if (!gameReady()) return;

        const now = completedUnlocks();
        if (knownUnlocks === null) {
            knownUnlocks = now;
        } else {
            const fresh = [], debut = [];
            let grew = false;
            now.forEach(k => {
                if (!knownUnlocks.has(k)) {
                    fresh.push(k);
                    if (!everSet.has(k)) debut.push(k);
                }
                if (!everSet.has(k)) { everSet.add(k); grew = true; }
            });
            knownUnlocks = now;
            if (grew) { state.everUnlocked = Array.from(everSet); save(); }

            const list = state.ignoreSeen ? debut : fresh;
            if (list.length && state.anyUnlock) trigger('Nuevo desbloqueo: ' + list.join(', '));
        }

        // Quedarse sin monedas: con el tick acortado se frena justo antes; si el
        // pausado exacto está apagado, al menos se avisa al cruzar cero.
        if (state.pauseBroke) {
            const net = netPerDay();
            if (frenoPorSaldo || (net !== null && net < 0 && W.gameData.coins <= 0)) {
                if (!avisoSaldo) { avisoSaldo = true; trigger('Te quedaste sin monedas'); }
            } else if (W.gameData.coins > 0 && (net === null || net >= 0)) {
                avisoSaldo = false;
            }
        }
        frenoPorSaldo = false;

        sampleRates();

        let changed = false;
        let lastFinishedMilestone = null;
        for (let i = 0; i < state.milestones.length; i++) {
            const m = state.milestones[i];
            if (m.done) continue;
            if (isMet(m)) {
                m.done = true;
                changed = true;
                trigger(describe(m));
                if (m.type === 'skill' || m.type === 'job' || m.type === 'net') {
                    lastFinishedMilestone = m;
                }
            }
        }

        if (lastFinishedMilestone && el.type) {
            if (lastFinishedMilestone.type === 'skill') {
                const nextSkill = findNextSkillMilestoneTarget();
                if (nextSkill) {
                    el.type.value = 'skill';
                    syncForm();
                    el.target.value = nextSkill.target;
                    el.field.value = 'level';
                    el.value.value = String(nextSkill.level);
                    el.hint.textContent = nextSkill.why + ' Podés cambiarlo.';
                }
            } else if (lastFinishedMilestone.type === 'job') {
                const nextJob = findNextJobMilestoneTarget(lastFinishedMilestone.target);
                if (nextJob) {
                    el.type.value = 'job';
                    syncForm();
                    el.target.value = nextJob.target;
                    el.field.value = 'level';
                    el.value.value = String(nextJob.level);
                    el.hint.textContent = nextJob.why + ' Podés cambiarlo.';
                }
            } else if (lastFinishedMilestone.type === 'net') {
                const completedCost = shopCost(lastFinishedMilestone.target)?.delta || lastFinishedMilestone.value;
                const nextShop = findNextShopMilestoneTarget(lastFinishedMilestone.target, completedCost);
                if (nextShop) {
                    el.type.value = 'net';
                    syncForm();
                    el.target.value = nextShop.target;
                    el.value.value = '1';
                }
            }
        }

        if (changed) save();

        const t = performance.now();
        if (t - lastRender > RENDER_MS) { lastRender = t; renderList(); }
    }

    /* ================================================================== */
    /* Notificaciones                                                     */
    /* ================================================================== */

    function pauseGame() {
        if (W.gameData && !W.gameData.paused) W.gameData.paused = true;
    }

    let audioCtx = null;
    function beep() {
        if (!state.sound) return;
        try {
            if (!audioCtx) audioCtx = new (W.AudioContext || W.webkitAudioContext)();
            if (audioCtx.state === 'suspended') audioCtx.resume();
            const osc = audioCtx.createOscillator(), gain = audioCtx.createGain();
            osc.connect(gain); gain.connect(audioCtx.destination);
            osc.type = 'sine'; osc.frequency.value = 880;
            gain.gain.setValueAtTime(0.0001, audioCtx.currentTime);
            gain.gain.exponentialRampToValueAtTime(0.15, audioCtx.currentTime + 0.02);
            gain.gain.exponentialRampToValueAtTime(0.0001, audioCtx.currentTime + 0.5);
            osc.start(); osc.stop(audioCtx.currentTime + 0.55);
        } catch (e) { }
    }

    function desktopNotify(label) {
        if (!state.desktopNotif || !('Notification' in W) || Notification.permission !== 'granted') return;
        try { new Notification('Progress Knight — hito alcanzado', { body: label }); } catch (e) { }
    }

    function flashTitle(label) {
        if (titleTimer) clearInterval(titleTimer);
        let on = true;
        titleTimer = setInterval(() => {
            document.title = on ? '⏸ HITO — ' + label : originalTitle;
            on = !on;
        }, 900);
    }

    function stopFlash() {
        if (!titleTimer) return;
        clearInterval(titleTimer); titleTimer = null;
        document.title = originalTitle;
    }

    window.addEventListener('focus', stopFlash);
    document.addEventListener('visibilitychange', () => { if (!document.hidden) stopFlash(); });

    function trigger(label) {
        pauseGame();
        showBanner(label);
        beep();
        desktopNotify(label);
        if (document.hidden) flashTitle(label);
    }

    /* ================================================================== */
    /* UI                                                                 */
    /* ================================================================== */

    const CSS = `
    #pkHitos {
        position: fixed; right: 14px; bottom: 14px; z-index: 99999;
        width: 310px; font-family: system-ui, "Segoe UI", Arial, sans-serif;
        font-size: 12px; color: #eaeaea; background: #23262b;
        border: 1px solid #3a3f47; border-radius: 8px;
        box-shadow: 0 6px 24px rgba(0,0,0,.45); overflow: hidden;
    }
    #pkHitos header {
        display: flex; align-items: center; justify-content: space-between;
        padding: 8px 10px; background: #2c3037; cursor: pointer; font-weight: 600;
    }
    #pkHitos header span.badge {
        background: #4c8bf5; color: #fff; border-radius: 10px;
        padding: 1px 7px; font-size: 11px; margin-left: 6px;
    }
    #pkHitos .body { padding: 10px; }
    #pkHitos.collapsed .body { display: none; }
    #pkHitos select, #pkHitos input[type=text] {
        width: 100%; box-sizing: border-box; background: #1b1e22; color: #eaeaea;
        border: 1px solid #3a3f47; border-radius: 4px; padding: 5px 6px;
        margin-bottom: 6px; font-size: 12px;
    }
    #pkHitos optgroup { color: #8b939e; font-style: normal; }
    #pkHitos option { color: #eaeaea; }
    #pkHitos .row2 { display: flex; gap: 6px; }
    #pkHitos .row2 > * { flex: 1; }
    #pkHitos button.add {
        width: 100%; background: #4c8bf5; color: #fff; border: 0;
        border-radius: 4px; padding: 6px; cursor: pointer; font-weight: 600;
    }
    #pkHitos button.add:hover { background: #3f78d8; }
    #pkHitos ul { list-style: none; margin: 10px 0 0; padding: 0; max-height: 210px; overflow-y: auto; }
    #pkHitos li {
        display: flex; align-items: center; gap: 6px;
        padding: 5px 6px; border-radius: 4px; background: #1b1e22; margin-bottom: 4px;
    }
    #pkHitos li.done { opacity: .55; text-decoration: line-through; }
    #pkHitos li .txt { flex: 1; line-height: 1.3; }
    #pkHitos li .prog { color: #8b939e; font-size: 11px; display: block; white-space: pre-line; }
    #pkHitos li button {
        background: transparent; border: 0; color: #8b939e; cursor: pointer;
        font-size: 13px; padding: 0 3px;
    }
    #pkHitos li button:hover { color: #fff; }
    #pkHitos label.chk.sub { margin-left: 20px; font-size: 11px; color: #8b939e; }
    #pkHitos label.chk.sub.off { display: none; }
    #pkHitos label.chk {
        display: flex; align-items: center; gap: 6px; margin: 6px 0; cursor: pointer; color: #c9ced6;
    }
    #pkHitos .banner {
        background: #f5a623; color: #20232a; font-weight: 600;
        padding: 7px 9px; border-radius: 4px; margin-bottom: 8px;
        display: none; line-height: 1.35;
    }
    #pkHitos .hint { color: #8b939e; font-size: 11px; margin: 2px 0 8px; }
    #pkHitos .status { color: #6f7681; font-size: 10px; margin-top: 8px; text-align: right; }
    #pkHitos .vitales {
        margin-top: 10px; padding: 6px 8px; background: #1b1e22; border-radius: 4px;
        color: #c9ced6; font-size: 11px; line-height: 1.5;
    }
    #pkHitos .vitales:empty { display: none; }
    #pkHitos .vitales .rojo { color: #f0a05a; }
    `;

    let el = {};

    function grouped(categories, allNames, fallbackLabel) {
        const out = [], used = new Set();
        for (const cat in (categories || {})) {
            const names = categories[cat].filter(n => allNames.includes(n));
            names.forEach(n => used.add(n));
            if (names.length) out.push([cat, names]);
        }
        const rest = allNames.filter(n => !used.has(n));
        if (rest.length) out.push([out.length ? 'Otros' : (fallbackLabel || 'Todos'), rest]);
        return out;
    }

    function jobGroups()   { return grouped(pageGlobal('jobCategories'),   Object.keys(W.gameData.taskData).filter(isJobName), 'Jobs'); }
    function skillGroups() { return grouped(pageGlobal('skillCategories'), Object.keys(W.gameData.taskData).filter(n => !isJobName(n)), 'Skills'); }
    function itemGroups()  { return grouped(pageGlobal('itemCategories'),  Object.keys(W.gameData.itemData), 'Shop'); }
    function unlockGroups(){ return [['Desbloqueos', Object.keys(W.gameData.requirements).sort()]]; }

    function buildUI() {
        const style = document.createElement('style');
        style.textContent = CSS;
        document.head.appendChild(style);

        const box = document.createElement('div');
        box.id = 'pkHitos';
        box.innerHTML = `
            <header>
                <span>⏸ Hitos<span class="badge" id="pkCount">0</span></span>
                <span id="pkToggle">▾</span>
            </header>
            <div class="body">
                <div class="banner" id="pkBanner"></div>
                <select id="pkType">
                    <option value="job">Nivel de Job</option>
                    <option value="skill">Nivel de Skill</option>
                    <option value="coins">Monedas</option>
                    <option value="age">Edad (años)</option>
                    <option value="evil">Evil</option>
                    <option value="netval">Net/día ≥ cantidad</option>
                    <option value="net">Net/día ≥ producto del Shop</option>
                    <option value="unlock">Desbloqueo puntual</option>
                </select>
                <select id="pkTarget"></select>
                <div class="row2" id="pkValueRow">
                    <select id="pkField">
                        <option value="level">Nivel actual</option>
                        <option value="maxLevel">Nivel máximo</option>
                    </select>
                    <input type="text" id="pkValue" placeholder="valor" />
                </div>
                <div class="hint" id="pkHint"></div>
                <button class="add" id="pkAdd">Agregar hito</button>
                <label class="chk"><input type="checkbox" id="pkPrecise"> Pausado exacto (tick parcial)</label>
                <label class="chk"><input type="checkbox" id="pkAnyUnlock"> Pausar ante cualquier desbloqueo nuevo</label>
                <label class="chk sub"><input type="checkbox" id="pkIgnoreSeen"> ignorar los ya vistos en vidas anteriores</label>
                <label class="chk"><input type="checkbox" id="pkBroke"> Pausar antes de quedarte sin monedas</label>
                <label class="chk"><input type="checkbox" id="pkSound"> Sonido al pausar</label>
                <label class="chk"><input type="checkbox" id="pkNotif"> Notificación del navegador</label>
                <div class="vitales" id="pkVitals"></div>
                <ul id="pkList"></ul>
                <div class="status" id="pkStatus"></div>
            </div>
        `;
        document.body.appendChild(box);

        el = {
            box,
            header: box.querySelector('header'),
            toggle: box.querySelector('#pkToggle'),
            count: box.querySelector('#pkCount'),
            banner: box.querySelector('#pkBanner'),
            type: box.querySelector('#pkType'),
            target: box.querySelector('#pkTarget'),
            valueRow: box.querySelector('#pkValueRow'),
            field: box.querySelector('#pkField'),
            value: box.querySelector('#pkValue'),
            hint: box.querySelector('#pkHint'),
            add: box.querySelector('#pkAdd'),
            list: box.querySelector('#pkList'),
            precise: box.querySelector('#pkPrecise'),
            anyUnlock: box.querySelector('#pkAnyUnlock'),
            ignoreSeen: box.querySelector('#pkIgnoreSeen'),
            ignoreSeenRow: box.querySelector('#pkIgnoreSeen').parentElement,
            broke: box.querySelector('#pkBroke'),
            vitals: box.querySelector('#pkVitals'),
            sound: box.querySelector('#pkSound'),
            notif: box.querySelector('#pkNotif'),
            status: box.querySelector('#pkStatus')
        };

        el.header.addEventListener('click', () => {
            state.collapsed = !state.collapsed;
            box.classList.toggle('collapsed', state.collapsed);
            el.toggle.textContent = state.collapsed ? '▸' : '▾';
            save();
        });

        el.type.addEventListener('change', syncForm);
        el.target.addEventListener('change', applySuggestion);
        el.field.addEventListener('change', applySuggestion);
        el.add.addEventListener('click', addMilestone);
        el.value.addEventListener('keydown', e => { if (e.key === 'Enter') addMilestone(); });

        el.precise.addEventListener('change', () => {
            state.precise = el.precise.checked;
            if (!state.precise) tickScale = 1;
            save(); updateStatus();
        });
        el.anyUnlock.addEventListener('change', () => {
            state.anyUnlock = el.anyUnlock.checked; save(); syncUnlockRow();
        });
        el.ignoreSeen.addEventListener('change', () => {
            state.ignoreSeen = el.ignoreSeen.checked; save();
        });
        el.broke.addEventListener('change', () => { state.pauseBroke = el.broke.checked; save(); });
        el.sound.addEventListener('change', () => { state.sound = el.sound.checked; save(); });
        el.notif.addEventListener('change', () => {
            state.desktopNotif = el.notif.checked;
            if (state.desktopNotif && 'Notification' in W && Notification.permission === 'default') {
                Notification.requestPermission();
            }
            save();
        });

        box.classList.toggle('collapsed', state.collapsed);
        el.toggle.textContent = state.collapsed ? '▸' : '▾';
        el.precise.checked = state.precise;
        el.anyUnlock.checked = state.anyUnlock;
        el.ignoreSeen.checked = state.ignoreSeen;
        syncUnlockRow();
        el.broke.checked = state.pauseBroke;
        el.sound.checked = state.sound;
        el.notif.checked = state.desktopNotif;

        syncForm();
        renderList();
        updateStatus();
    }

    function syncUnlockRow() {
        el.ignoreSeenRow.classList.toggle('off', !state.anyUnlock);
    }

    function updateStatus() {
        if (!el.status) return;
        el.status.textContent = hooksOk
            ? (state.precise ? 'tick a tick · exacto' : 'tick a tick')
            : 'modo compatible (' + FALLBACK_POLL_MS + 'ms)';
    }

    function fillSelect(select, groups) {
        let html = '';
        for (let i = 0; i < groups.length; i++) {
            const [cat, names] = groups[i];
            html += `<optgroup label="${cat}">`;
            for (let j = 0; j < names.length; j++) {
                html += `<option value="${names[j]}">${names[j]}</option>`;
            }
            html += `</optgroup>`;
        }
        select.innerHTML = html;
    }

    function syncForm() {
        const type = el.type.value;
        const needsTarget = ['job', 'skill', 'net', 'unlock'].includes(type);

        el.target.style.display = needsTarget ? '' : 'none';
        el.valueRow.style.display = (type === 'unlock') ? 'none' : 'flex';
        el.field.style.display = (type === 'job' || type === 'skill') ? '' : 'none';

        if (needsTarget) {
            fillSelect(el.target,
                type === 'job'   ? jobGroups()   :
                type === 'skill' ? skillGroups() :
                type === 'net'   ? itemGroups()  : unlockGroups());
        }

        const hints = {
            job:   'Acepta 1000000, 1M, 2.5k o 1e6.',
            skill: 'Acepta 1000000, 1M, 2.5k o 1e6.',
            coins: 'Acepta 1000000, 1M, 2.5k o 1e6.',
            age:   'Se compara contra la edad en años de la sidebar.',
            evil:  'El evil solo sube al renacer (rebirth 2), así que no lleva ETA.',
            netval:'Ingreso menos gastos por día. Ahora estás en ' + fmt(netPerDay()) + '.',
            net:   'Pausa cuando podés bancar ese producto. Se descuenta lo que dejarías de pagar: la Property actual (comprar otra la reemplaza) y los boosts puntuales que tengas activos —Dumbbells, Steel longsword, Sapphire charm— que apagarías. Los que sirven siempre (Book, Study desk, Library, Personal squire, Butler) no se descuentan. Margen opcional: 1 = justo, 1.5 = 50% de colchón.',
            unlock:'Pausa la primera vez que ese elemento queda desbloqueado.'
        };
        el.hint.textContent = hints[type] || '';

        applySuggestion();

        el.value.placeholder =
            type === 'age'    ? 'años (ej. 45)' :
            type === 'coins'  ? 'monedas (ej. 1M)' :
            type === 'evil'   ? 'evil (ej. 100)' :
            type === 'netval' ? 'net/día (ej. 5k)' :
            type === 'net'    ? 'margen (ej. 1)' : 'nivel (ej. 100)';
    }

    function applySuggestion() {
        const type = el.type.value;
        if (type !== 'job' && type !== 'skill') return;
        if (el.field.value === 'maxLevel') { el.value.value = ''; return; }

        const s = suggestedLevel(el.target.value);
        if (s.level !== null) {
            el.value.value = String(s.level);
            el.hint.textContent = s.why + ' Podés cambiarlo.';
        } else if (type === 'job') {
            el.value.value = '10';
            el.hint.textContent = 'Los jobs se desbloquean con el anterior en nivel 10. Podés cambiarlo.';
        } else {
            el.value.value = '';
        }
    }

    function addMilestone() {
        const type = el.type.value;
        const needsTarget = ['job', 'skill', 'net', 'unlock'].includes(type);
        const m = {
            id: Date.now() + '-' + Math.random().toString(36).slice(2, 7),
            type,
            target: needsTarget ? el.target.value : null,
            field: (type === 'job' || type === 'skill') ? el.field.value : null,
            value: null,
            done: false
        };

        if (type === 'net') {
            const raw = el.value.value.trim();
            const v = raw === '' ? 1 : parseNum(raw);
            if (isNaN(v) || v <= 0) { showBanner('Margen inválido. Dejalo vacío para 1, o poné 1.5.'); return; }
            m.value = v;
        } else if (type !== 'unlock') {
            const v = parseNum(el.value.value);
            if (isNaN(v)) { showBanner('Valor inválido. Probá 100, 1M o 1e6.'); return; }
            m.value = v;
        }

        if (isMet(m)) {
            m.done = true;
            showBanner('Ese hito ya está cumplido — lo agregué marcado. Usá ↺ para re-armarlo.');
        }

        state.milestones.push(m);
        el.value.value = '';
        save();
        renderList();
    }

    let listSig = null;
    const rowEls = new Map();

    function listSignature() {
        let s = '';
        for (let i = 0; i < state.milestones.length; i++) {
            const m = state.milestones[i];
            s += (i ? '|' : '') + m.id + (m.done ? ':1' : ':0');
        }
        return s;
    }

    function renderList(force) {
        if (!el.list) return;
        let pending = 0;
        for (let i = 0; i < state.milestones.length; i++) {
            if (!state.milestones[i].done) pending++;
        }
        el.count.textContent = pending;
        if (el.type.value === 'netval') syncFormHintOnly();
        updateVitals();

        const sig = listSignature();
        if (force || sig !== listSig) { rebuildList(); listSig = sig; }
        else updateRows();
    }

    function rebuildList() {
        const scroll = el.list.scrollTop;
        el.list.innerHTML = '';
        rowEls.clear();

        for (let i = 0; i < state.milestones.length; i++) {
            const m = state.milestones[i];
            const li = document.createElement('li');
            if (m.done) li.classList.add('done');

            const txt = document.createElement('span');
            txt.className = 'txt';
            const desc = document.createElement('span');
            const prog = document.createElement('span');
            prog.className = 'prog';
            txt.appendChild(desc);
            txt.appendChild(prog);
            li.appendChild(txt);

            if (m.done) {
                const rearm = document.createElement('button');
                rearm.title = 'Re-armar'; rearm.textContent = '↺';
                rearm.addEventListener('click', () => {
                    m.done = false; delete rates[m.id];
                    save(); renderList(true);
                });
                li.appendChild(rearm);
            }

            const del = document.createElement('button');
            del.title = 'Eliminar'; del.textContent = '✕';
            del.addEventListener('click', () => {
                state.milestones = state.milestones.filter(x => x.id !== m.id);
                delete rates[m.id];
                save(); renderList(true);
            });
            li.appendChild(del);

            rowEls.set(m.id, { li, desc, prog });
            el.list.appendChild(li);
        }
        el.list.scrollTop = scroll;
        updateRows();
    }

    function updateRows() {
        for (let i = 0; i < state.milestones.length; i++) {
            const m = state.milestones[i];
            const row = rowEls.get(m.id);
            if (!row) continue;
            const d = describe(m);
            if (row.desc.textContent !== d) row.desc.textContent = d;
            const pr = progressText(m);
            const shown = pr ? '\n' + pr : '';
            if (row.prog.textContent !== shown) {
                row.prog.textContent = shown;
                row.prog.style.display = pr ? 'block' : 'none';
            }
        }
    }

    // Dos cuentas que no son hitos pero conviene tener a la vista.
    function updateVitals() {
        if (!el.vitals) return;
        const g = W.gameData;
        const filas = [];
        try {
            const muerte = fmtEta(ticksHastaMorir());
            if (muerte) {
                const años = Math.max(0, W.daysToYears(W.getLifespan()) - W.daysToYears(g.days));
                filas.push(`Muerte en ~${muerte} · quedan ${años} años`);
            }
            const net = netPerDay();
            if (net !== null && net < 0) {
                const cero = ticksHastaSaldoCero();
                filas.push(cero === null
                    ? `<span class="rojo">Net en rojo</span>, pero el ingreso lo alcanza antes de vaciarte`
                    : `<span class="rojo">Saldo en cero en ~${fmtEta(cero)}</span>`);
            }
        } catch (e) { /* nunca romper el panel por esto */ }
        const html = filas.map(t => `<div>${t}</div>`).join('');
        if (el.vitals.innerHTML !== html) el.vitals.innerHTML = html;
    }

    function syncFormHintOnly() {
        el.hint.textContent = 'Ingreso menos gastos por día. Ahora estás en ' + fmt(netPerDay()) + '.';
    }

    function showBanner(text) {
        if (!el.banner) return;
        el.banner.textContent = '⏸ ' + text;
        el.banner.style.display = 'block';
        if (state.collapsed) {
            state.collapsed = false;
            el.box.classList.remove('collapsed');
            el.toggle.textContent = '▾';
        }
        clearTimeout(showBanner._t);
        showBanner._t = setTimeout(() => { el.banner.style.display = 'none'; }, 12000);
    }

    /* ================================================================== */
    /* Arranque                                                           */
    /* ================================================================== */

    function boot() {
        if (!gameReady()) { setTimeout(boot, 300); return; }
        load();
        originalTitle = document.title;
        buildUI();

        knownUnlocks = completedUnlocks();
        everSet = new Set(state.everUnlocked || []);
        let seeded = false;
        knownUnlocks.forEach(k => { if (!everSet.has(k)) { everSet.add(k); seeded = true; } });
        if (seeded) { state.everUnlocked = Array.from(everSet); save(); }

        hooksOk = installHooks();
        updateStatus();

        setInterval(() => {
            if (hooksOk) { renderList(); return; }
            try { afterTick(); } catch (e) { }
        }, FALLBACK_POLL_MS);

        console.log('[Hitos] listo · hooks:', hooksOk);
    }

    boot();
})();
