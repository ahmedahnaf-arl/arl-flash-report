"""
ERP client — query the live ERP (iBOS) via the enterprise-api-gateway MCP.
Used as a drop-in replacement for the stalled DWH in the flash report build.
"""
import json
import os

import requests

GATEWAY_URL = os.environ.get("ERP_GATEWAY_URL", "https://enterprise-api-gateway.ibos.agency/mcp")
# Credentials MUST come from the environment (server-side secret store). No hardcoded defaults.
_ERP_API_KEY = os.environ.get("ERP_API_KEY", "")
_DEVICE_ID = os.environ.get("ERP_DEVICE_ID", "")
if not _ERP_API_KEY or not _DEVICE_ID:
    raise RuntimeError(
        "ERP_API_KEY and ERP_DEVICE_ID must be set in the environment (server-side). "
        "Do not hardcode credentials in source."
    )
HEADERS = {
    "Authorization": f"Bearer {_ERP_API_KEY}",
    "X-Device-Id": _DEVICE_ID,
    "Content-Type": "application/json",
}


def erp_query(sql, limit=500):
    """Run a read-only SQL query against the ERP and return rows as list-of-lists."""
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "execute_readonly_query",
            "arguments": {"sql": sql, "limit": limit},
        },
    }
    r = requests.post(GATEWAY_URL, headers=HEADERS, json=payload, timeout=180)
    r.raise_for_status()
    outer = r.json()
    if "result" not in outer:
        raise RuntimeError(f"ERP gateway error: {outer}")
    content = outer["result"].get("content", [])
    if not content:
        return []
    inner = json.loads(content[0]["text"])
    if "error" in inner:
        raise RuntimeError(f"ERP query error: {inner.get('message') or inner['error']}")
    rows = inner.get("rows", [])
    return [list(row.values()) for row in rows]
