"""Deploy to the exact ReasoningEngine API required by the hackathon."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path

import vertexai
from vertexai.preview import reasoning_engines

from campuspulse.agent import CampusPulseAgent

ROOT = Path(__file__).resolve().parent.parent


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True)
    parser.add_argument("--bucket", required=True, help="Existing gs:// staging bucket")
    parser.add_argument("--region", default="us-central1")
    parser.add_argument("--model", default="gemini-3.6-flash")
    parser.add_argument("--gemini-location", default="global")
    parser.add_argument("--update", help="Existing resource name to update; avoids duplicate agents")
    args = parser.parse_args()
    if not args.bucket.startswith("gs://"):
        parser.error("--bucket must start with gs://")
    os.chdir(ROOT)
    vertexai.init(project=args.project, location=args.region, staging_bucket=args.bucket)
    agent = CampusPulseAgent(args.project, args.model, args.gemini_location)
    requirements = [line for line in (ROOT / "requirements.lock").read_text().splitlines()
                    if line and not line.startswith(("#", "pytest", "iniconfig", "pluggy", "pygments"))]
    kwargs = {"reasoning_engine": agent, "requirements": requirements,
              "extra_packages": ["campuspulse"], "display_name": "CampusPulse AI",
              "description": "GDG Astana: Gemini student agent with real MCP tools"}
    if args.update:
        remote = reasoning_engines.ReasoningEngine(args.update).update(**kwargs)
    else:
        remote = reasoning_engines.ReasoningEngine.create(**kwargs, sys_version="3.11")
    # Successful create is recorded separately from an actual remote query.
    record = {"resource_name": remote.resource_name, "project": args.project,
              "region": args.region, "model": args.model, "deployed_at": datetime.now(timezone.utc).isoformat(),
              "api_verified": False}
    Path("deployment.json").write_text(json.dumps(record, indent=2))
    print(json.dumps(record, indent=2))
    print("Run python -m scripts.verify_cloud to verify the live API before claiming deployment complete.")


if __name__ == "__main__":
    main()
