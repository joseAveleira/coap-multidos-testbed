#!/usr/bin/env node
"use strict";
const fs = require("node:fs");
const path = require("node:path");
const {VERSION, makePlan, validate, localAddress} = require("./actor/plan");
const {Channel, preflight} = require("./actor/transport");
const {run, sha256} = require("./actor/runner");

const HELP = `Actor CoAP de laboratorio ${VERSION} — Node.js 22+, sin npm

Desde la carpeta que contiene actor_coap.js:
  node actor_coap.js plan --out plan.json --seed 2026 --duration 900 --pairs 6
  node actor_coap.js campaign --out planes --sessions 12 --seed 2026
  node actor_coap.js inspect --plan plan.json
  node actor_coap.js check --server IP_DEL_SERVIDOR
  node actor_coap.js run --server IP_DEL_SERVIDOR --plan plan.json --session fisica_001

plan/campaign/inspect no abren sockets. run requiere un plan explícito y un
destino privado individual. Capture en el servidor antes de ejecutar run.

Opciones:
  plan:     --out FILE [--seed 2026] [--duration 900] [--pairs 6] [--scale 1]
  campaign: --out DIR [--sessions 12] [--seed 2026] [--duration SECONDS]
            [--pairs 6] [--scale 1]
            Sin duration, alterna sesiones de 600, 900 y 1200 segundos.
  inspect:  --plan FILE
  check:    --server IP [--port 5683]
  run:      --server IP --plan FILE --session NAME [--output registros_actor]
            [--port 5683] [--start-delay 10 | --start-at ISO_CON_ZONA]
            [--clock-note TEXTO]

Ctrl+C detiene los envíos y conserva registros y resumen como interrupted.
Guía: actor/README.md (README.md en el paquete portátil).
`;
function parse(argv) {
  const command = argv.shift();
  if (!command || command === "--help" || command === "help") return {command: "help", options: {}};
  const allowed = {
    plan: ["out", "seed", "duration", "pairs", "scale"],
    campaign: ["out", "sessions", "seed", "duration", "pairs", "scale"], inspect: ["plan"],
    check: ["server", "port"],
    run: ["server", "port", "plan", "session", "output", "start-delay", "start-at", "clock-note"],
  }[command];
  if (!allowed) throw Error(`Comando desconocido: ${command}`);
  const options = {};
  for (let i = 0; i < argv.length; i += 2) {
    const key = argv[i].replace(/^--/, "");
    if (argv[i] !== `--${key}` || !allowed.includes(key) || key in options || argv[i + 1] === undefined)
      throw Error(`Opción inválida o repetida: ${argv[i]}`);
    const value = argv[i + 1];
    options[key] = ["seed", "duration", "pairs", "scale", "sessions", "port", "start-delay"].includes(key) ? Number(value) : value;
    if (typeof options[key] === "number" && !Number.isFinite(options[key])) throw Error(`Valor numérico inválido: ${key}`);
  }
  return {command, options};
}
function save(file, value) {
  fs.mkdirSync(path.dirname(path.resolve(file)), {recursive: true});
  fs.writeFileSync(file, JSON.stringify(value, null, 2) + "\n", {flag: "wx"});
}
function describe(plan) {
  const counts = {}, seconds = {};
  for (const phase of plan.phases) {
    counts[phase.kind] = (counts[phase.kind] || 0) + 1;
    seconds[phase.label] = (seconds[phase.label] || 0) + phase.duration_s;
  }
  return {seed: plan.seed, duration_s: plan.duration_s, lanes: plan.lanes,
    ...validate(plan), episodes_by_kind: counts, scheduled_seconds_by_label: seconds,
    plan_sha256: sha256(JSON.stringify(plan))};
}
async function main(argv) {
  if (Number(process.versions.node.split(".")[0]) < 22) throw Error("Se necesita Node.js 22 o posterior.");
  const {command, options: o} = parse(argv);
  if (command === "help") { console.log(HELP); return; }
  if (command === "plan") {
    if (!o.out) throw Error("Falta --out.");
    const plan = makePlan(o); save(o.out, plan);
    console.log(JSON.stringify({file: path.resolve(o.out), ...describe(plan)}, null, 2)); return;
  }
  if (command === "campaign") {
    if (!o.out) throw Error("Falta --out.");
    const count = o.sessions ?? 12, seed = o.seed ?? 2026;
    if (!Number.isInteger(count) || count < 1 || count > 100 || !Number.isInteger(seed) || seed < 0 || seed + count - 1 > 0xffffffff)
      throw Error("sessions debe estar entre 1 y 100 y las semillas dentro de uint32.");
    const plans = Array.from({length: count}, (_, i) => makePlan({...o, seed: seed + i, duration: o.duration ?? [600, 900, 1200][i % 3]}));
    fs.mkdirSync(path.dirname(path.resolve(o.out)), {recursive: true}); fs.mkdirSync(o.out);
    const sessions = plans.map((plan, i) => {
      const name = `fisica_${String(i + 1).padStart(3, "0")}`;
      save(path.join(o.out, `${name}.json`), plan);
      return {session: name, file: `${name}.json`, ...describe(plan)};
    });
    save(path.join(o.out, "campaign.json"), {schema: 1, actor_version: VERSION, sessions,
      note: "Propuesta editable: el número de sesiones no garantiza por sí solo suficiencia científica."});
    console.log(`Creados ${count} planes en ${path.resolve(o.out)}. No se ha enviado tráfico.`); return;
  }
  if (command === "inspect") {
    if (!o.plan) throw Error("Falta --plan.");
    console.log(JSON.stringify(describe(JSON.parse(fs.readFileSync(o.plan, "utf8"))), null, 2)); return;
  }
  localAddress(o.server);
  const port = o.port ?? 5683;
  if (!Number.isInteger(port) || port < 1 || port > 65535) throw Error("Puerto inválido.");
  if (command === "check") {
    let socketError;
    const channel = new Channel({server: o.server, port, onFatal: error => { socketError = error; }});
    try {
      await channel.open(); const result = await preflight(channel);
      if (socketError) throw socketError;
      console.log(JSON.stringify({status: "ok", server: o.server, port, local: channel.endpoint,
        sensor: result.sensor, resource_bytes: result.resource.length, resource_sha256: result.sha256, counts: channel.snapshot()}, null, 2));
    } finally { await channel.close(); }
    return;
  }
  if (!o.plan) throw Error("Falta --plan. Primero genera y revisa un plan.");
  if (o["start-at"] && o["start-delay"] !== undefined) throw Error("Usa start-at o start-delay, no ambos.");
  const plan = JSON.parse(fs.readFileSync(o.plan, "utf8"));
  const result = await run({plan, server: o.server, port, session: o.session, output: o.output,
    startAt: o["start-at"], startDelay: o["start-delay"] ?? 10, clockNote: o["clock-note"] ?? "not_verified",
    onProgress: message => console.log(message)});
  if (result.error) console.error(result.error.message);
  if (result.summary.status !== "completed") process.exitCode = result.summary.status === "interrupted" ? 130 : 1;
}
if (require.main === module) main(process.argv.slice(2)).catch(error => { console.error(error.message); process.exitCode = 1; });
module.exports = {main, parse, describe};
