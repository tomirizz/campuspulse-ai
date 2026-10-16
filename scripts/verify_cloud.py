"""Verify a deployed remote agent; saves truthful, synthetic-only evidence."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path


def main():
    config = json.loads(Path("deployment.json").read_text())
    os.environ["ENGINE_RESOURCE_NAME"] = config["resource_name"]
    from campuspulse.server import remote_run
    result = remote_run("Проверь текущее время через current_time, затем вызови study_progress и объясни текущий опыт с источником.",
                        {"tasks": [], "materials": [], "preferences": {"timezone": "Asia/Almaty"}}, [])
    successful = {t["tool"] for t in result.get("trace", []) if t["status"] == "ok"}
    verified = result.get("status") == "ok" and {"current_time", "study_progress"}.issubset(successful)
    record = {"verified": verified, "verified_at": datetime.now(timezone.utc).isoformat(),
              "resource_name": config["resource_name"], "model": result.get("model"), "result": result}
    Path("evidence").mkdir(exist_ok=True)
    Path("evidence/live-cloud.json").write_text(json.dumps(record, ensure_ascii=False, indent=2))
    config["api_verified"] = verified
    Path("deployment.json").write_text(json.dumps(config, indent=2))
    print(json.dumps({"verified": verified, "tools": sorted(successful), "evidence": "evidence/live-cloud.json"}))
    raise SystemExit(0 if verified else 1)


if __name__ == "__main__":
    main()
