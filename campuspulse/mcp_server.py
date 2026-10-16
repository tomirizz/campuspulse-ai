"""Real MCP server over stdio. Stdout is reserved for JSON-RPC."""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("CampusPulse Live Tools")


@mcp.tool()
def current_time(timezone_name: str = "Asia/Almaty") -> dict:
    """Get the actual current date/time in an IANA timezone before calculating deadlines."""
    try:
        zone = ZoneInfo(timezone_name)
    except Exception:
        return {"error": "Неизвестный часовой пояс"}
    return {"now": datetime.now(zone).isoformat(), "timezone": timezone_name, "source": "system_clock"}


if __name__ == "__main__":
    mcp.run(transport="stdio")
