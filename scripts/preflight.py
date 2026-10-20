"""Readiness check; no cloud resources are created."""
import argparse
import asyncio
import json
import os

from dotenv import load_dotenv
from campuspulse.agent import configured_client
from campuspulse.provider_errors import classify_provider_error
from campuspulse.tools import ToolHub


async def check(live):
    checks = []
    async with ToolHub({}) as hub:
        result = await hub.call("current_time", {"timezone_name": "Asia/Almaty"})
        checks.append({"check": "mcp_protocol", "ok": "now" in result, "tools": sorted(hub.mcp_names)})
    if os.getenv("GEMINI_API_KEY"):
        checks.append({"check": "gemini_server_key", "ok": True, "note": "Key present; a real request is needed to verify access. Agent Engine still requires Vertex ADC."})
    else:
        try:
            import google.auth
            from google.auth.transport.requests import Request
            credentials, project = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
            credentials.refresh(Request())
            checks.append({"check": "google_adc", "ok": True, "project": project})
        except Exception:
            checks.append({"check": "google_adc", "ok": False, "action": "Configure local Gemini API key or run gcloud auth application-default login for Vertex AI"})
    if live:
        provider = "developer_api" if os.getenv("GEMINI_API_KEY") else "vertex_ai"
        client = None
        try:
            client = configured_client()
            response = await client.aio.models.generate_content(model=os.getenv("GEMINI_MODEL", "gemini-3.8-flash"), contents="Reply with exactly CAMPUSPULSE_OK")
            checks.append({"check": "live_gemini", "ok": bool(response.text and "CAMPUSPULSE_OK" in response.text), "provider": provider, "model": os.getenv("GEMINI_MODEL", "gemini-3.8-flash")})
        except Exception as error:
            checks.append({"check": "live_gemini", "ok": False, "provider": provider,
                           **classify_provider_error(error, provider)})
        finally:
            if client is not None:
                # Cleanup must not replace a useful provider error with an
                # unrelated close failure, or print upstream error details.
                try:
                    await client.aio.aclose()
                except Exception:
                    pass
                try:
                    client.close()
                except Exception:
                    pass
    print(json.dumps(checks, ensure_ascii=False, indent=2))
    return all(c["ok"] for c in checks)


if __name__ == "__main__":
    load_dotenv()
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="Make a small Gemini request (uses API quota; may incur charges)")
    args = parser.parse_args()
    raise SystemExit(0 if asyncio.run(check(args.live)) else 1)
