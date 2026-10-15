"use strict";

// Subconjunto CoAP/UDP del banco de pruebas: GET, CON/NON y Block2.
// No es una implementación completa de CoAP (no DTLS, Observe ni Block1).
function uint(value) {
  if (!Number.isInteger(value) || value < 0 || value > 0xffffffff) throw Error("Invalid uint");
  if (!value) return Buffer.alloc(0);
  const bytes = [];
  for (; value; value = Math.floor(value / 256)) bytes.unshift(value % 256);
  return Buffer.from(bytes);
}
function extended(n) {
  if (n < 0 || n > 65804) throw Error("Option out of range");
  if (n < 13) return [n, Buffer.alloc(0)];
  if (n < 269) return [13, Buffer.from([n - 13])];
  const b = Buffer.alloc(2); b.writeUInt16BE(n - 269); return [14, b];
}
function encode({type, code, mid, token = Buffer.alloc(0), options = [], payload = Buffer.alloc(0)}) {
  if (token.length > 8 || type < 0 || type > 3) throw Error("Invalid header");
  const h = Buffer.from([0x40 | (type << 4) | token.length, code, mid >>> 8, mid & 255]);
  const out = [h, token]; let previous = 0;
  for (const o of [...options].sort((a, b) => a.number - b.number)) {
    const value = Buffer.from(o.value);
    const [d, de] = extended(o.number - previous), [l, le] = extended(value.length);
    out.push(Buffer.from([(d << 4) | l]), de, le, value); previous = o.number;
  }
  if (payload.length) out.push(Buffer.from([255]), payload);
  return Buffer.concat(out);
}
function decode(b) {
  if (b.length < 4 || b[0] >>> 6 !== 1 || (b[0] & 15) > 8 || b.length < 4 + (b[0] & 15)) throw Error("Invalid header");
  const m = {type: (b[0] >>> 4) & 3, code: b[1], mid: b.readUInt16BE(2),
    token: b.subarray(4, 4 + (b[0] & 15)), options: [], payload: Buffer.alloc(0)};
  let at = 4 + m.token.length, number = 0;
  function read(n) {
    if (n < 13) return n;
    if (n === 15 || at + (n === 13 ? 1 : 2) > b.length) throw Error("Invalid option");
    if (n === 13) return 13 + b[at++];
    const v = 269 + b.readUInt16BE(at); at += 2; return v;
  }
  while (at < b.length) {
    const h = b[at++];
    if (h === 255) {
      if (at === b.length) throw Error("Empty payload marker");
      m.payload = b.subarray(at); break;
    }
    number += read(h >>> 4); const len = read(h & 15);
    if (number > 65535 || at + len > b.length) throw Error("Truncated option");
    m.options.push({number, value: b.subarray(at, at + len)}); at += len;
  }
  if (!m.code && (m.token.length || m.options.length || m.payload.length)) throw Error("Invalid empty message");
  return m;
}
function optionUInt(m, n, fallback) {
  const opts = m.options.filter(o => o.number === n);
  if (!opts.length) return fallback;
  if (opts.length !== 1 || opts[0].value.length > 4) throw Error("Invalid integer option");
  return [...opts[0].value].reduce((v, b) => v * 256 + b, 0);
}
function uri(m) { return m.options.filter(o => o.number === 11).map(o => o.value.toString()).join("/"); }
module.exports = {encode, decode, uint, optionUInt, uri};

