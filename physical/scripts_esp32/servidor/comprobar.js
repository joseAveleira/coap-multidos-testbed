#!/usr/bin/env node
"use strict";
// Benign smoke check: one sensor read and one complete configuration download.
const dgram = require("node:dgram");
const crypto = require("node:crypto");
const {isIPv4} = require("node:net");
const {encode, decode, uint, optionUInt} = require("./coap");
async function main() {
  const host = process.argv[2], port = Number(process.argv[3] || 5683);
  if (!isIPv4(host || "") || !Number.isInteger(port) || port < 1 || port > 65535)
    throw Error("Uso: node servidor/comprobar.js IP_DEL_SERVIDOR [5683]");
  const socket = dgram.createSocket("udp4");
  let mid = crypto.randomInt(65536);
  async function get(route, block) {
    const token = crypto.randomBytes(4), id = mid = (mid + 1) & 65535;
    const options = [{number: 11, value: Buffer.from(route)}];
    if (block !== undefined) options.push({number: 23, value: uint((block << 4) | 6)});
    return new Promise((resolve, reject) => {
      let timer;
      function cleanup() { clearTimeout(timer); socket.off("message", receive); socket.off("error", error); }
      function error(err) { cleanup(); reject(err); }
      function receive(bytes, remote) {
        if (remote.address !== host || remote.port !== port) return;
        let m; try { m = decode(bytes); } catch { return; }
        if (!m.token.equals(token) || m.mid !== id || m.type !== 2) return;
        cleanup(); if (m.code !== 69) reject(Error(`CoAP response code ${m.code}`)); else resolve(m);
      }
      socket.on("message", receive); socket.once("error", error);
      timer = setTimeout(() => error(Error("No response within 3 seconds; check IP, server and firewall")), 3000);
      socket.send(encode({type: 0, code: 1, mid: id, token, options}), port, host, err => { if (err) error(err); });
    });
  }
  try {
    console.log("/sensor:", (await get("sensor")).payload.toString());
    const chunks = []; let etag;
    for (let n = 0; n < 32; n++) {
      const m = await get("large", n);
      if (optionUInt(m, 23) !== ((n << 4) | (n < 31 ? 8 : 0) | 6) ||
          optionUInt(m, 28) !== 32768 || m.payload.length !== 1024) throw Error(`Invalid Block2 response ${n}`);
      const e = m.options.find(o => o.number === 4)?.value;
      if (!e || (etag && !etag.equals(e))) throw Error("Resource ETag changed");
      etag = e; chunks.push(m.payload);
      await new Promise(resolve => setTimeout(resolve, 20));
    }
    const resource = Buffer.concat(chunks), first = resource[0] - 65;
    if (first < 0 || first > 25 || resource.some((b, i) => b !== 65 + (first + i) % 26)) throw Error("Unexpected configuration data");
    console.log("/large: 32768 bytes, 32 blocks verified; SHA256", crypto.createHash("sha256").update(resource).digest("hex"));
  } finally { try { socket.close(); } catch { /* Socket creation/binding failed. */ } }
}
main().catch(err => { console.error(err.message); process.exitCode = 1; });
