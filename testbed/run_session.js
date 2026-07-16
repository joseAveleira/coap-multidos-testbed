#!/usr/bin/env node
"use strict";

// Dependency-free local CoAP/UDP testbed. It implements the subset of RFC 7252
// and Block2 needed to generate benign traffic and externally labelled events.

const dgram = require("node:dgram");
const fs = require("node:fs");
const path = require("node:path");

function parseArgs(argv) {
  const result = {};
  for (let i = 2; i < argv.length; i += 2) {
    const key = argv[i].replace(/^--/, "");
    result[key] = argv[i + 1];
  }
  return result;
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function mulberry32(seed) {
  return function random() {
    let t = (seed += 0x6d2b79f5);
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function uintOption(value) {
  if (value === 0) return Buffer.from([0]);
  const bytes = [];
  let remaining = value >>> 0;
  while (remaining > 0) {
    bytes.unshift(remaining & 0xff);
    remaining >>>= 8;
  }
  return Buffer.from(bytes);
}

function optionNibble(value) {
  if (value < 13) return { nibble: value, extra: Buffer.alloc(0) };
  if (value < 269) return { nibble: 13, extra: Buffer.from([value - 13]) };
  const extra = Buffer.alloc(2);
  extra.writeUInt16BE(value - 269);
  return { nibble: 14, extra };
}

function encodeOptions(options) {
  let previous = 0;
  const chunks = [];
  for (const option of [...options].sort((a, b) => a.number - b.number)) {
    const value = Buffer.isBuffer(option.value)
      ? option.value
      : Buffer.from(String(option.value), "utf8");
    const delta = optionNibble(option.number - previous);
    const length = optionNibble(value.length);
    chunks.push(
      Buffer.from([(delta.nibble << 4) | length.nibble]),
      delta.extra,
      length.extra,
      value,
    );
    previous = option.number;
  }
  return Buffer.concat(chunks);
}

function encodeCoap({ type, code, mid, token, options = [], payload = Buffer.alloc(0) }) {
  const header = Buffer.alloc(4);
  header[0] = 0x40 | ((type & 0x03) << 4) | token.length;
  header[1] = code;
  header.writeUInt16BE(mid & 0xffff, 2);
  const encodedOptions = encodeOptions(options);
  return payload.length
    ? Buffer.concat([header, token, encodedOptions, Buffer.from([0xff]), payload])
    : Buffer.concat([header, token, encodedOptions]);
}

function readExtended(nibble, buffer, offset) {
  if (nibble < 13) return { value: nibble, offset };
  if (nibble === 13) return { value: buffer[offset] + 13, offset: offset + 1 };
  if (nibble === 14) {
    return { value: buffer.readUInt16BE(offset) + 269, offset: offset + 2 };
  }
  throw new Error("Nibble de opción CoAP reservado");
}

function decodeCoap(buffer) {
  if (buffer.length < 4 || (buffer[0] >> 6) !== 1) throw new Error("CoAP no válido");
  const tokenLength = buffer[0] & 0x0f;
  const message = {
    type: (buffer[0] >> 4) & 0x03,
    code: buffer[1],
    mid: buffer.readUInt16BE(2),
    token: buffer.subarray(4, 4 + tokenLength),
    options: [],
    payload: Buffer.alloc(0),
  };
  let offset = 4 + tokenLength;
  let number = 0;
  while (offset < buffer.length) {
    if (buffer[offset] === 0xff) {
      message.payload = buffer.subarray(offset + 1);
      break;
    }
    const marker = buffer[offset++];
    const delta = readExtended(marker >> 4, buffer, offset);
    offset = delta.offset;
    const length = readExtended(marker & 0x0f, buffer, offset);
    offset = length.offset;
    number += delta.value;
    message.options.push({ number, value: buffer.subarray(offset, offset + length.value) });
    offset += length.value;
  }
  return message;
}

function optionUInt(message, number, fallback = 0) {
  const option = message.options.find((candidate) => candidate.number === number);
  if (!option) return fallback;
  let value = 0;
  for (const byte of option.value) value = (value << 8) | byte;
  return value >>> 0;
}

function uriPath(message) {
  return message.options
    .filter((option) => option.number === 11)
    .map((option) => option.value.toString("utf8"))
    .join("/");
}

function epoch() {
  return Date.now() / 1000;
}

async function bind(socket, port, address) {
  await new Promise((resolve, reject) => {
    socket.once("error", reject);
    socket.bind(port, address, () => {
      socket.removeListener("error", reject);
      resolve();
    });
  });
}

async function main() {
  const args = parseArgs(process.argv);
  const sessionId = args.session || "smoke_01";
  const seed = Number(args.seed || 6101);
  const profile = args.profile || "smoke";
  const serverIp = args["server-ip"] || "127.20.1.1";
  const port = Number(args.port || 5683);
  if (!serverIp.startsWith("127.")) {
    throw new Error("This research testbed only accepts IPv4 loopback addresses (127.0.0.0/8).");
  }
  const outputDir = path.resolve(args["output-dir"] || path.join(__dirname, "generated"));
  fs.mkdirSync(outputDir, { recursive: true });

  const random = mulberry32(seed);
  const sessionNumber = Number((sessionId.match(/(\d+)$/) || [0, 1])[1]);
  const prefix = serverIp.split(".").slice(0, 3).join(".");
  const addresses = {
    server: serverIp,
    client_a: `${prefix}.10`,
    client_b: `${prefix}.11`,
    noisy_client: `${prefix}.12`,
    probe: `${prefix}.20`,
    actor: `${prefix}.99`,
  };
  const blockSize = 1024;
  const resourceSize = 32768;
  const blockCount = resourceSize / blockSize;
  const resource = Buffer.alloc(resourceSize);
  for (let i = 0; i < resource.length; i += 1) resource[i] = 65 + ((i + seed) % 26);

  const stats = {
    requests_sent: 0,
    responses_received: 0,
    request_bytes: 0,
    response_bytes: 0,
    server_requests: 0,
    server_responses: 0,
    server_request_bytes: 0,
    server_response_bytes: 0,
    by_workload: {},
  };
  const events = [];
  const probes = [];
  const pending = new Map();
  let mid = (seed * 997) & 0xffff;
  let tokenCounter = (seed * 2654435761) >>> 0;

  function nextToken() {
    tokenCounter = (tokenCounter + 1) >>> 0;
    const token = Buffer.alloc(4);
    token.writeUInt32BE(tokenCounter);
    return token;
  }

  const server = dgram.createSocket("udp4");
  server.on("message", (buffer, remote) => {
    let request;
    try {
      request = decodeCoap(buffer);
    } catch {
      return;
    }
    stats.server_requests += 1;
    stats.server_request_bytes += buffer.length;
    if (request.code !== 1) return;
    const requestedPath = uriPath(request);
    let response;
    if (requestedPath === "large") {
      const blockValue = optionUInt(request, 23, 6);
      const number = blockValue >>> 4;
      const safeNumber = Math.min(number, blockCount - 1);
      const more = safeNumber < blockCount - 1 ? 1 : 0;
      const payload = resource.subarray(safeNumber * blockSize, (safeNumber + 1) * blockSize);
      const responseBlock = (safeNumber << 4) | (more << 3) | 6;
      response = encodeCoap({
        type: request.type === 0 ? 2 : 1,
        code: 69,
        mid: request.mid,
        token: request.token,
        options: [
          { number: 12, value: uintOption(42) },
          { number: 23, value: uintOption(responseBlock) },
          { number: 28, value: uintOption(resourceSize) },
        ],
        payload,
      });
    } else if (requestedPath === "sensor") {
      const payload = Buffer.from(`temperature=${20 + (seed % 7)}.${Math.floor(random() * 10)}`);
      response = encodeCoap({
        type: request.type === 0 ? 2 : 1,
        code: 69,
        mid: request.mid,
        token: request.token,
        options: [{ number: 12, value: uintOption(0) }],
        payload,
      });
    } else {
      response = encodeCoap({
        type: request.type === 0 ? 2 : 1,
        code: 132,
        mid: request.mid,
        token: request.token,
      });
    }
    server.send(response, remote.port, remote.address);
    stats.server_responses += 1;
    stats.server_response_bytes += response.length;
  });
  await bind(server, port, addresses.server);

  const clients = {};
  for (const name of ["client_a", "client_b", "noisy_client", "probe", "actor"]) {
    const socket = dgram.createSocket("udp4");
    socket.on("message", (buffer) => {
      let response;
      try {
        response = decodeCoap(buffer);
      } catch {
        return;
      }
      stats.responses_received += 1;
      stats.response_bytes += buffer.length;
      const key = response.token.toString("hex");
      const sent = pending.get(key);
      if (sent) {
        sent.responses += 1;
        if (sent.workload === "probe") {
          probes.push({
            timestamp_epoch: epoch(),
            rtt_ms: (performance.now() - sent.started_perf).toFixed(3),
            timeout: 0,
          });
        }
        if (!sent.reusedToken || sent.responses >= sent.expectedResponses) pending.delete(key);
      }
    });
    await bind(socket, 0, addresses[name]);
    clients[name] = socket;
  }

  function sendGet(
    clientName,
    requestedPath,
    blockNumber,
    workload,
    token = null,
    expected = 1,
    messageType = 0,
  ) {
    const socket = clients[clientName];
    const requestToken = token || nextToken();
    const options = [{ number: 11, value: Buffer.from(requestedPath) }];
    if (blockNumber !== null) {
      options.push({ number: 23, value: uintOption((blockNumber << 4) | 6) });
    }
    const packet = encodeCoap({
      type: messageType,
      code: 1,
      mid: (mid = (mid + 1) & 0xffff),
      token: requestToken,
      options,
    });
    const key = requestToken.toString("hex");
    const existing = pending.get(key);
    pending.set(key, {
      workload,
      started_perf: existing ? existing.started_perf : performance.now(),
      responses: existing ? existing.responses : 0,
      expectedResponses: expected,
      reusedToken: expected > 1,
    });
    socket.send(packet, port, addresses.server);
    stats.requests_sent += 1;
    stats.request_bytes += packet.length;
    stats.by_workload[workload] = (stats.by_workload[workload] || 0) + 1;
  }

  async function waitUntil(sessionStartPerf, offsetSeconds) {
    const remaining = offsetSeconds * 1000 - (performance.now() - sessionStartPerf);
    if (remaining > 0) await sleep(remaining);
  }

  async function runRate(durationSeconds, rate, callback) {
    const started = performance.now();
    let sent = 0;
    while ((performance.now() - started) / 1000 < durationSeconds) {
      const elapsed = (performance.now() - started) / 1000;
      const target = Math.floor(elapsed * rate) + 1;
      while (sent < target) {
        callback(sent);
        sent += 1;
      }
      await sleep(5);
    }
    return sent;
  }

  async function legitimateDownloadBurst(plan, sessionStartPerf) {
    await waitUntil(sessionStartPerf, plan.offset);
    let block = 0;
    let transferToken = nextToken();
    await runRate(plan.duration, plan.rate, () => {
      if (block === 0) transferToken = nextToken();
      sendGet(plan.client, "large", block, "legitimate_block2_download", transferToken, blockCount);
      block = (block + 1) % blockCount;
    });
  }

  async function legitimateSingleBlock(plan, sessionStartPerf) {
    await waitUntil(sessionStartPerf, plan.offset);
    await runRate(plan.duration, plan.rate, () => {
      sendGet(plan.client, "large", plan.block, "legitimate_single_block_read");
    });
  }

  async function legitimateSensorBurst(plan, sessionStartPerf) {
    await waitUntil(sessionStartPerf, plan.offset);
    await runRate(plan.duration, plan.rate, () => {
      sendGet(plan.client, "sensor", null, "legitimate_sensor_burst");
    });
  }

  async function blockAttackEpisode(plan, sessionStartPerf, index) {
    await waitUntil(sessionStartPerf, plan.offset);
    const episodeId = `${sessionId}_block2_${String(index + 1).padStart(2, "0")}`;
    const tokenPool = Array.from({ length: 8 }, () => nextToken());
    const startEpoch = epoch();
    const sent = await runRate(plan.duration, plan.rate, (sequence) => {
      let block;
      let token = null;
      if (plan.strategy === "hot_block_unique_token") {
        block = sequence % 5 === 0 ? 1 : 0;
      } else if (plan.strategy === "random_block_unique_token") {
        block = Math.floor(random() * blockCount);
      } else if (plan.strategy === "sequential_block_unique_token") {
        block = sequence % blockCount;
      } else {
        block = Math.floor(random() * blockCount);
        token = tokenPool[sequence % tokenPool.length];
      }
      sendGet("actor", "large", block, "block2_amplification_flood", token);
    });
    const endEpoch = epoch();
    events.push({
      session_id: sessionId,
      episode_id: episodeId,
      attack_type: "coap_block2_amplification_flood",
      label_source: "external_orchestrator_event",
      start_epoch: Number(startEpoch.toFixed(6)),
      end_epoch: Number(endEpoch.toFixed(6)),
      duration_seconds: Number((endEpoch - startEpoch).toFixed(6)),
      target_rate_pps: plan.rate,
      sent_requests: sent,
      strategy: plan.strategy,
      actor_ip: addresses.actor,
      server_ip: addresses.server,
      server_port: port,
      spoofing: false,
    });
  }

  async function requestFloodEpisode(plan, sessionStartPerf, index) {
    await waitUntil(sessionStartPerf, plan.offset);
    const episodeId = `${sessionId}_request_flood_${String(index + 1).padStart(2, "0")}`;
    const tokenPool = Array.from({ length: 12 }, () => nextToken());
    const messageType = plan.strategy.startsWith("nonconfirmable") ? 1 : 0;
    const startEpoch = epoch();
    const sent = await runRate(plan.duration, plan.rate, (sequence) => {
      const token = plan.strategy.endsWith("token_pool")
        ? tokenPool[sequence % tokenPool.length]
        : null;
      sendGet(
        "actor",
        "sensor",
        null,
        "coap_request_flood",
        token,
        1,
        messageType,
      );
    });
    const endEpoch = epoch();
    events.push({
      session_id: sessionId,
      episode_id: episodeId,
      attack_type: "coap_request_flood",
      label_source: "external_orchestrator_event",
      start_epoch: Number(startEpoch.toFixed(6)),
      end_epoch: Number(endEpoch.toFixed(6)),
      duration_seconds: Number((endEpoch - startEpoch).toFixed(6)),
      target_rate_pps: plan.rate,
      sent_requests: sent,
      strategy: plan.strategy,
      actor_ip: addresses.actor,
      server_ip: addresses.server,
      server_port: port,
      spoofing: false,
    });
  }

  const smoke = profile === "smoke";
  const strong = profile === "strong";
  const totalDuration = smoke ? 8 : strong ? 68 : 44;
  const factor = smoke
    ? 1
    : strong
      ? 0.82 + (sessionNumber % 7) * 0.06
      : 0.88 + (sessionNumber % 5) * 0.06;
  const strategies = [
    "hot_block_unique_token",
    "random_block_unique_token",
    "sequential_block_unique_token",
    "random_block_token_pool",
  ];
  const blockAttackPlans = smoke
    ? [{ offset: 2.5, duration: 2.5, rate: 24, strategy: strategies[0] }]
    : strong
      ? [
          { offset: 6.0, duration: 4.2, rate: Math.round(60 * factor), strategy: strategies[(sessionNumber + 0) % 4] },
          { offset: 20.0, duration: 4.5, rate: Math.round(105 * factor), strategy: strategies[(sessionNumber + 1) % 4] },
          { offset: 29.0, duration: 4.8, rate: Math.round(175 * factor), strategy: strategies[(sessionNumber + 2) % 4] },
          { offset: 39.0, duration: 4.5, rate: Math.round(285 * factor), strategy: strategies[(sessionNumber + 3) % 4] },
          { offset: 56.0, duration: 5.0, rate: Math.round(420 * factor), strategy: strategies[(sessionNumber + 4) % 4] },
        ]
      : [
        { offset: 6.0, duration: 4.5, rate: Math.round(70 * factor), strategy: strategies[(sessionNumber + 0) % 4] },
        { offset: 14.0, duration: 4.5, rate: Math.round(130 * factor), strategy: strategies[(sessionNumber + 1) % 4] },
        { offset: 23.0, duration: 4.8, rate: Math.round(230 * factor), strategy: strategies[(sessionNumber + 2) % 4] },
        { offset: 32.0, duration: 5.0, rate: Math.round(360 * factor), strategy: strategies[(sessionNumber + 3) % 4] },
      ];
  const requestStrategies = [
    "confirmable_sensor_unique_token",
    "nonconfirmable_sensor_unique_token",
    "confirmable_sensor_token_pool",
  ];
  const requestAttackPlans = strong
    ? [
        { offset: 13.0, duration: 4.5, rate: Math.round(150 * factor), strategy: requestStrategies[(sessionNumber + 0) % 3] },
        { offset: 47.0, duration: 5.0, rate: Math.round(560 * factor), strategy: requestStrategies[(sessionNumber + 1) % 3] },
      ]
    : [];
  const legitimatePlans = smoke
    ? [{ offset: 0.8, duration: 5.5, rate: 30, client: "client_a" }]
    : strong
      ? [
          { offset: 1.5, duration: 2.2, rate: 120, client: "actor" },
          { offset: 5.0, duration: 1.8, rate: 310, client: "client_a" },
          { offset: 11.0, duration: 2.0, rate: 170, client: "client_b" },
          { offset: 18.0, duration: 1.8, rate: 240, client: "actor" },
          { offset: 21.0, duration: 1.7, rate: 420, client: "client_a" },
          { offset: 26.0, duration: 2.5, rate: 90, client: "client_b" },
          { offset: 32.0, duration: 1.8, rate: 350, client: "client_a" },
          { offset: 36.0, duration: 2.0, rate: 180, client: "actor" },
          { offset: 41.0, duration: 1.6, rate: 450, client: "client_b" },
          { offset: 53.0, duration: 2.0, rate: 280, client: "client_a" },
          { offset: 58.0, duration: 1.6, rate: 500, client: "client_b" },
          { offset: 63.0, duration: 2.0, rate: 220, client: "actor" },
        ]
      : [
        { offset: 2.0, duration: 2.2, rate: 90, client: "actor" },
        { offset: 5.0, duration: 2.0, rate: 220, client: "client_a" },
        { offset: 11.0, duration: 2.0, rate: 130, client: "client_b" },
        { offset: 16.0, duration: 1.5, rate: 300, client: "client_a" },
        { offset: 20.0, duration: 2.0, rate: 160, client: "actor" },
        { offset: 24.0, duration: 1.8, rate: 280, client: "client_b" },
        { offset: 29.0, duration: 2.5, rate: 80, client: "client_a" },
        { offset: 34.0, duration: 1.5, rate: 350, client: "client_b" },
        { offset: 39.0, duration: 2.0, rate: 200, client: "actor" },
      ];
  const singleBlockPlans = smoke
    ? []
    : strong
      ? [
          { offset: 8.0, duration: 2.0, rate: 80, client: "noisy_client", block: 0 },
          { offset: 22.0, duration: 2.0, rate: 160, client: "noisy_client", block: 0 },
          { offset: 40.0, duration: 1.8, rate: 260, client: "noisy_client", block: 7 },
          { offset: 57.0, duration: 1.8, rate: 400, client: "noisy_client", block: 15 },
        ]
      : [
        { offset: 8.0, duration: 1.8, rate: 55, client: "noisy_client", block: 0 },
        { offset: 25.0, duration: 2.0, rate: 95, client: "noisy_client", block: 0 },
        { offset: 35.0, duration: 1.5, rate: 145, client: "noisy_client", block: 7 },
      ];
  const sensorBurstPlans = strong
    ? [
        { offset: 3.0, duration: 2.0, rate: 80, client: "noisy_client" },
        { offset: 12.5, duration: 2.0, rate: 220, client: "client_a" },
        { offset: 18.0, duration: 1.5, rate: 130, client: "actor" },
        { offset: 30.0, duration: 2.0, rate: 500, client: "client_b" },
        { offset: 44.5, duration: 1.5, rate: 300, client: "actor" },
        { offset: 48.0, duration: 2.0, rate: 650, client: "client_a" },
        { offset: 62.0, duration: 2.0, rate: 450, client: "actor" },
      ]
    : [];

  const sessionStartEpoch = epoch();
  const sessionStartPerf = performance.now();
  const tasks = [];
  for (const [index, plan] of blockAttackPlans.entries()) {
    tasks.push(blockAttackEpisode(plan, sessionStartPerf, index));
  }
  for (const [index, plan] of requestAttackPlans.entries()) {
    tasks.push(requestFloodEpisode(plan, sessionStartPerf, index));
  }
  for (const plan of legitimatePlans) tasks.push(legitimateDownloadBurst(plan, sessionStartPerf));
  for (const plan of singleBlockPlans) tasks.push(legitimateSingleBlock(plan, sessionStartPerf));
  for (const plan of sensorBurstPlans) tasks.push(legitimateSensorBurst(plan, sessionStartPerf));

  tasks.push(
    (async () => {
      await runRate(totalDuration - 0.5, 3.0, (sequence) => {
        sendGet(sequence % 2 ? "client_a" : "client_b", "sensor", null, "background_sensor");
      });
    })(),
  );
  tasks.push(
    (async () => {
      await runRate(totalDuration - 0.5, 2.0, () => {
        sendGet("probe", "sensor", null, "probe");
      });
    })(),
  );

  await Promise.all(tasks);
  await waitUntil(sessionStartPerf, totalDuration);
  await sleep(500);
  const sessionEndEpoch = epoch();

  for (const socket of Object.values(clients)) socket.close();
  server.close();

  events.sort((a, b) => a.start_epoch - b.start_epoch);
  const eventPath = path.join(outputDir, `${sessionId}.events.jsonl`);
  const probePath = path.join(outputDir, `${sessionId}.probes.csv`);
  const summaryPath = path.join(outputDir, `${sessionId}.summary.json`);
  fs.writeFileSync(eventPath, events.map((event) => JSON.stringify(event)).join("\n") + "\n", "utf8");
  fs.writeFileSync(
    probePath,
    "timestamp_epoch,rtt_ms,timeout\n" + probes.map((probe) => `${probe.timestamp_epoch},${probe.rtt_ms},${probe.timeout}`).join("\n") + "\n",
    "utf8",
  );
  const summary = {
    schema_version: "1.0",
    session_id: sessionId,
    profile,
    seed,
    session_start_epoch: sessionStartEpoch,
    session_end_epoch: sessionEndEpoch,
    duration_seconds: sessionEndEpoch - sessionStartEpoch,
    addresses,
    port,
    resource: { path: "/large", bytes: resourceSize, block_size: blockSize, blocks: blockCount },
    attack_types: [...new Set(events.map((event) => event.attack_type))].sort(),
    spoofing: false,
    stats,
    episode_count: events.length,
    probe_samples: probes.length,
  };
  fs.writeFileSync(summaryPath, JSON.stringify(summary, null, 2) + "\n", "utf8");
  process.stdout.write(JSON.stringify(summary) + "\n");
}

main().catch((error) => {
  process.stderr.write(`${error.stack || error}\n`);
  process.exitCode = 1;
});
