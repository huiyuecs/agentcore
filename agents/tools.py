"""Agent  Tool definition and implementation.

All Agent tools are concentrated here, The orchestrator is only responsible for:
  1.  Expose tool whitelist based on Agent type
  2.  tool_use returned by executing LLM
  3.  Pass tool results back to LLM

 The tool itself remains deterministic, Testable, and clearly distinguish:
  -  Current request analysis
  -  Technical troubleshooting suggestions
  -  Bill field verification
  -  Manual upgrade summary
  - Shared knowledge base RAG

Order inquiry,Refund execution, Actions such as bill modifications that require authorization from the real business system are not forged here.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, List, Optional, TYPE_CHECKING, Union

if TYPE_CHECKING:
    from agents.agent_orchestrator import Request


AgentToolHandler = Callable[["Request", Dict[str, Any]], Union[Any, Awaitable[Any]]]


@dataclass(frozen=True)
class AgentToolSpec:
    """Agent  Visible tool definition and execution functions."""

    name: str
    description: str
    input_schema: Dict[str, Any]
    handler: AgentToolHandler


def make_tool(
    name: str,
    description: str,
    properties: Dict[str, Any],
    handler: AgentToolHandler,
    required: Optional[List[str]] = None,
) -> AgentToolSpec:
    """ Create Agent tool with JSON Schema."""
    return AgentToolSpec(
        name=name,
        description=description,
        input_schema={
            "type": "object",
            "properties": properties,
            "required": required or [],
            "additionalProperties": False,
        },
        handler=handler,
    )


def inspect_request_context(req: Request, args: Dict[str, Any]) -> Dict[str, Any]:
    """ General customer service tools: Returns the current request snapshot after desensitization."""
    return {
        "intent": req.intent.value if req.intent else None,
        "intent_group": req.intent_group,
        "urgency": req.urgency.name if req.urgency else None,
        "intent_confidence": round(req.intent_confidence, 4),
        "entities": req.entities or {},
        "context_available": bool(req.context),
        "requested_focus": str(args.get("focus", "general"))[:40],
    }


def suggest_required_fields(req: Request, args: Dict[str, Any]) -> Dict[str, Any]:
    """ General customer service tools: Calculate the fields that only need to be asked in the next round by business type."""
    intent = req.intent.value if req.intent else "other"
    fields: List[str] = []
    if intent in {"order_status", "logistics"}:
        fields = ["Order number or order time"]
    elif intent in {"account", "account_security"}:
        fields = ["Login method or account ID", " Problem occurrence time"]
    elif intent in {"complaint", "request"}:
        fields = ["Event time", "Expected processing method"]
    elif intent == "other":
        fields = ["Specific problem you want to solve"]
    return {
        "intent": intent,
        "required_fields": fields,
        "known_entities": req.entities or {},
    }


def lookup_error_code(req: Request, args: Dict[str, Any]) -> Dict[str, Any]:
    """Technical Tools: Explain the troubleshooting directions for common error codes. Does not claim to have read server logs."""
    code = str(args.get("error_code", "")).upper().strip()
    mapping = {
        "401": ("Authentication failed", [" Confirm whether the Token/API Key has expired", " Confirm request timestamp and signature", " Confirm account login status"]),
        "403": (" Insufficient permissions", [" Confirm account or package permissions", " Confirm resource permissions and IP whitelist"]),
        "404": (" Resource or path does not exist", [" Confirm interface path and environment", " Confirm whether the resource identification is correct"]),
        "500": (" Server processing exception", [" Log request_id and occurrence time", " Check dependent services, Parameter format and server log"]),
    }
    meaning, steps = mapping.get(
        code,
        (" Unrecognized error code yet", ["Add complete error message, Occurrence time and operating environment"]),
    )
    return {
        "error_code": code,
        "meaning": meaning,
        "next_steps": steps,
        "server_log_checked": False,
    }


def build_diagnostic_plan(req: Request, args: Dict[str, Any]) -> Dict[str, Any]:
    """Technical Tools: Generate low-risk troubleshooting sequences."""
    environment = str(args.get("environment", "unknown"))[:80]
    reproduced = bool(args.get("reproduced", False))
    steps = [
        " Reproduce and record the complete error message",
        " Confirm network,DNS,Proxy and Certificate",
        "Confirm version, Configuration and Permissions",
    ]
    if reproduced:
        steps.append(" Reproduce with minimum request and record request_id")
    return {
        "environment": environment,
        "reproduced": reproduced,
        "diagnostic_steps": steps,
    }


def check_billing_fields(req: Request, args: Dict[str, Any]) -> Dict[str, Any]:
    """Billing Tools: Check whether the necessary verification fields are complete."""
    fields = {
        "order_id": bool(req.entities.get("order_id")),
        "amount": bool(req.entities.get("amount")),
        "date": bool(req.entities.get("date")),
        "payment_channel": bool(args.get("payment_channel")),
    }
    return {
        "fields": fields,
        "missing_fields": [name for name, present in fields.items() if not present],
        "can_confirm_refund": False,
        "reason": " The current tool only performs field checking. Not connecting to order or payment systems",
    }


def compare_amounts(req: Request, args: Dict[str, Any]) -> Dict[str, Any]:
    """Billing tools: Only do arithmetic between amounts explicitly provided by the user."""
    try:
        first = float(args["amount_a"])
        second = float(args["amount_b"])
    except (KeyError, TypeError, ValueError):
        return {"success": False, "error": "amount_a  and amount_b must be numbers"}
    return {
        "success": True,
        "amount_a": first,
        "amount_b": second,
        "difference": round(first - second, 2),
        "interpretation": " only represents the amount difference, does not represent the conclusion of repeated deductions or refunds",
    }


def create_handoff_summary(req: Request, args: Dict[str, Any]) -> Dict[str, Any]:
    """Upgrade tools: Generate structured snippets that can be handed to human agents."""
    return {
        "request_id": req.request_id,
        "reason": str(args.get("reason", " Manual customer service is required to continue verification"))[:120],
        "intent": req.intent.value if req.intent else "unknown",
        "urgency": req.urgency.name if req.urgency else "UNKNOWN",
        "entities": req.entities or {},
        "sensitive_data_required": False,
    }


def build_shared_rag_tools(tool_manager: Any) -> Dict[str, AgentToolSpec]:
    """ Build a RAG tool that can be shared by all Agents."""

    async def search_knowledge_base(req: Request, args: Dict[str, Any]) -> Dict[str, Any]:
        query = str(args.get("query") or req.message or "").strip()
        top_k = int(args.get("top_k", 5) or 5)
        if not query:
            return {"success": False, "error": "query  cannot be empty", "results": []}
        if tool_manager is None:
            return {"success": False, "error": "RAG  Tool not initialized", "results": []}

        result = await tool_manager.search_with_rewrite(
            "knowledge_search",
            query,
            top_k=top_k,
        )
        if not getattr(result, "success", False):
            return {
                "success": False,
                "query": query,
                "error": getattr(result, "error", " Knowledge base search failed"),
                "results": [],
                "reranked": False,
            }

        return {
            "success": True,
            "query": query,
            "top_k": top_k,
            "results": result.data,
            "reranked": bool(getattr(result, "reranked", False)),
        }

    return {
        "search_knowledge_base": make_tool(
            "search_knowledge_base",
            " Search the knowledge base and return the most relevant document fragments; Can be used for general, Technology, Billing and upgrade scenarios.",
            {
                "query": {"type": "string", "description": " User question or search keyword"},
                "top_k": {"type": "integer", "description": "Number of results returned"},
            },
            search_knowledge_base,
            required=["query"],
        )
    }


def general_tools() -> Dict[str, AgentToolSpec]:
    return {
        "inspect_request_context": make_tool(
            "inspect_request_context",
            " View the intent of the current request, Urgency, Entity and context availability; Do not query external business systems.",
            {"focus": {"type": "string", "description": " The business direction you want to pay attention to"}},
            inspect_request_context,
        ),
        "suggest_required_fields": make_tool(
            "suggest_required_fields",
            " Suggest fields that only need to be supplemented to the user in the next round based on the current intent.",
            {},
            suggest_required_fields,
        ),
    }


def technical_tools() -> Dict[str, AgentToolSpec]:
    return {
        "lookup_error_code": make_tool(
            "lookup_error_code",
            " Explain the possible meanings and low-risk troubleshooting directions of common HTTP error codes; Server log will not be read.",
            {"error_code": {"type": "string", "description": "For example 401,403,500"}},
            lookup_error_code,
            required=["error_code"],
        ),
        "build_diagnostic_plan": make_tool(
            "build_diagnostic_plan",
            " Generate a troubleshooting sequence based on the operating environment and whether it is reproducible. Operations such as modifying the configuration are not performed.",
            {
                "environment": {"type": "string", "description": "App, Browser, Server or Docker, etc."},
                "reproduced": {"type": "boolean", "description": " Whether the problem can be reproduced stably"},
            },
            build_diagnostic_plan,
            required=["environment", "reproduced"],
        ),
    }


def billing_tools() -> Dict[str, AgentToolSpec]:
    return {
        "check_billing_fields": make_tool(
            "check_billing_fields",
            " Check whether the bill verification fields are complete;Do not connect orders, Payment or refund system.",
            {"payment_channel": {"type": "string", "description": " Payment channel,For example, WeChat,Alipay,Bank card"}},
            check_billing_fields,
        ),
        "compare_amounts": make_tool(
            "compare_amounts",
            " Calculate the difference between the two amounts explicitly provided by the user; Does not determine whether repeated deductions are made. Refunds are not performed either.",
            {
                "amount_a": {"type": "number", "description": "First amount"},
                "amount_b": {"type": "number", "description": " The second amount"},
            },
            compare_amounts,
            required=["amount_a", "amount_b"],
        ),
    }


def escalation_tools() -> Dict[str, AgentToolSpec]:
    return {
        "create_handoff_summary": make_tool(
            "create_handoff_summary",
            " Generate a structured handover summary for human customer service, No real ticket will be created.",
            {"reason": {"type": "string", "description": " Reason for upgrading"}},
            create_handoff_summary,
        ),
    }
