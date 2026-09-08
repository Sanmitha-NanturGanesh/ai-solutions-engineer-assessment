from __future__ import annotations

import asyncio
import json
import logging
import sys
from typing import Any

import mcp.server.stdio
import mcp.types as types
from mcp import MCPError
from mcp.server import Server, ServerRequestContext
from pydantic import ValidationError

from .schemas import GetCustomerRecordInput, TriggerRefundInput

# stdio is the MCP wire. Keeping logging on stderr avoids one of the easiest
# ways to break an otherwise-correct stdio server.
logging.basicConfig(
    stream=sys.stderr,
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("customer-mcp")

CUSTOMERS = {
    "CUST-A1001": {
        "customer_id": "CUST-A1001",
        "name": "Avery Stone",
        "status": "active",
        "tier": "gold",
    },
    "CUST-B2002": {
        "customer_id": "CUST-B2002",
        "name": "Jordan Lee",
        "status": "active",
        "tier": "standard",
    },
}

GET_CUSTOMER_TOOL = types.Tool(
    name="get_customer_record",
    description="Fetch a customer record by customer ID.",
    input_schema=GetCustomerRecordInput.model_json_schema(),
)
REFUND_TOOL = types.Tool(
    name="trigger_refund",
    description="Create a refund request for a customer.",
    input_schema=TriggerRefundInput.model_json_schema(),
)


def invalid_params(exc: ValidationError) -> MCPError:
    # Pydantic's full error object can contain input values. Return only the
    # location/type/message so validation is useful without echoing request data.
    errors = [
        {"loc": list(item["loc"]), "type": item["type"], "msg": item["msg"]}
        for item in exc.errors()
    ]
    return MCPError(
        code=types.INVALID_PARAMS,
        message="Invalid tool parameters",
        data={"validation_errors": errors},
    )


async def list_tools(
    ctx: ServerRequestContext,
    params: types.PaginatedRequestParams | None,
) -> types.ListToolsResult:
    return types.ListToolsResult(tools=[GET_CUSTOMER_TOOL, REFUND_TOOL])


async def call_tool(
    ctx: ServerRequestContext,
    params: types.CallToolRequestParams,
) -> types.CallToolResult:
    arguments: dict[str, Any] = params.arguments or {}

    try:
        if params.name == "get_customer_record":
            request = GetCustomerRecordInput.model_validate(arguments)
            record = CUSTOMERS.get(request.customer_id)
            payload = (
                {"found": True, "record": record}
                if record
                else {"found": False, "customer_id": request.customer_id}
            )

        elif params.name == "trigger_refund":
            request = TriggerRefundInput.model_validate(arguments)
            payload = {
                "status": "accepted",
                "refund_id": f"RF-{request.customer_id[-5:]}",
                "customer_id": request.customer_id,
                "amount": round(request.amount, 2),
                "reason": request.reason,
            }
            logger.info("refund accepted customer=%s amount=%.2f", request.customer_id, request.amount)

        else:
            raise MCPError(code=types.INVALID_PARAMS, message=f"Unknown tool: {params.name}")

    except ValidationError as exc:
        logger.warning("invalid tool arguments tool=%s", params.name)
        raise invalid_params(exc) from exc

    return types.CallToolResult(
        content=[types.TextContent(type="text", text=json.dumps(payload, separators=(",", ":")))],
        structured_content=payload,
    )


server = Server(
    "customer-refund-server",
    version="1.0.0",
    on_list_tools=list_tools,
    on_call_tool=call_tool,
)


async def main() -> None:
    logger.info("starting customer MCP server")
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


if __name__ == "__main__":
    asyncio.run(main())
