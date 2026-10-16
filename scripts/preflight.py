"""Readiness check; no cloud resources are created."""
import argparse
import asyncio
import json
import os

from dotenv import load_dotenv
from campuspulse.agent import configured_client
from campuspulse.tools import ToolHub


async def check(live):
    checks = []
    async with ToolHub({}) as hub:
        result = await hub.call("current_time", {"timezone_name": "Asia/Almaty"})
        checks.append({"check": "mcp_protocol", "ok": "now" in result, "tools": sorted(hub.mcp_names)})
    try:
        import google.auth
        from google.auth.transport.requests import Request
        credentials, project = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        credentials.refresh(Request())
        checks.append({"check": "google_adc", "ok": True, "project": project})
    except Exception:
        checks.append({"check": "google_adc", "ok": False, "action": "Run gcloud auth application-default login"})
    if live:
        try:
            client = configured_client()
            try:
                response = await client.aio.models.generate_content(model=os.getenv("GEMINI_MODEL", "gemini-3.6-flash"), contents="Reply with exactly CAMPUSPULSE_OK")
                checks.append({"check": "live_gemini", "ok": bool(response.text and "CAMPUSPULSE_OK" in response.text), "model": os.getenv("GEMINI_MODEL", "gemini-3.6-flash")})
            finally:
                await client.aio.aclose(); client.close()
        except Exception:
            checks.append({"check": "live_gemini", "ok": False, "action": "Check project, billing, Vertex AI API, IAM, model access and region"})
    print(json.dumps(checks, ensure_ascii=False, indent=2))
    return all(c["ok"] for c in checks)


if __name__ == "__main__":
    load_dotenv()
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="Make a small billed Gemini request")
    args = parser.parse_args()
    raise SystemExit(0 if asyncio.run(check(args.live)) else 1)
