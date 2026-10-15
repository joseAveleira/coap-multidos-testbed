"use strict";
const {test} = require("node:test");
const assert = require("node:assert/strict");
const {EventEmitter} = require("node:events");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const {makePlan, validate, localAddress, LABELS} = require("../actor/plan");
const {MidPool, Channel, preflight} = require("../actor/transport");
const {run, sha256} = require("../actor/runner");
const {parse} = require("../actor_coap");
const {encode, uint} = require("../servidor/coap");
const {createServer} = require("../servidor/server");

test("plans reproduce seeds, balance both attacks and cover the full session", () => {
  assert.deepEqual(makePlan({seed: 42}), makePlan({seed: 42}));
  assert.notDeepEqual(makePlan({seed: 42}), makePlan({seed: 43}));
  for (let seed = 0; seed < 100; seed++) {
    const plan = makePlan({seed, duration: [600, 900, 1200][seed % 3]});
    validate(plan);
    for (const kind of ["block2_amplification", "request_flood", "benign_sensor_burst"])
      assert.equal(plan.phases.filter(phase => phase.kind === kind).length, 6);
    assert.equal(plan.phases.filter(phase => phase.kind === "benign_block2_download").length, 3);
    assert.equal(plan.phases.filter(phase => phase.kind === "benign_block2_reads").length, 3);
    for (let i = 1; i < plan.phases.length; i++)
      assert.ok(Math.abs(plan.phases[i].start_s - plan.phases[i - 1].start_s - plan.phases[i - 1].duration_s) < 1e-6);
  }
});
test("invalid labels, gaps, overloaded plans and ambiguous NON tokens are rejected", () => {
  function reject(change) { const plan = makePlan(); change(plan); assert.throws(() => validate(plan)); }
  reject(plan => { plan.phases[0].label = "request_flood"; });
  reject(plan => { plan.phases[0].id = undefined; });
  reject(plan => { plan.phases[0].rate_rps = 1001; });
  reject(plan => { plan.phases[1].start_s += 1; });
  reject(plan => { plan.phases[1].duration_s = .1; });
  reject(plan => { plan.phases[0].message_type = "NON"; plan.phases[0].token_policy = "episode"; });
  assert.throws(() => makePlan({duration: 68, pairs: 6}));
  assert.throws(() => makePlan({scale: 2}));
});
test("the actor accepts one explicit private endpoint and rejects ambiguous CLI options", () => {
  for (const ip of ["10.37.225.138", "192.168.1.2", "172.16.1.2", "127.0.0.1"]) assert.equal(localAddress(ip), ip);
  for (const ip of ["8.8.8.8", "0.0.0.0", "239.1.2.3", "10.0.0.255", "example.com", "10.0.0.1/24", undefined])
    assert.throws(() => localAddress(ip));
  assert.throws(() => parse(["run", "--unknown", "1"]));
  assert.throws(() => parse(["plan", "--seed", "1", "--seed", "2"]));
});
test("MID wrap cannot reuse a value before 247 seconds", () => {
  const pool = new MidPool(0);
  for (let i = 0; i < 65536; i++) assert.equal(pool.take(0), i);
  assert.equal(pool.take(246999), null);
  assert.equal(pool.take(247000), 0);
});
function fakeChannel() {
  const socket = new EventEmitter(), events = []; socket.send = (packet, cb) => cb();
  socket.close = cb => cb(); let now = 0;
  const channel = new Channel({server: "127.0.0.1", socket, now: () => now, timeoutMs: 100, emit: e => events.push(e)});
  return {channel, events, setNow: value => { now = value; }};
}
const sensor = {id: "sensor", kind: "baseline", label: "benign", message_type: "CON", block_size: 1024};
test("ACK matching checks peer, MID and token; timeout is distinct from a send error", () => {
  const {channel, setNow} = fakeChannel(); let result;
  const q = channel.send({phase: sensor, onResult: value => { result = value; }});
  const good = encode({type: 2, code: 69, mid: q.mid, token: q.token, payload: Buffer.from("ok")});
  channel.receive(good, {address: "127.0.0.2", port: 5683}); assert.equal(channel.pending.size, 1);
  channel.receive(encode({type: 2, code: 69, mid: q.mid, token: Buffer.from([9])}), {address: "127.0.0.1", port: 5683});
  assert.equal(channel.pending.size, 1);
  channel.receive(good, {address: "127.0.0.1", port: 5683}); assert.equal(result.ok, true);
  const q2 = channel.send({phase: sensor, onResult: value => { result = value; }});
  setNow(101); channel.expire(); assert.equal(result.reason, "timeout");
  assert.equal(channel.counts.timeouts, 1); assert.equal(channel.counts.send_errors, 0);
  assert.ok(q2); channel.close();
});
test("NON responses use token correlation even with another MID", () => {
  const {channel} = fakeChannel(); let result;
  const q = channel.send({phase: {...sensor, message_type: "NON"}, onResult: value => { result = value; }});
  channel.receive(encode({type: 1, code: 69, mid: (q.mid + 7) & 65535, token: q.token}), {address: "127.0.0.1", port: 5683});
  assert.equal(result.ok, true); assert.equal(channel.pending.size, 0); channel.close();
});
test("wrong Block2 metadata is recorded as an error, not a valid response", () => {
  const {channel} = fakeChannel(); let result;
  const q = channel.send({phase: sensor, block: 0, onResult: value => { result = value; }});
  channel.receive(encode({type: 2, code: 69, mid: q.mid, token: q.token, payload: Buffer.alloc(1024),
    options: [{number: 4, value: Buffer.from([1])}, {number: 23, value: uint(6)}, {number: 28, value: uint(32768)}]}),
  {address: "127.0.0.1", port: 5683});
  assert.equal(result.reason, "block2_metadata"); assert.equal(channel.counts.valid_responses, 0); channel.close();
});

function shortPlan(long = false) {
  const phases = []; let start = 0;
  for (const [kind, type, length, rate] of [
    ["benign_block2_download", "CON", 1, 150], ["block2_amplification", "CON", .4, 30],
    ["request_flood", "NON", long ? 20 : .4, 30], ["benign_sensor_burst", "NON", .4, 30]]) {
    phases.push({id: `phase_${phases.length}`, kind, label: LABELS[kind], start_s: start, duration_s: length,
      rate_rps: rate, message_type: type, token_policy: kind === "benign_block2_download" ? "transfer" : type === "CON" ? "episode" : "unique",
      block_size: 1024, block_order: "sequential", fixed_block: 0});
    start += length;
    phases.push({id: `guard_${phases.length}`, kind: "guard", label: "excluded", start_s: start, duration_s: .2, rate_rps: 0});
    start += .2;
  }
  return {schema: 1, seed: 9, duration_s: start, lanes: 1, response_timeout_ms: 150, phases};
}
function temporary() {
  const base = path.resolve(os.tmpdir()), directory = fs.mkdtempSync(path.join(base, "coap-actor-test-"));
  return {directory, cleanup() {
    const target = path.resolve(directory);
    assert.equal(path.dirname(target), base); assert.ok(path.basename(target).startsWith("coap-actor-test-"));
    fs.rmSync(target, {recursive: true});
  }};
}
const udp = process.env.COAP_ACTOR_TEST_UDP === "1";
test("real UDP: preflight, both attacks, complete downloads, logs and hashes", {skip: !udp}, async () => {
  const server = createServer({host: "127.0.0.1", port: 0}), temp = temporary();
  try {
    const {port} = await server.start();
    const result = await run({plan: shortPlan(), server: "127.0.0.1", port, output: temp.directory, session: "run", startDelay: 0});
    assert.equal(result.summary.status, "completed", result.summary.reason);
    assert.equal(result.summary.log_dropped_records, 0);
    for (const phase of result.summary.phases.filter(p => p.kind !== "guard")) {
      assert.ok(phase.queued > 0); assert.equal(phase.valid_responses, phase.queued);
      assert.equal(phase.timeouts, 0); assert.equal(phase.send_errors, 0);
    }
    assert.ok(result.summary.phases[0].downloads_verified >= 1);
    const hashes = JSON.parse(fs.readFileSync(path.join(result.directory, "sha256.json")));
    for (const [file, hash] of Object.entries(hashes)) assert.equal(sha256(fs.readFileSync(path.join(result.directory, file))), hash);
    const lines = fs.readFileSync(path.join(result.directory, "traffic.jsonl"), "utf8").trim().split("\n").map(JSON.parse);
    const events = fs.readFileSync(path.join(result.directory, "events.jsonl"), "utf8").trim().split("\n").map(JSON.parse);
    for (const kind of ["phase_start", "phase_end", "phase_final"])
      assert.equal(events.filter(event => event.kind === kind).length, shortPlan().phases.length);
    assert.deepEqual(events.filter(event => event.kind === "phase_final").map(event => event.workload), shortPlan().phases.map(phase => phase.kind));
    assert.equal(lines.filter(e => e.kind === "tx").length, lines.filter(e => e.kind === "rx").length);
    for (const event of lines.filter(e => e.kind === "tx")) {
      assert.equal(event.token.length, 8); // Four bytes, as on the ESP32 clients.
      if (event.phase_id === "preflight") continue;
      const phase = result.summary.phases.find(p => p.phase_id === event.phase_id);
      assert.ok(event.epoch >= phase.scheduled_start_epoch);
      assert.ok(event.epoch < phase.scheduled_end_epoch);
      assert.notEqual(phase.kind, "guard");
      assert.ok(phase.queued <= Math.ceil((phase.scheduled_end_epoch - phase.scheduled_start_epoch) * phase.target_rate_rps) + 1);
    }
    assert.equal(server.counts.mid_collisions, 0);
    const manifest = JSON.parse(fs.readFileSync(path.join(result.directory, "manifest.json")));
    assert.equal(manifest.server, "127.0.0.1");
    await assert.rejects(() => run({plan: shortPlan(), server: "127.0.0.1", port, output: temp.directory, session: "run", startDelay: 0}), /exist/i);
  } finally { await server.close(); temp.cleanup(); }
});
test("real UDP: interrupt closes sockets and persists an interrupted session", {skip: !udp}, async () => {
  const server = createServer({host: "127.0.0.1", port: 0}), temp = temporary(), controller = new AbortController();
  let timer;
  try {
    const {port} = await server.start();
    const result = await run({plan: shortPlan(true), server: "127.0.0.1", port, output: temp.directory,
      session: "interrupted", startDelay: 0, signal: controller.signal,
      onProgress: message => { if (message.includes(": request_flood,")) timer = setTimeout(() => controller.abort(), 80); }});
    assert.equal(result.summary.status, "interrupted");
    assert.equal(result.summary.reason, "interrupted");
    assert.ok(fs.existsSync(path.join(result.directory, "summary.json")));
  } finally { clearTimeout(timer); await server.close(); temp.cleanup(); }
});
test("real UDP: failed resource verification prevents all campaign phases", {skip: !udp}, async () => {
  const server = createServer({host: "127.0.0.1", port: 0}), temp = temporary();
  server.resource.fill(0);
  try {
    const {port} = await server.start();
    const result = await run({plan: shortPlan(), server: "127.0.0.1", port, output: temp.directory,
      session: "failed_preflight", startDelay: 0});
    assert.equal(result.summary.status, "failed"); assert.equal(result.summary.phases.length, 0);
    const lines = fs.readFileSync(path.join(result.directory, "traffic.jsonl"), "utf8").trim().split("\n").map(JSON.parse);
    assert.ok(lines.filter(e => e.kind === "tx").every(e => e.phase_id === "preflight"));
  } finally { await server.close(); temp.cleanup(); }
});
