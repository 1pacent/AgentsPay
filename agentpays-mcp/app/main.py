"""AgentPays MCP Server -- FastAPI entry point.

Run:  uvicorn app.main:app --reload
"""

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.config import settings
from app.db import init_db
from app.mcp_router import route

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("agentpays")

app = FastAPI(
    title="AgentPays MCP Server",
    description="MCP-compatible agent-to-agent payment server",
    version="0.1.0",
)


@app.on_event("startup")
async def startup():
    logger.info(f"AgentPays starting -- network={settings.network}, mock_contract={settings.mock_contract}")
    init_db()
    logger.info("Database initialized")


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "network": settings.network,
        "mock_contract": settings.mock_contract,
        "version": "0.1.0",
    }


@app.post("/mcp")
async def mcp_endpoint(request: Request):
    """MCP JSON-RPC 2.0 endpoint."""
    body: dict | None = None
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(
            content={"jsonrpc": "2.0", "error": {"code": -32700, "message": "Parse error"}, "id": None},
            status_code=400,
        )
    
    # Validate request shape
    if not isinstance(body, dict) or body.get("jsonrpc") != "2.0":
        return JSONResponse(
            content={"jsonrpc": "2.0", "error": {"code": -32600, "message": "Invalid request"}, "id": body.get("id") if isinstance(body, dict) else None},
            status_code=400,
        )
    
    req_id = body.get("id")
    method = body.get("method", "")
    params = body.get("params", {})
    
    if not method or not isinstance(method, str):
        return JSONResponse(
            content={"jsonrpc": "2.0", "error": {"code": -32600, "message": "Invalid request: method is required"}, "id": req_id},
            status_code=400,
        )
    
    logger.info(f"MCP call: {method} id={req_id}")
    
    try:
        result = route(method, params)
        if result is None:
            return JSONResponse(
                content={"jsonrpc": "2.0", "error": {"code": -32000, "message": "No result"}, "id": req_id},
                status_code=500,
            )
        
        if "error" in result:
            return JSONResponse(
                content={"jsonrpc": "2.0", "error": result["error"], "id": req_id},
                status_code=200,
            )
        
        return JSONResponse(
            content={"jsonrpc": "2.0", "result": result["result"], "id": req_id},
            status_code=200,
        )
    
    except Exception as e:
        logger.exception(f"Unhandled error in {method}")
        return JSONResponse(
            content={"jsonrpc": "2.0", "error": {"code": -32000, "message": "Internal server error"}, "id": req_id},
            status_code=500,
        )
