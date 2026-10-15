"use strict";
const dgram = require("node:dgram");
const crypto = require("node:crypto");
const {performance} = require("node:perf_hooks");
const {encode, decode, uint, optionUInt} = require("../servidor/coap");

class MidPool {
  constructor(first = crypto.randomInt(65536)) {
    this.next = first; this.last = new Float64Array(65536); this.last.fill(-Infinity);
  }
  take(now) {
    const id = this.next;
    if (now - this.last[id] < 247000) return null;
    this.last[id] = now; this.next = (id + 1) & 65535; return id;
  }
}

class Channel {
  constructor({server, port = 5683, lane = 0, timeoutMs = 3000, emit = () => {},
    now = () => performance.now(), socket = dgram.createSocket("udp4"), onFatal = () => {}}) {
    Object.assign(this, {server, port, lane, timeoutMs, emit, now, socket, onFatal});
    this.pool = new MidPool(); this.pending = new Map(); this.nonTokens = new Map();
    // Four-byte tokens match the physical clients. Leave enough room to avoid
    // wrap during the bounded campaign; wire IDs are independent of labels.
    this.tokenCounter = crypto.randomInt(0, 0xffffffff - 1000000); this.sequence = 0;
    this.counts = {queued: 0, sent: 0, send_errors: 0, responses: 0, valid_responses: 0,
      response_errors: 0, timeouts: 0, cancelled: 0, unmatched: 0, malformed: 0,
      rejected_peer: 0, mid_exhausted: 0, backpressure: 0, rx_bytes: 0, tx_bytes: 0};
    this.socket.on("message", (bytes, remote) => this.receive(bytes, remote));
  }
  async open() {
    await new Promise((resolve, reject) => {
      this.socket.once("error", reject);
      this.socket.bind(0, "0.0.0.0", () => this.socket.connect(this.port, this.server, () => {
        this.socket.off("error", reject); resolve();
      }));
    });
    this.socket.on("error", error => {
      this.emit({kind: "socket_error", lane: this.lane, error: error.message}); this.onFatal(error);
    });
    this.endpoint = this.socket.address();
    this.emit({kind: "flow", lane: this.lane, local: this.endpoint, remote: {address: this.server, port: this.port}});
  }
  token() {
    if (this.tokenCounter >= 0xffffffff) throw Error("Se agotó el contador de tokens.");
    const result = Buffer.alloc(4); result.writeUInt32BE(++this.tokenCounter); return result;
  }
  send({phase, block, token = this.token(), onResult = () => {}, onAccepted = () => {}, transfer = null}) {
    if (this.pending.size >= 512) { this.counts.backpressure++; return null; }
    const sentAt = this.now(), mid = this.pool.take(sentAt);
    if (mid === null) { this.counts.mid_exhausted++; return null; }
    if (phase.message_type === "NON" && this.nonTokens.has(token.toString("hex"))) throw Error("Token NON en uso.");
    const route = block === undefined ? "sensor" : "large";
    const options = [{number: 11, value: Buffer.from(route)}];
    if (block !== undefined) options.push({number: 23, value: uint((block << 4) | (Math.log2(phase.block_size) - 4))});
    const packet = encode({type: phase.message_type === "CON" ? 0 : 1, code: 1, mid, token, options});
    const request = {id: `${this.lane}:${++this.sequence}`, mid, token, phase, block, onResult, transfer,
      sentAt, deadline: sentAt + this.timeoutMs, length: packet.length};
    this.pending.set(mid, request);
    if (phase.message_type === "NON") this.nonTokens.set(token.toString("hex"), mid);
    this.counts.queued++;
    this.emit({kind: "tx", request_id: request.id, phase_id: phase.id, workload: phase.kind,
      label: phase.label, lane: this.lane, mid, token: token.toString("hex"), path: route,
      message_type: phase.message_type, block: block ?? null, block_size: block === undefined ? null : phase.block_size,
      transfer, bytes: packet.length});
    this.socket.send(packet, error => {
      if (error) {
        this.counts.send_errors++;
        this.emit({kind: "send_result", request_id: request.id, accepted_by_udp: false, error: error.message});
        if (this.pending.has(mid)) this.finish(request, {ok: false, reason: "send_error"});
      } else {
        this.counts.sent++; this.counts.tx_bytes += packet.length;
        this.emit({kind: "send_result", request_id: request.id, accepted_by_udp: true});
      }
      onAccepted(!error);
    });
    return request;
  }
  finish(request, result) {
    this.pending.delete(request.mid);
    if (request.phase.message_type === "NON") this.nonTokens.delete(request.token.toString("hex"));
    request.onResult({...result, request, elapsed_ms: this.now() - request.sentAt});
  }
  receive(bytes, remote) {
    if (remote.address !== this.server || remote.port !== this.port) { this.counts.rejected_peer++; return; }
    this.counts.rx_bytes += bytes.length;
    let response;
    try { response = decode(bytes); } catch {
      this.counts.malformed++; this.emit({kind: "malformed_response", lane: this.lane, bytes: bytes.length}); return;
    }
    let request = response.type === 2 || response.type === 3 ? this.pending.get(response.mid) :
      this.pending.get(this.nonTokens.get(response.token.toString("hex")));
    if (!request) {
      this.counts.unmatched++;
      this.emit({kind: "unmatched_response", lane: this.lane, mid: response.mid, token: response.token.toString("hex"), code: response.code});
      return;
    }
    if (response.type === 2 && response.code === 0) {
      this.emit({kind: "unsupported_separate_ack", request_id: request.id}); return;
    }
    const reset = response.type === 3 && response.code === 0;
    if (!reset && (!response.token.equals(request.token) ||
        response.type !== (request.phase.message_type === "CON" ? 2 : 1))) {
      this.counts.unmatched++; this.emit({kind: "mismatched_response", request_id: request.id}); return;
    }
    let reason = reset ? "reset" : response.code !== 69 ? "coap_error" : null;
    if (!reason && request.block !== undefined) {
      const size = request.phase.block_size, offset = request.block * size;
      try {
        const etag = response.options.find(option => option.number === 4)?.value;
        if (optionUInt(response, 23) !== ((request.block << 4) | (offset + size < 32768 ? 8 : 0) | (Math.log2(size) - 4)) ||
            optionUInt(response, 28) !== 32768 || response.payload.length !== size || !etag?.length)
          reason = "block2_metadata";
        else if (this.resource && !response.payload.equals(this.resource.subarray(offset, offset + size))) reason = "resource_content_changed";
        else if (this.etag && !etag.equals(this.etag)) reason = "etag_changed";
      } catch { reason = "block2_metadata"; }
    }
    this.counts.responses++;
    this.counts[reason ? "response_errors" : "valid_responses"]++;
    this.emit({kind: "rx", request_id: request.id, phase_id: request.phase.id, lane: this.lane,
      mid: response.mid, request_mid: request.mid, token: response.token.toString("hex"),
      code: response.code, bytes: bytes.length, payload_bytes: response.payload.length,
      elapsed_ms: this.now() - request.sentAt, valid: !reason, reason});
    this.finish(request, {ok: !reason, reason, response});
  }
  expire(now = this.now()) {
    for (const request of this.pending.values()) if (now >= request.deadline) {
      this.counts.timeouts++;
      this.emit({kind: "timeout", request_id: request.id, phase_id: request.phase.id, lane: this.lane,
        elapsed_ms: now - request.sentAt});
      this.finish(request, {ok: false, reason: "timeout"});
    }
  }
  async close() {
    for (const request of [...this.pending.values()]) {
      this.counts.cancelled++; this.emit({kind: "cancelled", request_id: request.id, phase_id: request.phase.id});
      this.finish(request, {ok: false, reason: "cancelled"});
    }
    await new Promise(resolve => { try { this.socket.close(resolve); } catch { resolve(); } });
  }
  snapshot() { return {...this.counts, pending: this.pending.size}; }
}

async function preflight(channel, shouldStop = () => false) {
  const phase = {id: "preflight", kind: "preflight", label: "excluded", message_type: "CON", block_size: 1024};
  async function get(block) {
    if (shouldStop()) throw Error("Comprobación interrumpida.");
    return new Promise((resolve, reject) => {
      const timer = setInterval(() => channel.expire(), 10);
      const request = channel.send({phase, block, onResult: result => {
        clearInterval(timer);
        if (result.ok) resolve(result.response); else reject(Error(`Comprobación CoAP: ${result.reason}`));
      }});
      if (!request) { clearInterval(timer); reject(Error("No se pudo enviar la comprobación.")); }
    });
  }
  const sensor = await get(undefined);
  if (!/^temperature=\d+\.\d$/.test(sensor.payload.toString())) throw Error("/sensor no coincide con el servidor del experimento.");
  let etag;
  const chunks = [];
  for (let n = 0; n < 32; n++) {
    const response = await get(n), current = response.options.find(option => option.number === 4).value;
    if (etag && !etag.equals(current)) throw Error("El ETag cambió durante la comprobación.");
    etag = current; chunks.push(response.payload);
  }
  const resource = Buffer.concat(chunks), first = resource[0] - 65;
  if (first < 0 || first > 25 || resource.some((b, i) => b !== 65 + (first + i) % 26))
    throw Error("/large no tiene el contenido esperado del servidor del experimento.");
  return {resource, etag, sensor: sensor.payload.toString(), sha256: crypto.createHash("sha256").update(resource).digest("hex")};
}
module.exports = {MidPool, Channel, preflight};
