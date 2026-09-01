"""
 Highlights:Multi-Agent routing and orchestration

 Core question: How to do routing in the case of multiple agents?

 Routing Policy (Three levels of decision-making):
  1.  Intent Routing ——  Directly mapped to dedicated Agent based on IntentCategory
  2. Performance Routing ——  When there are multiple Agents of the same type, has the highest selection success rate, Lowest latency
  3.  Downgrade routing ——  When the dedicated Agent is unavailable, Automatic downgrade to GeneralAgent

 Parallel collaboration:
  -  Complex problem ( Such as"Technical issues + billing issues") Can be distributed to multiple Agents at the same time
  -  Results are merged and returned by Orchestrator

Upgrade mechanism:
  - Agent  Confidence below threshold →  Automatically upgrade to a higher-level Agent or switch to manual
"""
import asyncio
import inspect
import json
import logging
import os
import time
import uuid
from collections import deque
from datetime import datetime
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from anthropic import AsyncAnthropic

from agents.tools import (
    AgentToolSpec,
    build_shared_rag_tools,
    billing_tools,
    escalation_tools,
    general_tools,
    technical_tools,
)
from core.intent_recognizer import IntentCategory, IntentRecognizer, UrgencyLevel
from core.llm_utils import extract_text_content

logger = logging.getLogger(__name__)


# ── Data structure ──────────────────────────────────────────────────────────────────

class AgentType(Enum):
    GENERAL   = "general"    #  General customer service
    TECHNICAL = "technical"  # Technical Support
    BILLING   = "billing"    # Billing/Refund
    ESCALATION = "escalation" #  Manual upgrade and handover


@dataclass(frozen=True)
class AgentProfile:

    role: str
    mission: str
    workflow: Tuple[str, ...]
    input_contract: Tuple[str, ...]
    output_contract: Tuple[str, ...]
    handoff_conditions: Tuple[str, ...] = ()
    tool_scope: Tuple[str, ...] = ()
    model: Optional[str] = None
    temperature: float = 0.2
    max_tokens: int = 1024


def _env_float(name: str, default: float) -> float:
    """ Read optional floating point configuration; Misconfiguration should not block service startup."""
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        logger.warning("Ignore illegal floating point configuration %s=%r", name, os.getenv(name))
        return default


def _env_int(name: str, default: int) -> int:
    """ Read optional integer configuration; Misconfiguration should not block service startup."""
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        logger.warning("Ignore illegal integer configuration %s=%r", name, os.getenv(name))
        return default


@dataclass
class AgentStats:
    """Agent  Runtime statistics, For use by monitors and routing decisions."""
    total:     int   = 0
    success:   int   = 0
    total_ms:  float = 0.0
    monitor_penalty: float = 0.0

    @property
    def success_rate(self) -> float:
        return self.success / self.total if self.total else 1.0

    @property
    def avg_ms(self) -> float:
        return self.total_ms / self.total if self.total else 0.0

    def routing_score(self) -> float:
        """ Route Rating:High success rate, Agents with low latency have high scores."""
        latency_score = 1.0 / (1.0 + self.avg_ms / 1000)
        base_score = self.success_rate * 0.7 + latency_score * 0.3
        return base_score * max(0.0, 1.0 - self.monitor_penalty)


@dataclass
class AgentResponse:
    agent_type:  AgentType
    content:     str
    success:     bool
    confidence:  float = 1.0
    latency_ms:  float = 0.0
    escalate:    bool  = False   # Whether it is necessary to upgrade
    tools_used:  List[str] = field(default_factory=list)
    tool_traces: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class Request:
    message:     str
    user_id:     str
    conv_id:     str
    context:     str = ""        #  Formatting context from MemoryManager
    history:     Optional[List[Dict[str, str]]] = None  #  Conversation History, Pass to intent recognition
    entities:    Dict[str, List[str]] = field(default_factory=dict)
    intent:      Optional[IntentCategory] = None
    intent_group: Optional[str] = None
    urgency:     Optional[UrgencyLevel]   = None
    intent_confidence: float = 1.0
    request_id:  str = field(default_factory=lambda: str(uuid.uuid4())[:8])


@dataclass
class OrchestratorResult:
    request_id:  str
    response:    str
    agent_type:  AgentType
    intent:      Optional[IntentCategory]
    escalated:   bool  = False
    latency_ms:  float = 0.0
    agent_types: List[AgentType] = field(default_factory=list)
    primary_agent: Optional[AgentType] = None
    supporting_agents: List[AgentType] = field(default_factory=list)
    tools_used: List[str] = field(default_factory=list)
    tool_traces: List[Dict[str, Any]] = field(default_factory=list)
    routing_reason: str = ""
    routing_confidence: float = 0.0


@dataclass
class RoutingDecision:
    """ Structured routing decisions for one request."""
    primary_agent: AgentType
    supporting_agents: List[AgentType] = field(default_factory=list)
    reason: str = ""
    confidence: float = 0.0

    @property
    def agent_types(self) -> List[AgentType]:
        return [self.primary_agent] + self.supporting_agents

    @property
    def multi_agent(self) -> bool:
        return bool(self.supporting_agents)


# ── Basic Agent ────────────────────────────────────────────────────────────────

class BaseAgent:
    """ Base class for all Agents, Encapsulating LLM calls, Character Contracts and Statistics."""

    agent_type: AgentType
    system_prompt: str
    profile: AgentProfile

    def __init__(
        self,
        client: AsyncAnthropic,
        model: str,
        skill_manager: Optional[Any] = None,
        profile: Optional[AgentProfile] = None,
    ):
        self._client = client
        self.profile = profile or self.profile
        self._model  = self.profile.model or model
        self._skill_manager = skill_manager
        self.stats   = AgentStats()
        self._last_tools_used: List[str] = []
        self._last_tool_traces: List[Dict[str, Any]] = []
        self._shared_tools: Dict[str, AgentToolSpec] = {}

    def get_tools(self) -> Dict[str, AgentToolSpec]:
        """ Returns the whitelist of tools that can actually be called by this role."""
        return dict(self._shared_tools)

    def set_shared_tools(self, tools: Optional[Dict[str, AgentToolSpec]]) -> None:
        self._shared_tools = dict(tools or {})

    async def handle(self, req: Request) -> AgentResponse:
        t0 = time.monotonic()
        self.stats.total += 1
        self._last_tools_used = []
        self._last_tool_traces = []
        try:
            content = await self._call_llm(req)
            ms = (time.monotonic() - t0) * 1000
            self.stats.success += 1
            self.stats.total_ms += ms
            escalate = self._needs_escalation(content)
            return AgentResponse(
                agent_type=self.agent_type,
                content=content,
                success=True,
                latency_ms=ms,
                escalate=escalate,
                tools_used=list(self._last_tools_used),
                tool_traces=list(self._last_tool_traces),
            )
        except Exception as ex:
            ms = (time.monotonic() - t0) * 1000
            self.stats.total_ms += ms
            logger.error(f"{self.agent_type.value}  Processing failed: {ex}")
            return AgentResponse(
                agent_type=self.agent_type,
                content="Sorry, There was a problem processing your request. Please try again later.",
                success=False,
                latency_ms=ms,
                tool_traces=list(self._last_tool_traces),
            )

    async def _call_llm(self, req: Request) -> str:
        def _clean(s: str) -> str:
            return s.encode("utf-8", errors="ignore").decode("utf-8")

        messages = []
        if req.context:
            messages.append({"role": "user", "content": f"[ Background information]\n{_clean(req.context)}"})
            messages.append({"role": "assistant", "content": "Okay,I understand the background information."})
        if req.entities:
            entities_text = json.dumps(req.entities, ensure_ascii=False)
            messages.append({"role": "user", "content": f"[ Structured Entity]\n{_clean(entities_text)}"})
            messages.append({"role": "assistant", "content": "Okay, I will combine these structured entity processing."})
        role_packet = self._build_role_packet(req)
        if role_packet:
            messages.append({"role": "user", "content": f"[Character input contract]\n{_clean(role_packet)}"})
            messages.append({"role": "assistant", "content": "Okay, I will follow the input and output contracts for this character."})
        messages.append({"role": "user", "content": _clean(req.message)})

        tools = self.get_tools()
        tools_used: List[str] = []
        tool_traces: List[Dict[str, Any]] = []
        for _ in range(3):
            request_kwargs: Dict[str, Any] = {
                "model": self._model,
                "max_tokens": self.profile.max_tokens,
                "temperature": self.profile.temperature,
                "system": self._build_system_prompt(req),
                "messages": messages,
            }
            if tools:
                request_kwargs["tools"] = [
                    {
                        "name": spec.name,
                        "description": spec.description,
                        "input_schema": spec.input_schema,
                    }
                    for spec in tools.values()
                ]
            resp = await self._client.messages.create(**request_kwargs)
            tool_uses = [block for block in (resp.content or []) if self._block_type(block) == "tool_use"]
            if not tool_uses:
                self._last_tools_used = tools_used
                return extract_text_content(resp.content)

            messages.append({"role": "assistant", "content": resp.content})
            tool_results = []
            for block in tool_uses:
                name = self._block_value(block, "name")
                tool_use_id = self._block_value(block, "id")
                args = self._block_value(block, "input") or {}
                spec = tools.get(name)
                tool_t0 = time.monotonic()
                call_success = True
                result_success: Optional[bool] = None
                error_text = ""
                if spec is None:
                    call_success = False
                    result: Any = {"success": False, "error": f"Tool is not there {self.agent_type.value} Agent  Whitelisted"}
                    error_text = result["error"]
                else:
                    try:
                        self._validate_tool_input(spec, args)
                        result = spec.handler(req, args)
                        if inspect.isawaitable(result):
                            result = await result
                        tools_used.append(name)
                        if isinstance(result, dict) and "success" in result:
                            result_success = bool(result.get("success"))
                    except Exception as ex:
                        call_success = False
                        logger.warning("Agent  Tool %s failed to execute: %s", name, ex)
                        error_text = str(ex)
                        result = {"success": False, "error": error_text}
                tool_latency_ms = (time.monotonic() - tool_t0) * 1000
                if not error_text and isinstance(result, dict):
                    error_text = str(result.get("error", "") or "")
                tool_traces.append(
                    {
                        "agent_type": self.agent_type.value,
                        "tool_name": name,
                        "tool_use_id": tool_use_id,
                        "input": dict(args),
                        "success": call_success,
                        "result_success": result_success,
                        "latency_ms": round(tool_latency_ms, 1),
                        "cached": bool(result.get("cached")) if isinstance(result, dict) else False,
                        "reranked": bool(result.get("reranked")) if isinstance(result, dict) else False,
                        "error": error_text,
                    }
                )
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_use_id,
                    "content": json.dumps(result, ensure_ascii=False),
                })
            messages.append({"role": "user", "content": tool_results})

        self._last_tools_used = tools_used
        self._last_tool_traces = tool_traces
        raise RuntimeError(f"{self.agent_type.value}  Tool call exceeds maximum number of rounds")

    @staticmethod
    def _block_type(block: Any) -> Optional[str]:
        if isinstance(block, dict):
            return block.get("type")
        return getattr(block, "type", None)

    @staticmethod
    def _block_value(block: Any, key: str) -> Any:
        if isinstance(block, dict):
            return block.get(key)
        return getattr(block, key, None)

    @staticmethod
    def _validate_tool_input(spec: AgentToolSpec, args: Any) -> None:
        if not isinstance(args, dict):
            raise ValueError(" Tool parameters must be JSON objects")
        schema = spec.input_schema
        for field_name in schema.get("required", []):
            if field_name not in args:
                raise ValueError(f" Required parameter missing: {field_name}")
        properties = schema.get("properties", {})
        unknown = set(args) - set(properties)
        if unknown and schema.get("additionalProperties") is False:
            raise ValueError(f" Tool parameter not allowed: {', '.join(sorted(unknown))}")
        type_map = {"string": str, "number": (int, float), "integer": int, "boolean": bool}
        for key, value in args.items():
            expected = properties.get(key, {}).get("type")
            if expected in type_map and not isinstance(value, type_map[expected]):
                raise ValueError(f" Parameters {key}  Type error,Expectation {expected}")

    def _build_system_prompt(self, req: Request) -> str:
        """ Integrate character contracts and dynamic Skills into the system prompt."""
        profile_prompt = (
            f"\n\n[Character Contract]\n"
            f" Role:{self.profile.role}\n"
            f" Responsibilities:{self.profile.mission}\n"
            f" Processing flow:{' -> '.join(self.profile.workflow)}\n"
            f" Available inputs:{';'.join(self.profile.input_contract)}\n"
            f" Output requirements:{';'.join(self.profile.output_contract)}\n"
            f"Upgrade conditions:{';'.join(self.profile.handoff_conditions) or ' None, Processed according to general customer service rules'}\n"
            f" Allowed data/tool range:{','.join(self.profile.tool_scope) or ' Only use current request context'}\n"
            " Do not claim to have executed a query that was not provided, Modification or refund operation; Clearly indicate the need for verification when evidence is lacking."
        )
        base_prompt = f"{self.system_prompt}{profile_prompt}"
        if self._skill_manager is None:
            return base_prompt
        skill_prompt = self._skill_manager.prompt_for(req.message, self.agent_type.value)
        if not skill_prompt:
            return base_prompt
        return f"{base_prompt}\n\n[Dynamic Skills]\n{skill_prompt}"

    def _build_role_packet(self, req: Request) -> str:
        """ Deterministic input package for child Agent; Subclasses can supplement domain fields."""
        packet = {
            "agent_type": self.agent_type.value,
            "intent": req.intent.value if req.intent else None,
            "intent_group": req.intent_group,
            "urgency": req.urgency.name if req.urgency else None,
            "intent_confidence": round(req.intent_confidence, 4),
            "available_entities": req.entities or {},
        }
        return json.dumps(packet, ensure_ascii=False)

    def _needs_escalation(self, content: str) -> bool:
        """ Check whether the Agent recommends upgrading ( Simple keyword detection)."""
        keywords = [" Convert to manual", "Manual customer service", "escalate", "specialist", " Unable to process"]
        return any(kw in content for kw in keywords)


class GeneralAgent(BaseAgent):
    agent_type    = AgentType.GENERAL
    profile = AgentProfile(
        role=" General customer service triage and first round of reception",
        mission=" Quickly answer basic questions, Clarify incomplete requirements, and identify whether professional Agent or manual processing is required.",
        workflow=("Restate the appeal", " Determine business scope", " Answer directly or add necessary information", " Give next step"),
        input_contract=("Conversation History", " User portrait", " Intention and urgency", "Knowledge Base Context"),
        output_contract=("Respond to the core question first", " Only ask for necessary fields when there is insufficient information", " Clarify next steps and boundaries"),
        handoff_conditions=(" involves permissions,Funds, Privacy or Complex Complaint", " User explicitly requested manual"),
        tool_scope=("search_knowledge_base", "inspect_request_context", "suggest_required_fields"),
        temperature=0.3,
        max_tokens=900,
    )
    system_prompt = (
        "You are AgentCore intelligent customer service. Friendly, Answer user questions concisely."
        " If the problem is beyond your capabilities, Clearly explain and recommend transferring to professional customer service."
    )

    def _build_role_packet(self, req: Request) -> str:
        packet = json.loads(super()._build_role_packet(req))
        packet["triage_targets"] = ["technical", "billing", "escalation"]
        packet["response_mode"] = "answer_or_clarify"
        return json.dumps(packet, ensure_ascii=False)

    def get_tools(self) -> Dict[str, AgentToolSpec]:
        tools = super().get_tools()
        tools.update(general_tools())
        return tools


class TechnicalAgent(BaseAgent):
    agent_type    = AgentType.TECHNICAL
    profile = AgentProfile(
        role=" Technical fault diagnosis and troubleshooting",
        mission="Based on error code, Environmental and recurrence information narrows the root cause, gives low risk, Verifiable troubleshooting steps.",
        workflow=(" Confirm the phenomenon", " Determine the scope of influence", "Troubleshoot by network/permission/configuration/dependency", " Give verification method", " Determine upgrade conditions"),
        input_contract=(" Error code", " Problem occurrence time", " Operating environment", " Scope of influence", " Recent changes", "Knowledge Base Context"),
        output_contract=(" Phenomenon retelling", " Possible reasons", " Number troubleshooting steps", " Verification results", " Additional information needed"),
        handoff_conditions=(" Large production area is not available", " Data loss or abnormal permissions", "Need background log, Database or manual operation"),
        tool_scope=("search_knowledge_base", "lookup_error_code", "build_diagnostic_plan"),
        temperature=0.1,
        max_tokens=1200,
    )
    system_prompt = (
        "You are a technical support expert. Focus on: Troubleshooting,Error diagnosis, System configuration."
        " Provide clear step-by-step solutions. Encountered a problem that requires background operations, Indicates that upgrade processing is required."
    )

    def _build_role_packet(self, req: Request) -> str:
        packet = json.loads(super()._build_role_packet(req))
        packet["diagnostic_fields"] = {
            "error_codes": req.entities.get("error_code", []),
            "environment_hint": " Please confirm device,System, version,Network",
            "risk_boundary": " Must not require password,Verification code, Complete key; Destructive actions must not be recommended",
        }
        return json.dumps(packet, ensure_ascii=False)

    def get_tools(self) -> Dict[str, AgentToolSpec]:
        tools = super().get_tools()
        tools.update(technical_tools())
        return tools


class BillingAgent(BaseAgent):
    agent_type    = AgentType.BILLING
    profile = AgentProfile(
        role="Bill verification and after-sales processing",
        mission=" Differentiate deductions,Refund,Invoice, Subscription and other funding scenarios,Explanation can determine the facts, And clarify the boundaries between verification and manual review.",
        workflow=(" Confirm bill scenario", " Collect necessary verification fields", " Distinguish between order/actual payment/refund amount", " Explain the processing path and timeliness", " Determine whether to upgrade"),
        input_contract=("Order number", "Amount and currency", "Payment time", "Payment channel", " User expectations", "Knowledge Base Context"),
        output_contract=(" Information that needs to be verified", "Currently judgeable content", "Next step processing path", " Aging boundary"),
        handoff_conditions=(" Actual refund or compensation", " Repeated deduction or payment is successful but the order does not take effect", " Invoice voided/reissued", "Enterprise contract or large order"),
        tool_scope=("search_knowledge_base", "check_billing_fields", "compare_amounts"),
        temperature=0.0,
        max_tokens=1100,
    )
    system_prompt = (
        "You are a billing service expert. Focus on:Bill inquiry,Refund application,Invoice problem, Subscription management."
        "Remain accurate and professional regarding financial matters. When it comes to actual refund operations, Description requires manual review."
    )

    def _build_role_packet(self, req: Request) -> str:
        packet = json.loads(super()._build_role_packet(req))
        packet["verification_fields"] = {
            "order_id": req.entities.get("order_id", []),
            "amount": req.entities.get("amount", []),
            "date": req.entities.get("date", []),
            "missing_fields": [
                field for field, values in (
                    (" Order number or transaction number", req.entities.get("order_id", [])),
                    (" Payment amount", req.entities.get("amount", [])),
                ) if not values
            ],
            "risk_boundary": " Do not promise successful refund, Get the account immediately or modify the bill directly",
        }
        return json.dumps(packet, ensure_ascii=False)

    def get_tools(self) -> Dict[str, AgentToolSpec]:
        tools = super().get_tools()
        tools.update(billing_tools())
        return tools


class EscalationAgent(BaseAgent):
    """ Manually upgrade nodes.

     Upgrading is not an ordinary Q&A Prompt: It should generate standardized handover messages and stop common
    Agent  Keep making up answers. The production environment can receive the work order system here, Manual queue or webhook.
    """

    agent_type = AgentType.ESCALATION
    profile = AgentProfile(
        role=" Manual upgrade and handover",
        mission=" Confirm the reason for the upgrade, Organize known context, Inform the user of the next step, Do not perform unauthorized business operations.",
        workflow=(" Confirm reason for upgrade", " Organize known information", " Mark priority", " Generate handover summary"),
        input_contract=(" User message", " Intention", " Urgency", " Structured Entity", " Dialogue background"),
        output_contract=(" Reason for upgrade", " Summary of known information", " Additional information is needed", " Conservative follow-up instructions"),
        handoff_conditions=(" User explicitly requested manual", " Emergency or high-risk scenario"),
        tool_scope=("search_knowledge_base", "create_handoff_summary"),
        temperature=0.0,
        max_tokens=500,
    )
    system_prompt = " You are responsible for manual upgrade handover from customer service. Do not continue simulating completed background operations."

    def get_tools(self) -> Dict[str, AgentToolSpec]:
        tools = super().get_tools()
        tools.update(escalation_tools())
        return tools

    async def handle(self, req: Request) -> AgentResponse:
        t0 = time.monotonic()
        self.stats.total += 1
        intent = req.intent.value if req.intent else "unknown"
        urgency = req.urgency.name if req.urgency else "UNKNOWN"
        entities = json.dumps(req.entities or {}, ensure_ascii=False)
        content = (
            "I have marked this issue for manual escalation.\n\n"
            f"Escalation reason: intent={intent}, urgency={urgency}\n"
            f"Recorded context: {entities}\n"
            "Do not send passwords, verification codes, or complete payment credentials. "
            "A support specialist will continue from the recorded conversation."
        )
        ms = (time.monotonic() - t0) * 1000
        self.stats.success += 1
        self.stats.total_ms += ms
        return AgentResponse(
            agent_type=self.agent_type,
            content=content,
            success=True,
            latency_ms=ms,
            escalate=True,
            tools_used=[],
        )


class ResponseComposer:
    """Merge primary and supporting agent results into one bounded response."""

    def __init__(self, client: AsyncAnthropic, model: str, skill_manager: Optional[Any] = None):
        self._client = client
        self._model = model
        self._skill_manager = skill_manager

    async def compose(self, req: Request, responses: List[AgentResponse]) -> str:
        successful = [response for response in responses if response.success and response.content.strip()]
        if not successful:
            return "Sorry, Processing failed for all Agents."
        if len(successful) == 1:
            return successful[0].content

        evidence = "\n\n".join(
            f"[{response.agent_type.value} Agent Output]\n{response.content}"
            for response in successful
        )
        prompt = (
            "You are a customer-support response composer. Merge the specialist results into one final reply.\n"
            "Prioritize the user's questions and the primary agent's conclusion. Remove duplicate or conflicting statements. "
            "Never invent order, refund, or backend-query results. When conclusions conflict, state that verification is required. "
            "Preserve necessary diagnostic steps, verification fields, and escalation boundaries. "
            "Respond in professional English and do not expose internal agent names.\n\n"
            f"Primary agent: {successful[0].agent_type.value}\n"
            f"User question: {req.message}\n"
            f"Candidate results:\n{evidence}"
        )
        if self._skill_manager is not None:
            skill = self._skill_manager.prompt_for(req.message, "general")
            if skill:
                prompt += f"\n\n[General customer-support policy]\n{skill}"
        try:
            response = await self._client.messages.create(
                model=self._model,
                max_tokens=_env_int("AGENTCORE_COMPOSER_MAX_TOKENS", 1000),
                temperature=_env_float("AGENTCORE_COMPOSER_TEMPERATURE", 0.1),
                messages=[{"role": "user", "content": prompt}],
            )
            content = extract_text_content(response.content).strip()
            if content:
                return content
        except Exception as ex:
            logger.warning("Response composer failed; using deterministic merge: %s", ex)

        # Preserve every successful result when the composer is unavailable.
        return "\n\n".join(
            f"{response.content}" if index == 0 else f"Additional instructions:\n{response.content}"
            for index, response in enumerate(successful)
        )


# ── Organizer ────────────────────────────────────────────────────────────────────

class AgentOrchestrator:
    """
     Multi-Agent Orchestrator.

     Routing Logic (Three layers):
      1.  Intention → Agent Type mapping
      2.  When there are multiple instances of the same type, press routing_score() Choose the best
      3.  Downgrade to GeneralAgent when dedicated Agent fails
    """

    #  Intention → Agent  Static mapping of type ( Routing table)
    _INTENT_ROUTING: Dict[IntentCategory, AgentType] = {
        IntentCategory.TECHNICAL:  AgentType.TECHNICAL,
        IntentCategory.TECHNICAL_LOGIN: AgentType.TECHNICAL,
        IntentCategory.TECHNICAL_CRASH: AgentType.TECHNICAL,
        IntentCategory.BILLING:    AgentType.BILLING,
        IntentCategory.REFUND:     AgentType.BILLING,
        IntentCategory.INVOICE:    AgentType.BILLING,
        IntentCategory.PAYMENT_ISSUE: AgentType.BILLING,
        IntentCategory.ACCOUNT:    AgentType.BILLING,
        IntentCategory.ACCOUNT_SECURITY: AgentType.BILLING,
        IntentCategory.ESCALATION: AgentType.ESCALATION,
        IntentCategory.HUMAN_HANDOFF: AgentType.ESCALATION,
        #  Rest of intentions → GENERAL(Default)
    }

    def __init__(
        self,
        api_key:  str,
        base_url: Optional[str] = None,
        model:    str = "claude-3-5-sonnet-20241022",
        skill_manager: Optional[Any] = None,
        rag_tool_manager: Optional[Any] = None,
    ):
        kwargs: Dict[str, Any] = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        client = AsyncAnthropic(**kwargs)

        self._intent_recognizer = IntentRecognizer(api_key=api_key, base_url=base_url, model=model)
        self._skill_manager = skill_manager
        self._composer = ResponseComposer(client, model, skill_manager)
        self._shared_tools: Dict[str, AgentToolSpec] = {}
        self._recent_tool_traces = deque(maxlen=_env_int("AGENTCORE_TOOL_TRACE_MAX", 200))

        # Agent  Pool: There can be multiple instances of each type ( Horizontal expansion)
        self._pool: Dict[AgentType, List[BaseAgent]] = {
            AgentType.GENERAL: [self._make_agent(GeneralAgent, client, model, skill_manager)],
            AgentType.TECHNICAL: [self._make_agent(TechnicalAgent, client, model, skill_manager)],
            AgentType.BILLING: [self._make_agent(BillingAgent, client, model, skill_manager)],
            AgentType.ESCALATION: [self._make_agent(EscalationAgent, client, model, skill_manager)],
        }
        self.set_shared_tools(build_shared_rag_tools(rag_tool_manager))

    @staticmethod
    def _make_agent(
        agent_cls: type[BaseAgent],
        client: AsyncAnthropic,
        default_model: str,
        skill_manager: Optional[Any],
    ) -> BaseAgent:
        """ Create Agent by role, and allows overriding the character's model with environment variables.

         Stronger models can be used, Faster model available for universal reception, Upgrading the node itself does not require calling LLM.
        """
        profile = agent_cls.profile
        env_name = f"AGENTCORE_{agent_cls.agent_type.value.upper()}_MODEL"
        model = os.getenv(env_name, "").strip() or profile.model
        configured_profile = replace(profile, model=model) if model else profile
        return agent_cls(client, default_model, skill_manager, profile=configured_profile)

    def set_skill_manager(self, skill_manager: Optional[Any]) -> None:
        """ Update SkillManager reference, For use by runtime overloading or test replacement."""
        self._skill_manager = skill_manager
        self._composer._skill_manager = skill_manager
        for agents in self._pool.values():
            for agent in agents:
                agent._skill_manager = skill_manager

    def set_shared_tools(self, tools: Optional[Dict[str, AgentToolSpec]]) -> None:
        """ Update tool whitelist shared by all Agents."""
        self._shared_tools = dict(tools or {})
        for agents in self._pool.values():
            for agent in agents:
                agent.set_shared_tools(self._shared_tools)

    async def recognize_intent(
        self,
        message: str,
        history: Optional[List[Dict[str, str]]] = None,
    ):
        """ External exposure intention identification, It is for the API layer to first determine whether pre-requisite capabilities such as RAG are needed."""
        return await self._intent_recognizer.recognize(message, history=history)

    def _record_tool_trace(self, result: OrchestratorResult) -> None:
        trace = {
            "request_id": result.request_id,
            "timestamp": datetime.now().isoformat(),
            "intent": result.intent.value if result.intent else None,
            "primary_agent": result.primary_agent.value if result.primary_agent else None,
            "supporting_agents": [agent.value for agent in result.supporting_agents],
            "tools_used": list(result.tools_used),
            "tool_calls": list(result.tool_traces),
            "escalated": result.escalated,
            "latency_ms": round(result.latency_ms, 1),
        }
        self._recent_tool_traces.append(trace)

    def get_tool_trace(self, request_id: str) -> Optional[Dict[str, Any]]:
        for trace in reversed(self._recent_tool_traces):
            if trace.get("request_id") == request_id:
                return trace
        return None

    def get_recent_tool_traces(self, limit: int = 20) -> List[Dict[str, Any]]:
        if not self._recent_tool_traces:
            return []
        limit = max(1, min(int(limit or 20), len(self._recent_tool_traces)))
        return list(reversed(list(self._recent_tool_traces)[-limit:]))

    # ──  Main entrance ────────────────────────────────────────────────────────────────

    async def run(self, req: Request) -> OrchestratorResult:
        """
         The complete process of processing a request:
           Intent recognition →  Route selection Agent → Execute →  Check for upgrade → Return results
        """
        t0 = time.monotonic()

        # 1.  Intent Recognition ( Skip if caller already recognized)
        if req.intent is None:
            intent_result = await self._intent_recognizer.recognize(req.message, history=req.history)
            req.intent  = intent_result.intent
            req.intent_group = intent_result.intent_group
            req.urgency = intent_result.urgency
            req.intent_confidence = intent_result.confidence

        if self._needs_clarification(req):
            result = OrchestratorResult(
                request_id=req.request_id,
                response="I'm not sure yet what type of problem you're dealing with. Please add that it is order logistics,Refund bill,Account information, Or is it a technical fault?",
                agent_type=AgentType.GENERAL,
                intent=req.intent,
                escalated=False,
                latency_ms=(time.monotonic() - t0) * 1000,
                agent_types=[AgentType.GENERAL],
                primary_agent=AgentType.GENERAL,
                routing_reason="Low confidence OTHER intent, Clarify user needs first",
                routing_confidence=req.intent_confidence,
            )
            self._record_tool_trace(result)
            return result

        #  Automatic parallel collaboration on complex problems, For example, the same sentence involves both login failure and deduction/refund.
        decision = self._route_decision(req)
        if decision.multi_agent:
            return await self.run_parallel(req, decision)

        # 2.  Execute the main Agent ( including downgrade)
        response = await self._execute(req, decision.primary_agent)

        # 4. Upgrade check
        escalated = False
        if response.escalate or req.urgency == UrgencyLevel.CRITICAL or req.intent in (
            IntentCategory.ESCALATION,
            IntentCategory.HUMAN_HANDOFF,
        ):
            escalated = True
            logger.warning(f" Request {req.request_id}  Trigger upgrade: urgency={req.urgency}")
            #  Production environment: Create a work order here, Notify human customer service

        result = OrchestratorResult(
            request_id=req.request_id,
            response=response.content,
            agent_type=response.agent_type,
            intent=req.intent,
            escalated=escalated,
            latency_ms=(time.monotonic() - t0) * 1000,
            agent_types=[response.agent_type],
            primary_agent=decision.primary_agent,
            supporting_agents=[],
            tools_used=list(response.tools_used),
            tool_traces=list(response.tool_traces),
            routing_reason=decision.reason,
            routing_confidence=decision.confidence,
        )
        self._record_tool_trace(result)
        return result

    async def run_parallel(self, req: Request, decision: RoutingDecision) -> OrchestratorResult:
        """
         Distributed to multiple Agents in parallel, Merge results.
         Suitable for complex problems ( If both technical and billing are involved).
        """
        t0 = time.monotonic()
        agent_types = decision.agent_types
        tasks = [self._execute(req, at) for at in agent_types]
        responses = await asyncio.gather(*tasks, return_exceptions=True)

        valid_responses = [r for r in responses if isinstance(r, AgentResponse)]
        combined = await self._composer.compose(req, valid_responses)
        escalated = any(isinstance(r, AgentResponse) and r.escalate for r in responses)
        tools_used = list(dict.fromkeys(
            tool_name
            for response in valid_responses
            for tool_name in response.tools_used
        ))
        tool_traces = [
            trace
            for response in valid_responses
            for trace in response.tool_traces
        ]
        result = OrchestratorResult(
            request_id=req.request_id,
            response=combined,
            agent_type=decision.primary_agent,
            intent=req.intent,
            escalated=escalated,
            latency_ms=(time.monotonic() - t0) * 1000,
            agent_types=[
                r.agent_type for r in responses
                if isinstance(r, AgentResponse) and r.success
            ] or agent_types,
            primary_agent=decision.primary_agent,
            supporting_agents=decision.supporting_agents,
            tools_used=tools_used,
            tool_traces=tool_traces,
            routing_reason=decision.reason,
            routing_confidence=decision.confidence,
        )
        self._record_tool_trace(result)
        return result

    # ──  Routing logic ──────────────────────────────────────────────────────────────

    def _route(self, intent: Optional[IntentCategory], urgency: Optional[UrgencyLevel]) -> AgentType:
        """
         Layer 3 routing decisions:
          1.  Intent Mapping
          2.  Urgency coverage (CRITICAL  Direct upgrade)
          3. Default GENERAL
        """
        if urgency == UrgencyLevel.CRITICAL:
            return AgentType.ESCALATION

        if intent and intent in self._INTENT_ROUTING:
            target = self._INTENT_ROUTING[intent]
            #  Use if there are available instances of the target type, Otherwise downgrade
            if target in self._pool and self._pool[target]:
                return target

        return AgentType.GENERAL

    def _route_decision(self, req: Request) -> RoutingDecision:
        """
         Structured routing decisions.

         Handle emergency/transfer to manual first, Domain scores are then used to determine the primary Agent and auxiliary Agent.
         This can express " Main processing + auxiliary diagnosis", Avoid splicing without priority after keyword hits.
        """
        if req.urgency == UrgencyLevel.CRITICAL:
            return RoutingDecision(
                primary_agent=AgentType.ESCALATION,
                reason=" Urgency is CRITICAL, Trigger upgrade route",
                confidence=1.0,
            )

        if req.intent in (IntentCategory.ESCALATION, IntentCategory.HUMAN_HANDOFF):
            return RoutingDecision(
                primary_agent=AgentType.ESCALATION,
                reason=f" Intent is {req.intent.value if req.intent else 'unknown'}, Trigger upgrade routing",
                confidence=max(req.intent_confidence, 0.8),
            )

        scores = self._domain_scores(req)
        available_scores = {
            agent_type: score
            for agent_type, score in scores.items()
            if agent_type == AgentType.GENERAL or self._pool.get(agent_type)
        }
        if not available_scores:
            return RoutingDecision(
                primary_agent=AgentType.GENERAL,
                reason=" No dedicated Agent available, Downgrade to GeneralAgent",
                confidence=0.1,
            )

        ordered = sorted(available_scores.items(), key=lambda item: item[1], reverse=True)
        primary_agent, primary_score = ordered[0]
        supporting_agents = [
            agent_type
            for agent_type, score in ordered[1:]
            if agent_type != AgentType.GENERAL and score >= 0.45 and score >= primary_score * 0.55
        ]

        reason = self._routing_reason(req, available_scores, primary_agent, supporting_agents)
        return RoutingDecision(
            primary_agent=primary_agent,
            supporting_agents=supporting_agents,
            reason=reason,
            confidence=round(min(primary_score, 1.0), 3),
        )

    def _domain_scores(self, req: Request) -> Dict[AgentType, float]:
        """ According to intention, Keywords and entities score Agents in each field."""
        msg = req.message.lower()
        scores = {
            AgentType.GENERAL: 0.1,
            AgentType.TECHNICAL: 0.0,
            AgentType.BILLING: 0.0,
        }

        if req.intent in (
            IntentCategory.QUERY,
            IntentCategory.ORDER_STATUS,
            IntentCategory.LOGISTICS,
            IntentCategory.REQUEST,
            IntentCategory.COMPLAINT,
            IntentCategory.GREETING,
            IntentCategory.FEEDBACK,
            IntentCategory.OTHER,
        ):
            scores[AgentType.GENERAL] += 0.55

        if req.intent in (
            IntentCategory.TECHNICAL,
            IntentCategory.TECHNICAL_LOGIN,
            IntentCategory.TECHNICAL_CRASH,
        ):
            scores[AgentType.TECHNICAL] += 0.75

        if req.intent in (
            IntentCategory.BILLING,
            IntentCategory.ACCOUNT,
            IntentCategory.ACCOUNT_SECURITY,
            IntentCategory.REFUND,
            IntentCategory.INVOICE,
            IntentCategory.PAYMENT_ISSUE,
        ):
            scores[AgentType.BILLING] += 0.75

        technical_kws = [" Crash", " Error report", "error", "crash", "Unable to log in", " Login failed", "500", "401", "Verification code"]
        billing_kws = ["Refund", "Return", "Deduction", "Invoice", "Bill", "Payment", "Subscribe", "refund", "invoice", "More deductions"]
        general_kws = ["Order", "Logistics", "Express delivery", " Delivery", "Member", " Points", "Consultation", "Help"]

        technical_hits = sum(1 for kw in technical_kws if kw in msg)
        billing_hits = sum(1 for kw in billing_kws if kw in msg)
        general_hits = sum(1 for kw in general_kws if kw in msg)

        scores[AgentType.TECHNICAL] += min(0.45, technical_hits * 0.18)
        scores[AgentType.BILLING] += min(0.45, billing_hits * 0.18)
        scores[AgentType.GENERAL] += min(0.35, general_hits * 0.12)

        entities = req.entities or {}
        if entities.get("error_code"):
            scores[AgentType.TECHNICAL] += 0.2
        if entities.get("amount"):
            scores[AgentType.BILLING] += 0.15
        if entities.get("order_id"):
            scores[AgentType.GENERAL] += 0.1

        return {agent_type: round(score, 3) for agent_type, score in scores.items()}

    @staticmethod
    def _routing_reason(
        req: Request,
        scores: Dict[AgentType, float],
        primary_agent: AgentType,
        supporting_agents: List[AgentType],
    ) -> str:
        score_text = ", ".join(
            f"{agent_type.value}={score:.2f}"
            for agent_type, score in sorted(scores.items(), key=lambda item: item[1], reverse=True)
        )
        support_text = ", ".join(agent.value for agent in supporting_agents) or "none"
        intent = req.intent.value if req.intent else "unknown"
        return (
            f"intent={intent}, group={req.intent_group or 'unknown'}, "
            f"primary={primary_agent.value}, supporting={support_text}, scores=[{score_text}]"
        )

    def _collaboration_targets(self, req: Request) -> List[AgentType]:
        """
         Determine whether multiple Agents need to collaborate in parallel.

         Intent recognition usually returns only one main intent; Domain keywords are used here to supplement the detection of compound problems.
         For example" Login error and repeated deductions" Requires technology and billing agent to process simultaneously.
        """
        msg = req.message.lower()
        targets: List[AgentType] = []

        technical_kws = [" Crash", " Error report", "error", "crash", "Unable to log in", " Login failed", "500", "401"]
        billing_kws = ["Refund", "Deduction", "Invoice", "Bill", "Payment", "Subscribe", "refund", "invoice"]

        if req.intent in (
            IntentCategory.TECHNICAL,
            IntentCategory.TECHNICAL_LOGIN,
            IntentCategory.TECHNICAL_CRASH,
        ) or any(kw in msg for kw in technical_kws):
            targets.append(AgentType.TECHNICAL)
        if req.intent in (
            IntentCategory.BILLING,
            IntentCategory.ACCOUNT,
            IntentCategory.ACCOUNT_SECURITY,
            IntentCategory.REFUND,
            IntentCategory.INVOICE,
            IntentCategory.PAYMENT_ISSUE,
        ) or any(kw in msg for kw in billing_kws):
            targets.append(AgentType.BILLING)

        #  Maintain order and remove duplicates, and only returns Agent types that currently have instances.
        deduped = list(dict.fromkeys(targets))
        return [agent_type for agent_type in deduped if self._pool.get(agent_type)]

    @staticmethod
    def _needs_clarification(req: Request) -> bool:
        """ When confidence is low and there is no clear intention, First ask, Avoid misrouting."""
        if req.intent != IntentCategory.OTHER:
            return False
        text = (req.message or "").strip()
        if len(text) <= 2:
            return False
        return req.intent_confidence < 0.5

    def _best_agent(self, agent_type: AgentType) -> Optional[BaseAgent]:
        """
         Performance routing:Select routing_score from similar Agents() The highest.
        This is" Dynamically adjust routing based on online performance
The core of ".
        """
        agents = self._pool.get(agent_type, [])
        if not agents:
            return None
        return max(agents, key=lambda a: a.stats.routing_score())

    async def _execute(self, req: Request, agent_type: AgentType) -> AgentResponse:
        """Execute Agent, Downgrade to GeneralAgent on failure."""
        agent = self._best_agent(agent_type)
        if agent is None:
            agent = self._best_agent(AgentType.GENERAL)
        if agent is None:
            return AgentResponse(
                agent_type=AgentType.GENERAL,
                content=" The service is temporarily unavailable, Please try again later.",
                success=False,
            )

        response = await agent.handle(req)

        #  Downgrade to GeneralAgent when dedicated Agent fails
        if not response.success and agent_type not in (AgentType.GENERAL, AgentType.ESCALATION):
            logger.warning(f"{agent_type.value}  failed,Downgrade to GeneralAgent")
            fallback = self._best_agent(AgentType.GENERAL)
            if fallback:
                response = await fallback.handle(req)

        return response

    # ──  Statistics ( for Monitor to read)────────────────────────────────────────────────

    def get_stats(self) -> Dict[str, Any]:
        result = {}
        for agent_type, agents in self._pool.items():
            for i, agent in enumerate(agents):
                key = f"{agent_type.value}_{i}"
                result[key] = {
                    "total":        agent.stats.total,
                    "success_rate": round(agent.stats.success_rate, 3),
                    "avg_ms":       round(agent.stats.avg_ms, 1),
                    "monitor_penalty": round(agent.stats.monitor_penalty, 3),
                    "routing_score": round(agent.stats.routing_score(), 3),
                    "role": agent.profile.role,
                    "workflow": list(agent.profile.workflow),
                    "tool_scope": list(agent.profile.tool_scope),
                    "available_tools": list(agent.get_tools()),
                    "model": agent._model,
                }
        return result

    def update_routing_penalties(self, penalties: Dict[str, float]) -> None:
        """
         Receive Monitor’s online performance feedback, Dynamically adjust routing penalty items.

        penalties  key uses get_stats
agent key in () , For example technical_0.
        """
        for agent_type, agents in self._pool.items():
            for i, agent in enumerate(agents):
                key = f"{agent_type.value}_{i}"
                penalty = penalties.get(key, 0.0)
                agent.stats.monitor_penalty = min(max(penalty, 0.0), 0.9)
