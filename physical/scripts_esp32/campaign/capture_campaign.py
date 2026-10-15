#!/usr/bin/env python3
"""Run a finite sequence of physical captures; stop at the first failed session."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from capture_session import run, save
from remote import ROOT


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--deployment", type=Path, required=True)
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--prefix", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    deployment = json.loads(args.deployment.read_text())
    campaign = json.loads(args.campaign.read_text())
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    records = []
    evidence = {"status": "running", "created_utc": datetime.now(timezone.utc).isoformat(),
                "campaign": campaign, "sessions": records,
                "capture_seconds_planned": sum(s["duration_s"] + 35 for s in campaign["sessions"]),
                "inventory_seconds_per_session": 60,
                "source_sha256": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in [Path(__file__), ROOT / "campaign/capture_session.py", ROOT / "campaign/remote.py",
                              ROOT / "actor_coap.js", ROOT / "actor/runner.js", ROOT / "servidor/server.js"]}}
    save(output / "campaign_execution.json", evidence)
    try:
        for index, item in enumerate(campaign["sessions"], 1):
            session = f"{args.prefix}_{index:02d}"
            print(f"Starting session {index}/{len(campaign['sessions'])}: {session}", flush=True)
            result = run(config, deployment, (args.campaign.parent / item["file"]).resolve(),
                         session, output / session)
            records.append(result)
            save(output / "campaign_execution.json", evidence)
        evidence["status"] = "captured_pending_extraction"
    except BaseException as error:
        evidence.update(status="failed", error=str(error))
        raise
    finally:
        evidence["finished_utc"] = datetime.now(timezone.utc).isoformat()
        save(output / "campaign_execution.json", evidence)


if __name__ == "__main__":
    main()
