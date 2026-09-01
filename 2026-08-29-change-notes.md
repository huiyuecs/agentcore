# AgentCore Python / Java Change description

 This article records this time around "Multi-Agent orchestration, Tool calls can be traced, Request level playback,Interface can be queried"
Changes made by .

## Python  version changes

### 1. Multi-Agent orchestration link reconstruction
- This time the Python version is not just " Multiple Agents each write a different prompt”, Instead, multiple Agents are orchestrated into a complete link.
- In `agents/agent_orchestrator.py` ,Agent  Both responses and orchestration results are expanded to portable tool information.
- `AgentResponse`  added `tools_used`  and `tool_traces`.
- `OrchestratorResult`  also added `tools_used`  and `tool_traces`, It is convenient to bring out the complete tool calls that actually occurred in a request.
- `Request`  Brought in `request_id`, Let multiple Agents collaborate, Tool calls and final responses can be chained together.

### 2. Multi-Agent routing from "Answer by role” upgraded to " Structured Orchestration”
- `AgentProfile`  is no longer just a prompt word shell, Instead, the role of Agent, Responsibilities,Workflow, Input and output contract,Upgrade conditions, Tool scopes are structured.
-  This means that Agent differences are not just "system prompt  Different”, but " Role Contract + Tool Boundary + Collaboration Method” are all different.
- `RoutingDecision`  Explicit description:
  - `primary_agent`
  - `supporting_agents`
  - `reason`
  - `confidence`
-  Routing logic is divided into three layers:
  -  Intent routing
  - Performance Routing
  -  Downgrade routing
-  Ability to collaborate in parallel on complex problems, It’s not just about picking one Agent and answering the question.

### 3.  Parallel collaboration and upgrade mechanism completed
- `run_parallel`  A request will be dispatched to multiple Agents at the same time.
-  The final result will combine multiple Agents’ answers. Instead of only retaining the output of a certain Agent.
-  The upgrade mechanism is also retained at the orchestration layer:
  - `CRITICAL` Emergency upgrade directly
  - `ESCALATION` / `HUMAN_HANDOFF`  Directly transfer to manual
  - Agent  You can also trigger the upgrade signal in the answer

### 4. Tool Scope  and sharing tool access
Tool whitelisting and shared tool injection were introduced in
- `BaseAgent` .
- `agents/tools.py`  Unified definition of available tools,Agent  Only get the tools in your own scope.
-  This makes multi-Agent no longer just " Different characters speak different words”, but " Different roles can call different tools".

### 5. Tool Use  The process can be recorded
- `BaseAgent`  retains and outputs the details of each tool call.
-  Record fields include:
  - `tool_name`
  - `success`
  - `fallback_used`
  - `cached`
  - `reranked`
  - `latency_ms`
  - `error`
-  In this way, you can directly trace which tools were called from a conversation, Whether it is successful or not?How long does it take?

### 6.  Request level trace storage
- `AgentOrchestrator`  Added recent request trace cache.
-  New capabilities:
  - `get_tool_trace(request_id)`
  - `get_recent_tool_traces(limit)`
- Every time `/chat`  A request trace will be recorded after the end. Convenient for troubleshooting and playback.

### 7. API Exposed
- In `api/main.py`  Added tool trajectory query interface:
  - `GET /trace/tool/{request_id}`
  - `GET /trace/tools?limit=20`
- `/chat`  also included in the response `request_id`, Convenient for front and back series connection.

### 8.  The goal of the Python side this time
-  Make a request from "User input" to " Intent Recognition” Then to " Tool call" can all be found.
-  Don’t just look at the final answer,But you can see what happened in the middle.

## Java  version changes

### 1.  Request ID to get through
- `AgentRequest`  Support explicit passing in `requestId`.
- `ChatResponse`  Increase `request_id`.
- `/chat`  The returned results can now be obtained directly `request_id`  Check the trace.

### 2. Agent / Orchestrator  Return structure extension
- `AgentResponse`  Added tool related fields:
  - `toolName`
  - `toolSuccess`
  - `toolCached`
  - `toolReranked`
  - `toolError`
- `OrchestratorResult`  Added:
  - `toolsUsed`
  - `toolCalls`

### 3.  Multi-Agent arrangement remains unchanged but tracks are added
The
- Java  side is still a multi-Agent orchestration structure:
  - `GENERAL`
  - `TECHNICAL`
  - `BILLING`
  - `ESCALATION`
- `AgentOrchestrator`  is still responsible for routing, Parallel collaboration and degradation.
- The main supplements this time are:
  - Multi-Agent result reporting tool track
  -  Request level trace dropped into library/dropped into storage
  -  Facilitates playback and troubleshooting of a single request
-  The current Java version has not completely become the "Python version"Agent  Internal LLM tool-use loop", But multi-Agent request aggregation and observability have been added.

### 4.  Added trace package
- New `com.agentcore.trace`:
  - `ToolCallTrace`
  - `RequestToolTrace`
  - `RequestTraceStore`
-  This part is responsible for calling a requested tool, Time consuming, Whether the cache is hit, Whether to rearrange and other information are saved uniformly.

### 5. Controller  Exposed query interface
- `AgentCoreController`  New:
  - `GET /trace/tool/{requestId}`
  - `GET /trace/tools?limit=20`
- At the same time `/chat`  The knowledge base search results will also be brought into the orchestration results as external tool trace.

### 6.  Current Java side features
- What the Java version does first this time is " Request level tool track can be checked".
-  Compared with the Python version,Java  The LLM tool-use loop is not yet fully closed, But it is possible to query the tool behavior that occurred in a request.