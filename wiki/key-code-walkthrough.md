# AgentCore Key code

This document is**Request link** Reorganization, The goal is not to list the files one by one;Instead answer a question:

>  After the user sends a message,
How does the core code of AgentCore  put "Identification, Routing,Search, Generate,Memory,Monitoring,Review"Strung together?

 If this is your first time watching this project, It is recommended to read in the following order:

1. `/chat`  Main link
2. `core/intent_recognizer.py`
3. `agents/agent_orchestrator.py`
4. `mcp/tool_manager.py`  and `mcp/knowledge_base.py`
5. `memory/conversation_memory.py`
6. `core/skill_loader.py`
7. `monitor/performance_monitor.py`
8. `evaluation/evaluator.py`

---

## 1. `/chat`  Main link

**File**:`api/main.py`

 This is the entrance to the entire system.
The request processing order for AgentCore  is not "Answer directly”, Instead:

```text
Read memory ->  Identify intent -> Deciding whether to search the knowledge base -> Multi-Agent Routing ->  Generate reply ->  Write back to memory -> Asynchronous update of portrait
```

 The core code is roughly as follows:

```python
@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    if _orchestrator is None or _memory is None:
        raise HTTPException(503, " Service not ready")

    conv_id = req.conv_id or str(uuid.uuid4())

    mem_ctx = await _memory.get_context(req.user_id, conv_id, query=req.message)
    history = [
        {"role": m.role.value, "content": m.content}
        for m in mem_ctx.recent_messages[-5:]
    ] if mem_ctx.recent_messages else None

    intent_result = await _orchestrator.recognize_intent(req.message, history=history)
    knowledge_text, knowledge_used = await _build_knowledge_context(
        req.message,
        intent=intent_result.intent,
    )

    full_context = "\n\n".join(
        part for part in [mem_ctx.to_prompt_text(), knowledge_text] if part
    )

    orch_req = Request(
        message=req.message,
        user_id=req.user_id,
        conv_id=conv_id,
        context=full_context,
        history=history,
        entities=intent_result.entities,
        intent=intent_result.intent,
        intent_group=intent_result.intent_group,
        urgency=intent_result.urgency,
        intent_confidence=intent_result.confidence,
    )

    result = await _orchestrator.run(orch_req)
    await _memory.add_message(req.user_id, conv_id, MsgRole.USER, req.message)
    await _memory.add_message(req.user_id, conv_id, MsgRole.ASSISTANT, result.response)
    asyncio.create_task(_memory.update_profile(req.user_id, conv_id))
```

### The most important thing to understand here

- `get_context()`  will get working memory, Episodic memory, User portrait
- `recognize_intent()`  Output the structured intent first, Decide whether to search the knowledge base again
- `Request`  not only contains the original message,Also `entities`,`urgency`,`intent_group`
-  will be written back to working memory immediately after replying. Portrait updates are done asynchronously in the background

---

## 2.  Three-way fusion intent recognition

**File**:`core/intent_recognizer.py`

This is the first core layer of AgentCore: First put "What exactly does the user want to do?" Structure it out.

###  Identify the link

```text
LLM Few-shot
Embedding  Similarity
Pattern  Rule matching
->  Weighted voting
-> intent / intent_group / confidence / source_scores / urgency / entities
```

### Code layer design

`recognize()`  LLM and Embedding will be started in parallel,Pattern  Synchronous execution:

```python
llm_task = asyncio.create_task(self._llm_recognize(message, history))
emb_task = asyncio.create_task(self._embedding_recognize(message)) if self._embedding_enabled else None
pat = self._pattern_recognize(message)
```

 Then in
Fusion in  `_vote()` :

- LLM  Responsible for semantic understanding
- Embedding  Responsible for similarity matching with template samples
- Pattern  Responsible for quick bottom-up and fine-grained correction

### Output field

`IntentResult`  is not only really useful `intent`,Also:

- `intent_group`
- `confidence`
- `source_scores`
- `urgency`
- `entities`

Among them `entities`  Extract rules:

- `order_id`
- `date`
- `amount`
- `error_code`

###  Urgency

 The system divides the urgency into 4 levels:

- `LOW`
- `MEDIUM`
- `HIGH`
- `CRITICAL`

 Rules come from two types of signals:

-  Urgent keywords in message
-  Whether the intention itself belongs to human transfer, Complaints and other high-risk scenarios

###  How to speak during an interview

>  I made intention recognition a three-way fusion. is not a single classifier.LLM  is responsible for semantics,Embedding  is responsible for similarity,Pattern Responsible for telling the truth,Finally output intent,intent_group,source_scores,urgency  and entities, is used directly for subsequent routing.

---

## 3. MCP Tool layer

**File**:`mcp/tool_manager.py`

 The tool layer is responsible for two things:

1.  Standardize search/external capabilities
2.  Make calls cacheable, Timeout, Meltdown and fallback

### Key mechanism

```text
 Parameter verification ->  Cache ->  Fuse check ->  Timeout Control ->  Downgrade failed ->  Statistics writeback
```

### Why is it important

 Without this layer,RAG  and external tool calls will directly bring down the stability of the main link.

###  Key design

- `asyncio.wait_for()` Control timeout
- JSON Schema  Verification parameters
-  Fuse triggered after consecutive failures
- fallback  Results should be interpretable
-  Success rate and delay statistics will be updated with each call. For Monitor use

###  How to speak during an interview

>  I did not give external capabilities directly to Agent. Instead, it is abstracted into a tool layer first.Add cache, Meltdown and fallback. This way the system can be downgraded when the tool fails. Instead of the entire link failing together.

---

## 4. Knowledge Base and RAG

**File
The knowledge base for **:`mcp/knowledge_base.py`,`api/main.py`

AgentCore  is not "Search whenever you see a word”,But** Intent-driven retrieval**.

### Main process

```text
 Identify the intention first
->  Decide if you need a knowledge base
-> Query rewriting
->  Parallel recall
-> Merge and remove duplicates
-> LLM Rearrange
->  Inject context
```

### Why do this?

- Greetings,Chat, Convert to manual, No need to check the knowledge base
-  Order status,Refund rules, Only business issues such as invoice policies need to be searched

###  Critical code point

`api/main.py`  will first judge:

```python
if not _should_use_knowledge(message, intent=intent):
    return "", False
```

 This prevents invalid searches from polluting the context.

### You can understand it this way

RAG  is not a standalone module here, but is part of the main link,And it is** Conditional trigger
Part of **.

---

## 5. Multi-Agent Orchestration

**File**:`agents/agent_orchestrator.py`

 This is the second core layer of AgentCore: Decide first”Who will handle it?”, Decide again”How to collaborate”.

###  is not prompt-only

 The current architecture is no longer simple:

```text
 An orchestrator + several prompts for different Agents
```

 Instead:

```text
 Intent Recognition ->  Routing Decision -> Main Agent/Auxiliary Agent/Upgrade Agent
          ->  Single Agent execution or parallel collaboration
          -> ResponseComposer Merge results
```

### Agent  Role

- `GeneralAgent`
- `TechnicalAgent`
- `BillingAgent`
- `EscalationAgent`

### Why `pool` Yes
The design of  `list`

`_pool: Dict[AgentType, List[BaseAgent]]` , is to support:

-  Multiple instances of the same role
-  Different model configurations
-  Online performance differentiated routing
-  Grayscale and Downgrade

 Currently there is only one instance of each class by default. But the structure has been reserved for expansion.

###  Routing basis

 Will be synthesized when routing:

- `intent`
- `urgency`
- `entities`
- Keywords
-  Online performance

 Complex requests generate:

- `primary_agent`
- `supporting_agents`

For example " Login error 401, And there were repeated deductions this month.”, May be routed to both technical and billing.

### Agent  Tool boundaries at execution time

Each Agent has its own `AgentProfile`, defines:

-  Responsibilities
-  Workflow
- Enter contract
- Output contract
- Upgrade conditions
- `tool_scope`

 This shows that the difference between multiple Agents is not just prompt,It’s a role contract, Both tool boundaries and routing locations are different.

###  How to speak during an interview

> AgentCore  Multi-Agent is not prompt-only, Rather, route-driven role orchestration. Each Agent has its own contract and tool boundaries, Complex problems can also be processed in parallel by primary and secondary collaboration, Online performance will also be fed back into the next round of routing.

---

## 6.  Shared Tools and Skills

**File**:`agents/agent_orchestrator.py`,`core/skill_loader.py`

 This layer solves the problem of "Agent How to say,How to do,Where is the border?”.

###  Tool whitelist

Agent  When calling the tool, it is not directly adjusted naked. Instead:

- Get the whitelist first
-  Do parameter verification again
- Execute handler again
-  Finally, backfill the results to the model

### Skills Injection

`_build_system_prompt()`  will spell dynamic Skills into the system prompt:

```python
skill_prompt = self._skill_manager.prompt_for(req.message, self.agent_type.value)
```

This means that Skills are in** After selecting Agent** is in effect, Does not affect routing, Only affects execution policy.

### Why dismantle it like this?

-  Knowledge base answers "What is the truth?”
- Skills  states "What should be done?”

So they are not the same thing.

### Hot update

Modify `skills/*/SKILL.md`  can be passed after `/skills/reload`  Reload, No need to restart the service.

---

## 7. Three layers of memory

**File**:`memory/conversation_memory.py`

AgentCore  Split the memory into three layers:

- ** Working memory**:Redis, Save recent messages of current conversation
- ** Episodic memory**:ChromaDB `episodic`, Save compressed summary
- ** User portrait**:ChromaDB `user_profile`, Save long-term preferences

### The reason for dismantling it like this

-  The current round should be shorter
-  Cross-wheel information needs to be retained
-  Long-term preferences cannot be lost

###  Key implementation

-  Working memory will automatically compress when it exceeds the threshold
-  Compression is not simple splicing; Merge summary instead
- `to_prompt_text()`  Only a small amount of recent news, Avoid contexts that are too long
- `update_profile()`  Asynchronous execution, Do not block interface response

### How to speak during an interview

> I split the memory into working memory, Three layers of episodic memory and user portrait, respectively correspond to the current round, Cross-turn cues and long-term preferences. This can control the context length, Cross-session continuity is also preserved.

---

## 8. Monitor Online observation

**File
The effect of **:`monitor/performance_monitor.py`

Monitor  is not " Kanban”, Instead, the operation is sent back to the routing layer.

### What does it do

-  Periodically read Agent and tool statistics
-  Detection success rate and latency anomalies
-  Generate suggestions
-  Write back `monitor_penalty`

###  Relationship with routing

`AgentStats.routing_score()` will `monitor_penalty`  Count it in.
 So the Agent with poor online performance, The probability of selection will be automatically reduced in the future.

###  This closed loop is very important

 This means that the system is not a static route. Instead, it will automatically adjust based on online quality.

###  How to speak during an interview

>  I sent the monitoring results back to the routing layer. Instead of just showing.
The success rate and latency of Agent  will affect routing_score, In this way, the system can automatically avoid nodes whose status has deteriorated based on their online performance.

---

## 9.  End-to-end evaluation

**File**:`evaluation/evaluator.py`

 The evaluation layer solves the problem of "How do you know if the system has improved?".

### Two types of evaluations

1. ** Intent recognition evaluation**
   - Accuracy
   - Macro-F1
   - Single class Precision/Recall/F1

2. ** Dialogue quality evaluation**
   -  Score with LLM-as-Judge
   -  The dimensions are relevance,accuracy,completeness,helpfulness

### Why not mock

 The evaluation meeting will actually call `AgentOrchestrator.run()`  Generate reply, Then hand it over to the judge for scoring.
 This means it is measuring the real link, is not a fake output.

### Regression Detection

 The evaluation results can be compared with the historical baseline, is used to determine whether there is degradation.

###  How to speak during an interview

>  I not only did multi-Agent arrangement, also integrated intent recognition and reply quality into the evaluation closed loop. In this way, the system is not adjusted by feeling. Instead, you can use Accuracy,Macro-F1  and LLM-as-Judge continue to return.

---

## 10. How to read this document

 If you are preparing for an interview, I recommend memorizing it in this order:

1. `/chat`  Primary link
2.  Three-way fusion intent recognition
3. Multi-Agent Routing
4.  Tool Whitelisting and Skills
5. Three layers of memory
6. Monitor  Closed loop
7.  Evaluation closed loop

 If you want to summarize this code in one sentence:

> AgentCore  is not a simple chatbot, But a "Identification, Routing,Search,Execute,Memory,Monitoring,Review" Multi-Agent customer service runtime strung into a closed loop.
