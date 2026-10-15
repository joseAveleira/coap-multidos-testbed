"use strict";
const fs = require("node:fs");
const path = require("node:path");
const os = require("node:os");
const crypto = require("node:crypto");
const {performance} = require("node:perf_hooks");
const {setTimeout: delay} = require("node:timers/promises");
const {Channel, preflight} = require("./transport");
const {VERSION, validate, localAddress, rng} = require("./plan");

const sha256 = value => crypto.createHash("sha256").update(value).digest("hex");
async function hashFile(file) {
  const digest = crypto.createHash("sha256");
  for await (const chunk of fs.createReadStream(file)) digest.update(chunk);
  return digest.digest("hex");
}
function writeJson(file, value) { fs.writeFileSync(file, JSON.stringify(value, null, 2) + "\n", {flag: "wx"}); }

class Journal {
  constructor(directory) {
    this.anchorMono = performance.now(); this.anchorEpoch = Date.now() / 1000;
    this.failure = null; this.dropped = 0; this.maxClockDeltaMs = 0;
    this.streams = Object.fromEntries(["events", "traffic"].map(name => {
      const stream = fs.createWriteStream(path.join(directory, `${name}.jsonl`), {flags: "wx", highWaterMark: 1024 * 1024});
      stream.on("error", error => { this.failure = `log_error: ${error.message}`; });
      return [name, stream];
    }));
  }
  epoch(mono = performance.now()) { return this.anchorEpoch + (mono - this.anchorMono) / 1000; }
  emit(event) {
    const mono = performance.now(), epoch = this.epoch(mono), wall = Date.now() / 1000;
    this.maxClockDeltaMs = Math.max(this.maxClockDeltaMs, Math.abs(epoch - wall) * 1000);
    const packet = ["tx", "rx", "send_result", "timeout", "cancelled", "unmatched_response", "mismatched_response", "malformed_response"].includes(event.kind);
    const stream = this.streams[packet ? "traffic" : "events"];
    if (stream.destroyed || stream.writableLength > 8 * 1024 * 1024) {
      this.failure ||= "log_backpressure"; this.dropped++; return;
    }
    stream.write(JSON.stringify({epoch, wall_epoch: wall, utc: new Date(epoch * 1000).toISOString(),
      mono_ms: mono - this.anchorMono, ...event}) + "\n");
  }
  async close() {
    await Promise.all(Object.values(this.streams).map(stream => new Promise(resolve => {
      if (stream.destroyed) resolve(); else { stream.once("error", resolve); stream.end(resolve); }
    })));
  }
}

async function run({plan, server, port = 5683, output = "registros_actor", session,
  startAt, startDelay = 10, clockNote = "not_verified", onProgress = () => {}, signal}) {
  const budget = validate(plan); localAddress(server);
  if (!Number.isInteger(port) || port < 1 || port > 65535) throw Error("Puerto inválido.");
  if (!/^[a-zA-Z0-9_-][a-zA-Z0-9_.-]*$/.test(session || "")) throw Error("Indica un nombre de sesión nuevo y válido.");
  if (!Number.isFinite(startDelay) || startDelay < 0 || startDelay > 3600) throw Error("start-delay fuera de rango.");
  let requestedEpoch = null;
  if (startAt !== undefined) {
    if (!/(Z|[+-]\d\d:\d\d)$/.test(startAt)) throw Error("start-at requiere zona horaria (Z o desplazamiento).");
    requestedEpoch = Date.parse(startAt) / 1000;
    if (!Number.isFinite(requestedEpoch) || requestedEpoch <= Date.now() / 1000 || requestedEpoch - Date.now() / 1000 > 3600)
      throw Error("start-at debe estar en el futuro, como máximo a una hora.");
  }
  fs.mkdirSync(output, {recursive: true});
  const directory = path.resolve(output, session); fs.mkdirSync(directory);
  const journal = new Journal(directory), emit = event => journal.emit(event);
  const channels = [], reports = [], states = [];
  let stopReason = null, error = null, startMono = null, phaseIndex = -1, active = null, nextDue = 0;
  const sourceFiles = ["../actor_coap.js", "plan.js", "runner.js", "transport.js", "../servidor/coap.js"];
  const manifest = {schema: 1, actor_version: VERSION, session, server, port,
    created_utc: new Date().toISOString(), node_version: process.version,
    platform: {type: os.type(), release: os.release(), architecture: os.arch()},
    clock_note: clockNote, timestamp_definition: "epoch anchored to monotonic clock; wall_epoch also retained; remote clock offset is not measured",
    capture_required_at_server: true, automatic_retransmissions: false,
    mid_reuse_minimum_seconds: 247, max_pending_per_lane: 512,
    preflight_packets: 33, ...budget, requested_start_utc: startAt ?? null,
    plan_sha256: sha256(JSON.stringify(plan)),
    source_sha256: Object.fromEntries(sourceFiles.map(file => [file, sha256(fs.readFileSync(path.join(__dirname, file)))]))};
  writeJson(path.join(directory, "plan.json"), plan);
  writeJson(path.join(directory, "manifest.json"), manifest);
  const abort = () => { stopReason ||= "interrupted"; };
  process.on("SIGINT", abort); process.on("SIGTERM", abort); signal?.addEventListener("abort", abort);
  if (signal?.aborted) abort();
  const stopped = () => stopReason || journal.failure;
  function endPhase(now, status = "ended") {
    if (!active) return;
    active.report.scheduler_end_epoch = journal.epoch(now);
    active.report.status = status;
    emit({kind: "phase_end", phase_id: active.phase.id, status,
      scheduled_end_epoch: journal.epoch(startMono + (active.phase.start_s + active.phase.duration_s) * 1000),
      note: "Responses may still arrive during the following guard; see phase_final."});
    active = null;
  }
  function beginPhase(index, now) {
    const phase = plan.phases[index];
    const report = {phase_id: phase.id, kind: phase.kind, label: phase.label,
      scheduled_start_epoch: journal.epoch(startMono + phase.start_s * 1000),
      scheduled_end_epoch: journal.epoch(startMono + (phase.start_s + phase.duration_s) * 1000),
      scheduler_start_epoch: journal.epoch(now), target_rate_rps: phase.rate_rps,
      queued: 0, accepted_by_udp: 0, send_errors: 0, valid_responses: 0, response_errors: 0,
      timeouts: 0, cancelled: 0, scheduler_skipped_slots: 0, capacity_skipped_slots: 0,
      downloads_verified: 0, downloads_aborted: 0, first_tx_epoch: null, last_tx_epoch: null,
      first_response_epoch: null, last_response_epoch: null};
    const state = {phase, report, random: rng((plan.seed ^ Math.imul(index + 1, 0x9e3779b9)) >>> 0),
      laneCursor: 0, counter: 0, episodeTokens: new Map(), transfers: new Map(), transferCounter: 0};
    states.push(state); reports.push(report); active = state;
    nextDue = startMono + phase.start_s * 1000;
    emit({...phase, kind: "phase_start", workload: phase.kind, phase_id: phase.id, scheduled_start_epoch: report.scheduled_start_epoch,
      scheduled_end_epoch: report.scheduled_end_epoch, scheduler_delay_ms: now - nextDue});
    if (phase.kind !== "guard") onProgress(`${phase.id}: ${phase.kind}, ${phase.rate_rps} req/s objetivo, ${phase.duration_s.toFixed(1)} s`);
  }
  function sendOne(state) {
    const {phase, report} = state, download = phase.kind === "benign_block2_download";
    let channel;
    for (let attempt = 0; attempt < channels.length; attempt++) {
      const candidate = channels[state.laneCursor++ % channels.length];
      if (!download || !candidate.pending.size) { channel = candidate; break; }
    }
    if (!channel) { report.capacity_skipped_slots++; return; }
    let block, token, transfer;
    if (download) {
      transfer = state.transfers.get(channel.lane);
      if (!transfer) {
        transfer = {id: `${phase.id}_download_${++state.transferCounter}`, token: channel.token(), nextBlock: 0};
        state.transfers.set(channel.lane, transfer);
        emit({kind: "download_start", phase_id: phase.id, transfer: transfer.id, lane: channel.lane});
      }
      block = transfer.nextBlock; token = transfer.token;
    } else {
      if (phase.kind.includes("block2")) {
        const blocks = 32768 / phase.block_size;
        block = phase.block_order === "random" ? Math.floor(state.random() * blocks) :
          phase.block_order === "fixed" ? phase.fixed_block :
          phase.block_order === "reverse" ? blocks - 1 - state.counter % blocks : state.counter % blocks;
      }
      if (phase.token_policy === "episode") {
        if (!state.episodeTokens.has(channel.lane)) state.episodeTokens.set(channel.lane, channel.token());
        token = state.episodeTokens.get(channel.lane);
      } else token = channel.token();
    }
    const request = channel.send({phase, block, token, transfer: transfer?.id,
      onAccepted: accepted => { if (accepted) report.accepted_by_udp++; },
      onResult: result => {
        if (result.response) {
          const epoch = journal.epoch(); report.first_response_epoch ??= epoch; report.last_response_epoch = epoch;
        }
        const field = result.ok ? "valid_responses" : result.reason === "timeout" ? "timeouts" :
          result.reason === "cancelled" ? "cancelled" : result.reason === "send_error" ? "send_errors" : "response_errors";
        report[field]++;
        if (["resource_content_changed", "etag_changed"].includes(result.reason)) stopReason ||= result.reason;
        if (transfer) {
          if (result.ok && ++transfer.nextBlock === 32768 / phase.block_size) {
            report.downloads_verified++; state.transfers.delete(channel.lane);
            emit({kind: "download_verified", phase_id: phase.id, transfer: transfer.id, lane: channel.lane, bytes: 32768});
          } else if (!result.ok) {
            report.downloads_aborted++; state.transfers.delete(channel.lane);
            emit({kind: "download_aborted", phase_id: phase.id, transfer: transfer.id, reason: result.reason});
          }
        }
      }});
    if (request) {
      const epoch = journal.epoch(request.sentAt);
      report.first_tx_epoch ??= epoch; report.last_tx_epoch = epoch; report.queued++; state.counter++;
    } else report.capacity_skipped_slots++;
  }
  try {
    emit({kind: "preflight_start", label: "excluded"});
    for (let lane = 0; lane < plan.lanes; lane++) {
      if (stopped()) break;
      const channel = new Channel({server, port, lane, timeoutMs: plan.response_timeout_ms, emit,
        onFatal: failure => { stopReason ||= `socket_error: ${failure.message}`; }});
      channels.push(channel); await channel.open();
    }
    if (!stopped()) {
      const checked = await preflight(channels[0], stopped);
      for (const channel of channels) { channel.resource = checked.resource; channel.etag = checked.etag; }
      emit({kind: "preflight_end", status: "passed", resource_bytes: checked.resource.length,
        resource_sha256: checked.sha256, etag: checked.etag.toString("hex")});
      const now = performance.now();
      startMono = requestedEpoch === null ? now + startDelay * 1000 : journal.anchorMono + (requestedEpoch - journal.anchorEpoch) * 1000;
      if (startMono < now) throw Error("La hora prevista pasó durante la comprobación; programa un inicio posterior.");
      emit({kind: "session_armed", start_epoch: journal.epoch(startMono),
        end_epoch: journal.epoch(startMono + plan.duration_s * 1000), flows: channels.map(channel => ({lane: channel.lane, ...channel.endpoint}))});
      onProgress(`Comprobación correcta. Inicio UTC: ${new Date(journal.epoch(startMono) * 1000).toISOString()}`);
      while (!stopped() && performance.now() < startMono) await delay(Math.min(50, startMono - performance.now()));
      emit({kind: "session_start", scheduled_epoch: journal.epoch(startMono), status: stopped() ? "cancelled" : "started"});
      let nextProgress = startMono + 1000;
      while (!stopped()) {
        const now = performance.now();
        for (const channel of channels) channel.expire(now);
        while (phaseIndex + 1 < plan.phases.length && now >= startMono + plan.phases[phaseIndex + 1].start_s * 1000) {
          endPhase(now); beginPhase(++phaseIndex, now);
        }
        if (now >= startMono + plan.duration_s * 1000) { endPhase(now); break; }
        if (active && active.phase.kind !== "guard" && now >= nextDue) {
          const interval = 1000 / active.phase.rate_rps;
          const skipped = Math.floor((now - nextDue) / interval);
          active.report.scheduler_skipped_slots += skipped;
          nextDue += (skipped + 1) * interval;
          sendOne(active);
        }
        if (now >= nextProgress) {
          emit({kind: "counters", phase_id: active?.phase.id, lanes: channels.map(channel => channel.snapshot())});
          nextProgress = now + 1000;
        }
        await delay(active?.phase.kind === "guard" ? 5 : Math.max(1, Math.min(5, nextDue - performance.now())));
      }
    }
  } catch (caught) {
    error = caught; stopReason ||= `error: ${caught.message}`;
    emit({kind: "run_error", message: caught.message});
  } finally {
    endPhase(performance.now(), "interrupted");
    const drainUntil = performance.now() + plan.response_timeout_ms + 50;
    while (channels.some(channel => channel.pending.size) && performance.now() < drainUntil) {
      for (const channel of channels) channel.expire();
      await delay(10);
    }
    for (const channel of channels) await channel.close();
    for (const state of states) {
      state.report.downloads_incomplete_at_boundary = state.transfers.size;
      state.report.active_scheduler_seconds = Math.max(0,
        Math.min(state.report.scheduler_end_epoch, state.report.scheduled_end_epoch) -
        Math.max(state.report.scheduler_start_epoch, state.report.scheduled_start_epoch));
      state.report.achieved_send_rate_rps = state.report.active_scheduler_seconds > 0 ?
        state.report.accepted_by_udp / state.report.active_scheduler_seconds : null;
      state.report.send_rate_over_scheduled_interval_rps = state.report.accepted_by_udp / state.phase.duration_s;
      emit({...state.report, kind: "phase_final", workload: state.report.kind});
    }
    const reason = stopReason || journal.failure;
    const summary = {schema: 1, session, status: reason ? (reason === "interrupted" ? "interrupted" : "failed") : "completed",
      reason, finished_utc: new Date().toISOString(), started_epoch: startMono === null ? null : journal.epoch(startMono),
      clock_max_wall_disagreement_ms: journal.maxClockDeltaMs, log_dropped_records: journal.dropped,
      quality_flags: ["cross_host_clock_offset_not_measured_by_actor", ...(clockNote === "not_verified" ? ["clock_sync_not_documented"] : []),
        ...(journal.maxClockDeltaMs > 100 ? ["host_clock_changed"] : []), ...(journal.failure ? [journal.failure] : [])],
      lanes: channels.map(channel => ({lane: channel.lane, local: channel.endpoint, ...channel.snapshot()})), phases: reports};
    emit({kind: "session_end", status: summary.status, reason: summary.reason});
    await journal.close();
    if (journal.failure) { summary.status = "failed"; summary.reason = journal.failure; summary.log_dropped_records = journal.dropped; }
    writeJson(path.join(directory, "summary.json"), summary);
    const hashes = {};
    for (const file of ["plan.json", "manifest.json", "events.jsonl", "traffic.jsonl", "summary.json"])
      hashes[file] = await hashFile(path.join(directory, file));
    writeJson(path.join(directory, "sha256.json"), hashes);
    process.off("SIGINT", abort); process.off("SIGTERM", abort); signal?.removeEventListener("abort", abort);
    onProgress(`Sesión ${summary.status}: ${directory}`);
    // A failed or interrupted run remains available for audit; never relabel it as complete.
    if (error) error.directory = directory;
    return {directory, summary, error};
  }
}
module.exports = {run, Journal, sha256};
