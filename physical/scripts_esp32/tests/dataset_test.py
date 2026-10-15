"""Regression tests for physical windowing and auditable labels; no network traffic."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "dataset"))
from extract import GroundTruth, FEATURES, original, packet_blocks


def packet(time, source="10.0.0.2", destination="10.0.0.1", kind=0, code=1, mid=10, token="aabbccdd"):
    row = dict.fromkeys(original.FIELDS, "")
    row.update({"frame.number": 1, "frame.time_relative": time, "frame.time_epoch": 1000 + time,
                "frame.len": 58 if code == 1 else 1078, "ip.src": source, "ip.dst": destination,
                "ip.ttl": 64, "udp.srcport": 40000 if source != "10.0.0.1" else 5683,
                "udp.dstport": 5683 if destination == "10.0.0.1" else 40000,
                "coap.type": kind, "coap.code": code, "coap.mid": mid, "coap.token": token,
                "coap.opt.uri_path": "large" if code == 1 else "", "coap.payload_length": 0 if code == 1 else 1024,
                "coap.opt.block_number": 0, "coap.opt.block_mflag": 0 if code == 1 else 1,
                "coap.opt.block_size": 1024, "coap.block_length": np.nan if code == 1 else 1024})
    return row


class DatasetTests(unittest.TestCase):
    def setUp(self):
        # Explicit workspace path keeps creation/cleanup within the project.
        self.temp = tempfile.TemporaryDirectory(prefix="dataset-test-", dir=ROOT.parent / "test")
        self.base = Path(self.temp.name).resolve()
        assert self.base.is_relative_to(ROOT.parent / "test")

    def tearDown(self):
        self.temp.cleanup()

    def test_streaming_matches_original_23_features_at_all_window_sizes(self):
        rows = []
        for i, t in enumerate([0.1, 0.2, 0.5, 0.9, 1.3, 1.8, 2.0, 2.4, 2.9, 4.0, 4.4, 4.8]):
            row = packet(t, mid=i)
            row["frame.number"] = i + 1
            row["coap.opt.block_number"] = [31, 0, 1, 1][i % 4]
            rows.append(row)
        raw = pd.DataFrame(rows)
        tsv = self.base / "packets.tsv"
        raw.to_csv(tsv, sep="\t", index=False)
        blocks = list(packet_blocks(tsv, chunksize=3))
        self.assertEqual(sum(len(b) for b in blocks), len(raw))
        for width in [0.5, 1.0, 2.0]:
            whole = original.aggregate(raw, "fixture", width)
            streamed = pd.concat([original.aggregate(b, "fixture", width) for b in blocks], ignore_index=True)
            pd.testing.assert_frame_equal(whole[FEATURES], streamed[FEATURES], check_dtype=False, atol=1e-12, rtol=1e-12)
        window = original.aggregate(raw.iloc[:2], "fixture", 1.0).iloc[0]
        self.assertEqual(window["core_bytes_per_s"], 116)
        self.assertAlmostEqual(window["core_mean_iat"], .1)
        self.assertEqual(window["coap_block2_sequential_req_frac"], 1)

    def actor_truth(self):
        actor = self.base / "actor"
        actor.mkdir()
        phase = {"phase_id": "attack", "kind": "block2_amplification", "label": "block2_amplification",
                 "scheduler_start_epoch": 1000, "scheduled_start_epoch": 1000,
                 "scheduler_end_epoch": 1006, "scheduled_end_epoch": 1006}
        tx = {"kind": "tx", "request_id": "0:1", "lane": 0, "mid": 10, "token": "aabbccdd",
              "message_type": "NON", "phase_id": "attack", "epoch": 1002.1}
        contents = {
            "manifest.json": json.dumps({"server": "10.0.0.1"}),
            "summary.json": json.dumps({"status": "completed", "log_dropped_records": 0,
                "lanes": [{"lane": 0, "local": {"port": 40000}}], "phases": [phase]}),
            "plan.json": json.dumps({"response_timeout_ms": 3000}), "events.jsonl": "",
            "traffic.jsonl": json.dumps(tx) + "\n" + json.dumps({"kind": "send_result", "request_id": "0:1", "accepted_by_udp": True}) + "\n"}
        for name, data in contents.items():
            (actor / name).write_text(data, encoding="utf-8")
        (actor / "sha256.json").write_text(json.dumps({name: hashlib.sha256((actor / name).read_bytes()).hexdigest() for name in contents}))
        (self.base / "clock.json").write_text(json.dumps({"actor_minus_capture_seconds": 0,
                    "uncertainty_seconds": .05, "method": "fixture", "evidence": ["fixture"]}))
        session = {"server_ip": "10.0.0.1", "benign_ips": ["10.0.0.3"],
                   "actor": {"ip": "10.0.0.2", "directory": "actor", "clock_file": "clock.json"}}
        return GroundTruth(session, self.base, self.base / "lookup.sqlite")

    def test_non_response_matches_original_request_despite_different_mid(self):
        truth = self.actor_truth()
        try:
            raw = pd.DataFrame([packet(2.1, kind=1), packet(2.2, source="10.0.0.1", destination="10.0.0.2", kind=1, code=69, mid=65000)])
            marked = truth.annotate(raw)
            self.assertEqual(marked["_truth"].tolist(), ["attack", "attack"])
            for width in [.5, 1, 2]:
                kept, excluded = truth.label(marked, original.aggregate(marked, "fixture", width), width, 1010)
                self.assertEqual(len(excluded), 0)
                self.assertEqual(kept["label_attack"].tolist(), ["coap_block2_amplification_flood"])
                self.assertEqual(kept["label_overlap_fraction"].tolist(), [1.0])
        finally:
            truth.close()

    def test_clock_boundary_and_late_response_are_excluded(self):
        truth = self.actor_truth()
        try:
            marked = pd.DataFrame([packet(5.9)])
            marked["_truth"] = "attack"
            kept, excluded = truth.label(marked, original.aggregate(marked, "fixture", .5), .5, 1010)
            self.assertEqual(len(kept), 0)
            self.assertEqual(excluded["exclusion_reason"].tolist(), ["phase_boundary_or_clock_uncertainty"])
            marked["frame.time_relative"] = 6.2
            marked["frame.time_epoch"] = 1006.2
            kept, excluded = truth.label(marked, original.aggregate(marked, "fixture", .5), .5, 1010)
            self.assertEqual(len(kept), 0)
        finally:
            truth.close()

    def test_unknown_hosts_do_not_become_benign_and_final_window_is_audited(self):
        truth = GroundTruth({"server_ip": "10.0.0.1", "benign_ips": ["10.0.0.3"], "traffic_declaration": "benign_only"}, self.base, self.base / "unused.sqlite")
        marked = truth.annotate(pd.DataFrame([packet(2.1), packet(3.2, source="10.0.0.3")]))
        kept, excluded = truth.label(marked, original.aggregate(marked, "fixture", 1), 1, 1003.2)
        self.assertEqual(len(kept), 0)
        self.assertEqual(set(excluded["exclusion_reason"]), {"preflight_guard_or_unknown_packet_origin", "outside_complete_observation_interval"})

    def test_missing_external_ground_truth_is_rejected(self):
        with self.assertRaises(ValueError):
            GroundTruth({"server_ip": "10.0.0.1", "benign_ips": ["10.0.0.3"]}, self.base, self.base / "unused.sqlite")

    def test_nonmonotonic_capture_fails_instead_of_losing_windows(self):
        tsv = self.base / "backwards.tsv"
        pd.DataFrame([packet(2.1), packet(1.1)]).to_csv(tsv, sep="\t", index=False)
        with self.assertRaises(ValueError):
            list(packet_blocks(tsv, chunksize=1))


if __name__ == "__main__":
    unittest.main(verbosity=2)
