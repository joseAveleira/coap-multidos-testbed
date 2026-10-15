"use strict";
const {test, before, after} = require("node:test");
const assert = require("node:assert/strict");
const dgram = require("node:dgram");
const {createServer} = require("../servidor/server");
const {encode, decode, uint, uri, optionUInt} = require("../servidor/coap");
// Same request/response tests can run without opening sockets in a sandbox.
// This exercises packet handling, not the OS UDP stack or physical network.
const memory = process.env.COAP_TEST_IN_MEMORY === "1";
const {EventEmitter} = require("node:events");
let lastResponse;
function memorySocket() {
  const s = new EventEmitter();
  s.bind = (port, host, cb) => queueMicrotask(cb);
  s.address = () => ({address: "127.0.0.1", port: 5683});
  s.close = cb => { if (cb) cb(); };
  s.send = (packet, port, host, cb) => { lastResponse = decode(packet); if (cb) cb(); };
  return s;
}
let server, port, client, mid = 10;
before(async () => {
  server = createServer({host: "127.0.0.1", port: 0, seed: 2026,
    ...(memory ? {socketFactory: memorySocket} : {})});
  port = (await server.start()).port;
  if (memory) return;
  client = dgram.createSocket("udp4");
  await new Promise(resolve => client.bind(0, "127.0.0.1", resolve));
});
after(async () => { client?.close(); if (server) await server.close(); });
function exchange(packet) {
  if (memory) {
    lastResponse = undefined;
    server.socket.emit("message", packet, {address: "127.0.0.1", port: 56831});
    return lastResponse ? Promise.resolve(lastResponse) : Promise.reject(Error("No response"));
  }
  return new Promise((resolve, reject) => {
    const onMessage = b => { clearTimeout(timer); resolve(decode(b)); };
    const timer = setTimeout(() => { client.off("message", onMessage); reject(Error("Response timeout")); }, 1500);
    client.once("message", onMessage);
    client.send(packet, port, "127.0.0.1", err => {
      if (err) { clearTimeout(timer); client.off("message", onMessage); reject(err); }
    });
  });
}
function get(path, {type = 0, block, id = ++mid, code = 1, extra = []} = {}) {
  const options = path.split("/").map(part => ({number: 11, value: Buffer.from(part)}));
  if (block !== undefined) options.push({number: 23, value: uint(block)});
  return encode({type, code, mid: id, token: Buffer.from("01020304", "hex"), options: [...options, ...extra]});
}
test("CON receives an ACK, matching MID/token and a synthetic value", async () => {
  const q = get("sensor"), r = await exchange(q);
  assert.equal(r.type, 2); assert.equal(r.code, 69); assert.equal(r.mid, decode(q).mid);
  assert.deepEqual(r.token, decode(q).token); assert.match(r.payload.toString(), /^temperature=\d+\.\d$/);
});
test("NON gets a NON response and token correlation", async () => {
  const r = await exchange(get("sensor", {type: 1})); assert.equal(r.type, 1); assert.equal(r.code, 69);
});
test("whole Block2 download: all 32 blocks, M bit, ETag, Size2 and byte content", async () => {
  const blocks = []; let etag;
  for (let n = 0; n < 32; n++) {
    const r = await exchange(get("large", {block: (n << 4) | 6}));
    assert.equal(r.code, 69); assert.equal(r.payload.length, 1024);
    assert.equal(optionUInt(r, 23), (n << 4) | (n < 31 ? 8 : 0) | 6);
    assert.equal(optionUInt(r, 28), 32768);
    const e = r.options.find(o => o.number === 4).value;
    if (etag) assert.deepEqual(e, etag); etag = e; blocks.push(r.payload);
  }
  assert.deepEqual(Buffer.concat(blocks), server.resource);
});
test("all legal Block2 sizes work, with a correct final block", async () => {
  for (let szx = 0; szx <= 6; szx++) {
    const size = 1 << (szx + 4), n = 32768 / size - 1;
    const r = await exchange(get("large", {block: (n << 4) | szx}));
    assert.equal(r.payload.length, size); assert.equal(optionUInt(r, 23), (n << 4) | szx);
    assert.deepEqual(r.payload, server.resource.subarray(32768 - size));
  }
});
test("CON retransmission is deduplicated, MID collision is reset", async () => {
  const packet = get("sensor"); const first = await exchange(packet);
  const before = server.counts.sensor; const second = await exchange(packet);
  assert.deepEqual(second, first); assert.equal(server.counts.sensor, before);
  const collision = await exchange(get("large", {id: decode(packet).mid}));
  assert.equal(collision.type, 3); assert.equal(collision.code, 0);
});
test("bad paths, unsupported methods and invalid Block2 values return errors", async () => {
  assert.equal((await exchange(get("missing"))).code, 132);
  assert.equal((await exchange(get("sensor", {code: 2}))).code, 133);
  assert.equal((await exchange(get("large", {block: 7}))).code, 130);
  assert.equal((await exchange(get("large", {block: 14}))).code, 130);
  assert.equal((await exchange(get("large", {block: (32 << 4) | 6}))).code, 128);
  assert.equal((await exchange(get("large", {extra: [{number: 23, value: Buffer.from([0, 0, 0, 6])}]}))).code, 130);
  assert.equal((await exchange(get("sensor", {extra: [{number: 9, value: Buffer.alloc(0)}]}))).code, 130);
});
test("discovery and malformed datagrams do not break the server", async () => {
  const r = await exchange(get(".well-known/core")); assert.equal(r.code, 69);
  assert.match(r.payload.toString(), /<\/large>/);
  const bad = Buffer.from([0x49, 1, 0, 0]);
  if (memory) server.socket.emit("message", bad, {address: "127.0.0.1", port: 56831});
  else client.send(bad, port, "127.0.0.1");
  assert.equal((await exchange(get("sensor"))).code, 69);
  assert.ok(server.counts.malformed > 0);
});
test("codec rejects truncated/reserved options and invalid payload markers", () => {
  for (const hex of ["", "49010000", "4401000001", "40010000d0", "40010000f0", "40010000b561", "40010000ff", "4100000001"]) {
    assert.throws(() => decode(Buffer.from(hex, "hex")), hex);
  }
  assert.equal(uri(decode(get(".well-known/core"))), ".well-known/core");
  assert.deepEqual(uint(0), Buffer.alloc(0));
});
