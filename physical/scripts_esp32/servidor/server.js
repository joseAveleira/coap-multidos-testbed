#!/usr/bin/env node
"use strict";
const dgram = require("node:dgram");
const fs = require("node:fs");
const path = require("node:path");
const crypto = require("node:crypto");
const {performance} = require("node:perf_hooks");
const {encode, decode, uint, optionUInt, uri} = require("./coap");

function createServer({host = "0.0.0.0", port = 5683, seed = 2026, log = () => {},
  socketFactory = () => dgram.createSocket("udp4")} = {}) {
  const socket = socketFactory();
  let bound = false;
  const started = performance.now();
  const resource = Buffer.from(Array.from({length: 32768}, (_, i) => 65 + ((i + seed) % 26)));
  const etag = crypto.createHash("sha256").update(resource).digest().subarray(0, 4);
  // CON duplicates retain the same response for EXCHANGE_LIFETIME (247 s).
  // Bounded memory; evictions are explicitly counted in the experiment logs.
  const cache = new Map(), cacheLimit = 20000;
  let responseMid = crypto.randomInt(65536);
  const counts = {rx: 0, tx: 0, rx_bytes: 0, tx_bytes: 0, malformed: 0,
    duplicates: 0, mid_collisions: 0, cache_evictions: 0, send_errors: 0, sensor: 0, large: 0, errors: 0};
  function send(packet, remote) {
    socket.send(packet, remote.port, remote.address, err => {
      if (err) { counts.send_errors++; return; }
      counts.tx++; counts.tx_bytes += packet.length;
    });
  }
  socket.on("message", (packet, remote) => {
    counts.rx++; counts.rx_bytes += packet.length;
    let q;
    try { q = decode(packet); } catch { counts.malformed++; return; }
    if (q.type > 1) return; // ACK/RST are never requests.
    if (!q.code) {
      if (!q.type) send(encode({type: 3, code: 0, mid: q.mid}), remote);
      return;
    }
    if (q.code >= 32) return;
    const key = `${remote.address}:${remote.port}:${q.mid}`;
    const now = performance.now(), previous = cache.get(key);
    if (previous && previous.until > now) {
      if (previous.request.equals(packet)) { counts.duplicates++; send(previous.response, remote); }
      else { counts.mid_collisions++; send(encode({type: 3, code: 0, mid: q.mid}), remote); }
      return;
    }
    if (previous) cache.delete(key);
    let code = 69, options = [], payload = Buffer.alloc(0);
    const route = uri(q);
    try {
      if (q.code !== 1) code = 133; // 4.05 Method Not Allowed
      else if (q.options.some(o => (o.number & 1) && ![11, 23].includes(o.number))) code = 130;
      else if (q.payload.length) code = 128;
      else if (route === "sensor") {
        counts.sensor++;
        // Process value emulated at the central service; NOT a real sensor reading.
        const tick = Math.floor((now - started) / 1000);
        payload = Buffer.from(`temperature=${20 + seed % 7}.${(tick + seed) % 10}`);
        options = [{number: 12, value: uint(0)}, {number: 14, value: uint(0)}];
      } else if (route === "large") {
        counts.large++;
        const block = optionUInt(q, 23, 6), szx = block & 7, number = block >>> 4;
        const raw = q.options.find(o => o.number === 23);
        if ((raw && raw.value.length > 3) || szx > 6 || (block & 8)) code = 130;
        else {
          const size = 1 << (szx + 4), offset = number * size;
          if (offset >= resource.length) code = 128;
          else {
            payload = resource.subarray(offset, offset + size);
            const more = offset + size < resource.length ? 8 : 0;
            options = [{number: 4, value: etag}, {number: 12, value: uint(42)},
              {number: 23, value: uint((number << 4) | more | szx)}, {number: 28, value: uint(resource.length)}];
          }
        }
      } else if (route === ".well-known/core") {
        payload = Buffer.from('</sensor>;rt="process-value",</large>;rt="configuration";sz=32768');
        options = [{number: 12, value: uint(40)}];
      } else code = 132;
    } catch { code = 130; options = []; payload = Buffer.alloc(0); }
    if (code >= 128) counts.errors++;
    const response = encode({type: q.type === 0 ? 2 : 1, code,
      mid: q.type === 0 ? q.mid : (responseMid = (responseMid + 1) & 65535), token: q.token, options, payload});
    if (q.type === 0) {
      if (cache.size >= cacheLimit) { cache.delete(cache.keys().next().value); counts.cache_evictions++; }
      cache.set(key, {until: now + 247000, request: Buffer.from(packet), response});
    }
    log({kind: "request", epoch: Date.now() / 1000, peer: remote.address, peer_port: remote.port,
      path: route, type: q.type, mid: q.mid, token: q.token.toString("hex"), code,
      request_bytes: packet.length, response_bytes: response.length});
    send(response, remote);
  });
  let purge;
  return {
    socket, counts, resource,
    async start() {
      await new Promise((resolve, reject) => {
        socket.once("error", reject);
        socket.bind(port, host, () => { socket.off("error", reject); bound = true; resolve(); });
      });
      purge = setInterval(() => {
        const now = performance.now();
        for (const [key, value] of cache) if (value.until <= now) cache.delete(key);
      }, 5000).unref();
      return socket.address();
    },
    async close() {
      clearInterval(purge);
      if (bound) { bound = false; await new Promise(resolve => socket.close(resolve)); }
      else { try { socket.close(); } catch { /* Bind never succeeded. */ } }
    },
  };
}

async function main(argv) {
  const args = {host: "0.0.0.0", port: 5683, seed: 2026, duration: 0,
    session: `physical_${new Date().toISOString().replace(/[:.]/g, "-")}`,
    output: path.join(__dirname, "registros"), requests: false, "control-stdin": false};
  for (let i = 0; i < argv.length; i++) {
    const key = argv[i].replace(/^--/, "");
    if (key === "help") {
      console.log("node server.js --host 0.0.0.0 --session fisica_001 --seed 2026 --duration 600 [--requests] [--output DIR] [--port 5683]"); return;
    }
    if (!(key in args) || argv[i] !== `--${key}`) throw Error(`Unknown option: ${argv[i]}`);
    if (key === "requests" || key === "control-stdin") { args[key] = true; continue; }
    if (i + 1 === argv.length) throw Error(`Missing value: ${key}`);
    args[key] = ["port", "seed", "duration"].includes(key) ? Number(argv[++i]) : argv[++i];
  }
  if (!/^[a-zA-Z0-9_-][a-zA-Z0-9_.-]*$/.test(args.session)) throw Error("Invalid session name");
  if (!Number.isInteger(args.port) || args.port < 1 || args.port > 65535) throw Error("Invalid port");
  if (!Number.isInteger(args.seed) || args.seed < 0 || args.seed > 0xffffffff) throw Error("Invalid seed");
  if (!Number.isFinite(args.duration) || args.duration < 0) throw Error("Invalid duration");
  fs.mkdirSync(args.output, {recursive: true});
  const directory = path.join(args.output, args.session);
  fs.mkdirSync(directory); // Refuse to overwrite an existing recording.
  fs.writeFileSync(path.join(directory, "manifest.json"), JSON.stringify({schema: 1, ...args,
    node_version: process.version, started_utc: new Date().toISOString(), resource_bytes: 32768,
    sensor_source: "synthetic process value", client_inventory: "recorded in the capture session manifest"}, null, 2) + "\n");
  const stream = fs.createWriteStream(path.join(directory, "server.jsonl"), {flags: "wx"});
  let droppedLogEntries = 0, stopped = false, timer, deadline;
  function log(event) {
    if (stream.writableLength > 1024 * 1024) { droppedLogEntries++; return; }
    stream.write(JSON.stringify(event) + "\n");
  }
  const server = createServer({...args, log: args.requests ? log : () => {}});
  stream.on("error", err => { console.error(`Log error: ${err.message}`); process.exitCode = 1; stop(); });
  let address;
  try { address = await server.start(); }
  catch (err) { await server.close(); stream.end(); throw err; }
  server.socket.on("error", err => { console.error(err); process.exitCode = 1; stop(); });
  const summary = () => ({kind: "counters", epoch: Date.now() / 1000,
    ...server.counts, dropped_log_entries: droppedLogEntries});
  timer = setInterval(() => log(summary()), 1000);
  async function stop() {
    if (stopped) return; stopped = true;
    clearInterval(timer); clearTimeout(deadline);
    if (args["control-stdin"]) process.stdin.destroy();
    await server.close();
    const result = summary();
    fs.writeFileSync(path.join(directory, "summary.json"), JSON.stringify(result, null, 2) + "\n");
    stream.end(JSON.stringify({...result, kind: "stop"}) + "\n");
    console.log(`Session saved: ${directory}`);
  }
  process.on("SIGINT", stop); process.on("SIGTERM", stop);
  if (args["control-stdin"]) {
    let input = "";
    process.stdin.setEncoding("utf8");
    process.stdin.on("data", chunk => {
      input += chunk;
      let newline;
      while ((newline = input.indexOf("\n")) >= 0) {
        const line = input.slice(0, newline).trim(); input = input.slice(newline + 1);
        if (line === "STOP") stop();
      }
      if (input.length > 1024) input = "";
    });
  }
  if (args.duration) deadline = setTimeout(stop, args.duration * 1000);
  log({kind: "start", epoch: Date.now() / 1000, ...address});
  console.log(`CoAP UDP ${address.address}:${address.port}; /sensor and /large (32768 bytes)`);
  console.log(`Records: ${directory}. Capture the server's physical interface separately.`);
}
if (require.main === module) main(process.argv.slice(2)).catch(err => { console.error(err.message); process.exitCode = 1; });
module.exports = {createServer};
