"""Pydantic models for MCP JSON-RPC."""

from pydantic import BaseModel, Field
from typing import Any


# JSON-RPC Protocol

class MCPRequest(BaseModel):
    jsonrpc: str = "2.0"
    method: str
    params: dict[str, Any] = Field(default_factory=dict)
    id: int | str | None = None


class MCPError(BaseModel):
    code: int
    message: str
    data: dict[str, Any] | None = None


class MCPResponse(BaseModel):
    jsonrpc: str = "2.0"
    result: Any | None = None
    error: MCPError | None = None
    id: int | str | None = None


# Tool-specific Params / Results

class DiscoverParams(BaseModel):
    capability: str
    maxPrice: float | None = None
    minTrustScore: float | None = None


class AgentInfo(BaseModel):
    agentId: str
    capabilities: list[str]
    pricePerCall: float
    trustScore: float
    endpointUrl: str
    walletAddress: str


class DiscoverResult(BaseModel):
    agents: list[AgentInfo]
    count: int


class OrderParams(BaseModel):
    agentId: str
    params: dict[str, Any] = Field(default_factory=dict)
    maxPrice: float


class OrderResult(BaseModel):
    orderId: str
    status: str
    escrowTxHash: str | None = None


class VerifyParams(BaseModel):
    orderId: str
    resultHash: str


class VerifyResult(BaseModel):
    status: str
    verified: bool
    txHash: str | None = None


class StatusResult(BaseModel):
    orderId: str
    status: str
    timeline: list[dict[str, Any]]


class RefundResult(BaseModel):
    orderId: str
    status: str
    refunded: bool
    txHash: str | None = None


# Error codes

MCP_ERROR_CODES = {
    "PARSE_ERROR": (-32700, "Parse error"),
    "INVALID_REQUEST": (-32600, "Invalid request"),
    "METHOD_NOT_FOUND": (-32601, "Method not found"),
    "INVALID_PARAMS": (-32602, "Invalid params"),
    "SERVER_ERROR": (-32000, "Server error"),
    "INSUFFICIENT_BALANCE": (-32001, "Insufficient balance"),
    "AGENT_NOT_FOUND": (-32002, "Agent not found"),
    "ORDER_NOT_FOUND": (-32003, "Order not found"),
    "REFUND_NOT_ELIGIBLE": (-32004, "Refund period not elapsed"),
}


def mcp_error(code: int, message: str, data: dict | None = None) -> MCPResponse:
    return MCPResponse(error=MCPError(code=code, message=message, data=data))


def mcp_success(result: Any, req_id: int | str | None = None) -> MCPResponse:
    return MCPResponse(result=result, id=req_id)
