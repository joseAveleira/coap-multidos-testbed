"use strict";
const {isIPv4} = require("node:net");

const VERSION = "1.0.0";
const LIMITS = Object.freeze({rate: 1000, seconds: 3600, packets: 600000, lanes: 4, timeoutMs: 3000, guardSeconds: 4});
const LABELS = Object.freeze({baseline: "benign", benign_sensor_burst: "benign",
  benign_block2_download: "benign", benign_block2_reads: "benign",
  block2_amplification: "block2_amplification", request_flood: "request_flood", guard: "excluded"});
function rng(seed) {
  let state = seed >>> 0;
  return () => {
    state = (state + 0x6d2b79f5) >>> 0;
    let n = Math.imul(state ^ (state >>> 15), 1 | state);
    n ^= n + Math.imul(n ^ (n >>> 7), 61 | n);
    return ((n ^ (n >>> 14)) >>> 0) / 4294967296;
  };
}
function localAddress(value) {
  if (!isIPv4(value)) throw Error("El servidor debe ser una IPv4 literal de la red de pruebas.");
  const [a, b, c, d] = value.split(".").map(Number);
  if (!(a === 10 || (a === 172 && b >= 16 && b <= 31) || (a === 192 && b === 168) || a === 127) || d === 255)
    throw Error("El actor admite un único destino privado RFC1918 o loopback, sin difusión.");
  return value;
}
function validate(plan) {
  if (!plan || plan.schema !== 1 || !Array.isArray(plan.phases) || !plan.phases.length)
    throw Error("Plan inválido: schema=1 y phases son obligatorios.");
  if (!Number.isInteger(plan.seed) || plan.seed < 0 || plan.seed > 0xffffffff) throw Error("Semilla inválida.");
  if (!Number.isFinite(plan.duration_s) || plan.duration_s <= 0 || plan.duration_s > LIMITS.seconds)
    throw Error(`La sesión debe durar como máximo ${LIMITS.seconds} s.`);
  if (!Number.isInteger(plan.lanes) || plan.lanes < 1 || plan.lanes > 8) throw Error("lanes debe estar entre 1 y 8.");
  if (!Number.isFinite(plan.response_timeout_ms) || plan.response_timeout_ms < 100 || plan.response_timeout_ms > 10000)
    throw Error("response_timeout_ms fuera de rango (100–10000).");
  let end = 0, budget = 0;
  const ids = new Set();
  for (const phase of plan.phases) {
    if (typeof phase.id !== "string" || !/^[a-zA-Z0-9_-]+$/.test(phase.id) || ids.has(phase.id)) throw Error("Identificador de fase inválido o repetido.");
    ids.add(phase.id);
    if (!(phase.kind in LABELS) || phase.label !== LABELS[phase.kind]) throw Error(`Etiqueta inconsistente: ${phase.id}`);
    if (!Number.isFinite(phase.start_s) || Math.abs(phase.start_s - end) > 1e-6 ||
        !Number.isFinite(phase.duration_s) || phase.duration_s <= 0) throw Error(`Hueco o solapamiento en ${phase.id}`);
    end = phase.start_s + phase.duration_s;
    if (phase.kind === "guard") {
      if (phase.rate_rps !== 0 || phase.duration_s * 1000 < plan.response_timeout_ms)
        throw Error("Cada guarda debe durar al menos el timeout de respuesta y tener tasa cero.");
      continue;
    }
    if (!Number.isFinite(phase.rate_rps) || phase.rate_rps <= 0 || phase.rate_rps > LIMITS.rate)
      throw Error(`Tasa inválida: máximo ${LIMITS.rate} peticiones/s.`);
    if (!["CON", "NON"].includes(phase.message_type)) throw Error("Tipo CoAP inválido.");
    if (!["unique", "episode", "transfer"].includes(phase.token_policy)) throw Error("Política de token inválida.");
    if (phase.message_type === "NON" && phase.token_policy !== "unique")
      throw Error("NON requiere tokens únicos para correlacionar respuestas concurrentes.");
    if (!Number.isInteger(phase.block_size) || ![16, 32, 64, 128, 256, 512, 1024].includes(phase.block_size))
      throw Error("Tamaño Block2 inválido.");
    if (!["sequential", "reverse", "random", "fixed"].includes(phase.block_order)) throw Error("Orden de bloques inválido.");
    if (!Number.isInteger(phase.fixed_block) || phase.fixed_block < 0 || phase.fixed_block >= 32768 / phase.block_size)
      throw Error("Número de bloque inválido.");
    if (phase.kind === "benign_block2_download" &&
        (phase.message_type !== "CON" || phase.token_policy !== "transfer" || phase.block_order !== "sequential"))
      throw Error("Las descargas usan CON, token por transferencia y orden secuencial.");
    if (phase.kind !== "benign_block2_download" && phase.token_policy === "transfer")
      throw Error("token_policy=transfer solo se usa en descargas completas.");
    budget += Math.ceil(phase.rate_rps * phase.duration_s);
  }
  if (Math.abs(end - plan.duration_s) > 1e-6 || budget > LIMITS.packets) throw Error("Duración o presupuesto de paquetes inválido.");
  for (let i = 0; i < plan.phases.length; i++) {
    const phase = plan.phases[i];
    if (phase.kind !== "guard" && plan.phases[i + 1]?.kind !== "guard")
      throw Error("Cada fase activa debe terminar con una guarda para recoger respuestas pendientes.");
  }
  return {scheduled_request_budget: budget};
}

function makePlan({seed = 2026, duration = 900, pairs = 6, scale = 1} = {}) {
  if (!Number.isInteger(seed) || seed < 0 || seed > 0xffffffff || !Number.isInteger(pairs) || pairs < 1 || pairs > 12 ||
      !Number.isFinite(scale) || scale <= 0 || scale > 1.5) throw Error("Parámetros: seed uint32, pairs 1–12, scale >0 y <=1.5.");
  const random = rng(seed), choose = values => values[Math.floor(random() * values.length)];
  const guard = LIMITS.guardSeconds, warmup = 20, slot = (duration - 2 * warmup) / (4 * pairs);
  if (!Number.isFinite(duration) || duration > LIMITS.seconds || slot < 18)
    throw Error(`Para ${pairs} pares hacen falta al menos ${40 + 72 * pairs} segundos.`);
  const special = [];
  for (let i = 0; i < pairs; i++) {
    for (const kind of ["block2_amplification", "request_flood", "benign_sensor_burst",
      i % 2 ? "benign_block2_reads" : "benign_block2_download"]) {
      const download = kind === "benign_block2_download", block = kind.includes("block2");
      const messageType = download ? "CON" : choose(["CON", "NON"]);
      special.push({kind, label: LABELS[kind],
        rate_rps: Math.round(choose(block ? [40, 100, 200, 350, 500] : [80, 180, 350, 500, 650]) * scale * 1000) / 1000,
        message_type: messageType, token_policy: download ? "transfer" :
          messageType === "CON" ? choose(["unique", "episode"]) : "unique",
        block_size: 1024, block_order: download ? "sequential" : choose(["sequential", "reverse", "random", "fixed"]),
        fixed_block: Math.floor(random() * 32)});
    }
  }
  for (let i = special.length - 1; i > 0; i--) {
    const j = Math.floor(random() * (i + 1)); [special[i], special[j]] = [special[j], special[i]];
  }
  const phases = [];
  let cursor = 0;
  function add(kind, seconds, params = {}) {
    if (seconds <= 1e-7) return;
    phases.push({id: `phase_${String(phases.length + 1).padStart(3, "0")}`, kind, label: LABELS[kind],
      start_s: cursor, duration_s: seconds, rate_rps: 0, ...params});
    cursor += seconds;
  }
  function baseline(until) {
    const seconds = until - cursor - guard;
    if (seconds > 1e-7) {
      add("baseline", seconds, {rate_rps: choose([1, 2, 3, 5]), message_type: "CON", token_policy: "unique",
        block_size: 1024, block_order: "sequential", fixed_block: 0});
      add("guard", guard);
    } else if (until - cursor > 1e-7) {
      // Extend an existing guard instead of inserting an undersized one.
      if (phases.at(-1)?.kind !== "guard") throw Error("No se puede construir la guarda.");
      phases.at(-1).duration_s += until - cursor; cursor = until;
    }
  }
  special.forEach((phase, index) => {
    const length = 6 + random() * (Math.min(30, slot - 12) - 6);
    const start = warmup + index * slot + random() * (slot - length - 2 * guard);
    baseline(start);
    add(phase.kind, length, phase);
    add("guard", guard);
  });
  baseline(duration);
  const plan = {schema: 1, generator_version: VERSION, seed, duration_s: duration,
    lanes: LIMITS.lanes, response_timeout_ms: LIMITS.timeoutMs,
    design: {pairs, scale, resource_bytes: 32768, block_bytes: 1024,
      purpose: "physical_campaign", labels: "externally_scheduled_workloads_not_proven_service_failure"}, phases};
  validate(plan);
  return plan;
}
module.exports = {VERSION, LIMITS, LABELS, rng, localAddress, validate, makePlan};
