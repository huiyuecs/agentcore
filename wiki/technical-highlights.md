# AgentCore Technical Highlights

 This document presses " The current code is actually implemented" Rewrite, Highlight why AgentCore is no longer "Single Agent + prompt variant",But one** Route-driven multi-agent customer service runtime**.

 The current link does not write the answer first and then add the ability. Instead, make structured judgment first, Decide who will handle it,What tools can be used? Do you want parallelism?Whether to upgrade?Finally how to write back memory and monitor.

##  Let’s look at the conclusion first

| Ability | Key module | Value |
|---|---|---|
|  Three-way fusion intent recognition | `core/intent_recognizer.py` |  Let routing be based on structured decisions, instead of keyword guessing |
|  Route-driven multi-Agent orchestration | `agents/agent_orchestrator.py` | Support main Agent, Auxiliary Agent,Upgrade Agent collaboration |
|  Sharing Tools + Role Whitelist | `agents/agent_orchestrator.py`,`agents/tools.py` | Tools can be reused,But the call boundary is controllable |
|  Intent-driven RAG | `api/main.py`,`mcp/tool_manager.py`,`mcp/knowledge_base.py` |  Only search when you should search. Reduce noise |
| Three layers of memory | `memory/conversation_memory.py` |  Taking into account short-term context, Cross-turn cues and long-term preferences |
| Dynamic Skills Injection | `core/skill_loader.py` |  Business rules can be hot updated, No need to change the code every time |
| Online monitoring and routing downgrade | `monitor/performance_monitor.py` |  Feed runtime quality back to routing layer |
|  End-to-end evaluation | `evaluation/evaluator.py` |  Support continuous regression of intent recognition and reply quality |

##  Overall architecture

```text
 User request
  -> api/main.py
  -> MemoryManager.get_context()
      - Redis  Working memory
      - ChromaDB Episodic memory
      - ChromaDB User profile user_profile
  -> IntentRecognizer.recognize()
      - LLM Few-shot
      - Embedding  Similarity
      - Pattern  Rules
      -  Output intent/intent_group/source_scores/urgency/entities
  -> _build_knowledge_context()
      -  Only trigger knowledge retrieval for business questions
  -> AgentOrchestrator.run()
      -  Route to main Agent
      -  Call the auxiliary agent in parallel when necessary
      -  Hand over the upgrade scenario to EscalationAgent
  -> ResponseComposer
      -  Merge multiple Agent outputs
  -> MemoryManager.add_message()
  -> MemoryManager.update_profile()
  -> PerformanceMonitor / EndToEndEvaluator
```

---

##  Highlight 1: Three-way fusion intent recognition

**File**:`core/intent_recognizer.py`

###  Problem solved

Customer service routers are most afraid of two things:

1.  Put "Refund" Misjudged as "Bill inquiry”
2.  Put " Login error + repeated deductions” This kind of compound problem is solved incorrectly

 If you only rely on keywords, Poor robustness.Only rely on LLM, High cost, High latency, Unstable behavior.AgentCore  uses three methods together:

- `LLM`  Responsible for semantic understanding and context judgment
- `Embedding`  Responsible for similarity matching with template samples
- `Pattern`  Responsible for zero-latency coverage and high-precision rule hits

### How to do it specifically

`recognize()`  LLM and Embedding recognition will be started in parallel,Pattern  Synchronous execution, Finally merged via weighted voting:

- LLM Highest weight
- Embedding  is responsible for complementing common expressions
- Pattern  Responsible for full disclosure and fine-grained intention correction
-  Fallback to when below threshold `OTHER`

###  Output is not just intent

The final output is a structured result, is not a category label:

- `intent`
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

 This allows subsequent routing andUpgrade, Knowledge retrieval can directly consume structured information.

###  How did the urgency come about?

 Urgency is level 4:

- `LOW`
- `MEDIUM`
- `HIGH`
- `CRITICAL`

 There are two levels of rule sources:

-  Hit "Urgent/asap/immediately” Directly raise when waiting for keywords
-  If the intention is to transfer to labor or make a complaint, will also be upgraded to a higher emergency level

### How to speak during an interview

>  I did not make intent recognition into a single classifier, Instead, it is a three-way fusion.LLM  is responsible for semantics,Embedding  is responsible for similarity,Pattern  Responsible for high-precision rules. The final output is not just the intent, Also includes intent_group,source_scores,urgency  and entities, is directly used for subsequent routing and upgrades.

---

##  Highlight 2: Route-driven multi-Agent orchestration

**File**:`agents/agent_orchestrator.py`

### Differences from earlier versions

 Earlier versions were more like:

```text
 User message ->  An orchestrator ->  Several Agents that only change prompt
```

 Not now.The current version is:

```text
 Intent Recognition ->  Routing Decision -> Main Agent/Auxiliary Agent/Upgrade Agent
           ->  Possible parallel execution -> ResponseComposer Merge
           ->  Results written back to memory -> Monitor  Feedback Routing
```

 This means that the difference between multiple agents is not only in prompt,But it is reflected in:

- `AgentProfile`
-  Tool whitelist
-  Input/Output Contract
-  Routing logic
-  Runtime Statistics
-  Monitoring feedback

### What roles are currently available?

 There are 4 types of roles by default:

- `GeneralAgent`
- `TechnicalAgent`
- `BillingAgent`
- `EscalationAgent`

Among them `EscalationAgent`  No more pretending”Continue to answer”, is instead responsible for standardized handoffs.

### Why `pool`  is list

`_pool: Dict[AgentType, List[BaseAgent]]` Use here `list`, Not because there are many examples now, Rather to support:

- Multiple instances of the same role extended
-  Different model configurations of the same type
-  Online performance differentiated routing
-  Follow-up stress test, Grayscale and Downgrade

 Currently there is only 1 instance per class by default. But the structure has reserved horizontal expansion capabilities.

### How to do routing

 Routing is not a pure keyword, Mainly look at these signals:

-  Intent Category
-  Urgency
-  Structured Entity
- Field keywords
- Agent  Online performance

 For compound problems,The system will give `primary_agent`  and `supporting_agents`, Then execute in parallel.

### How to speak during an interview

> AgentCore  Multi-Agent is not prompt-only. Now each character has its own contract, Tool boundaries and routing locations, Complex problems can also be processed in parallel by primary and secondary collaboration, Running performance will also be fed back to the next round of routing.

---

##  Highlight three: Shared tool system + role whitelist

**File**:`agents/agent_orchestrator.py`,`agents/tools.py`

###  Problem solved

 Customer Service Agent cannot " Everything can be adjusted”, Otherwise there will be two problems:

-  Capability boundary is out of control
-  Tool duplicate definition, High maintenance cost

###  Current implementation

 Tools are unified and abstracted into `AgentToolSpec`, Press the role again to inject.Agent  When calling the tool it does:

-  Whitelist check
- JSON Schema  Parameter verification
-  Asynchronous execution support
-  The call result is backfilled to the model

###  Current layer

-  General tools
- Technical Tools
- Billing tool
- Upgrade tool
- Share RAG tools

###  Design significance

- RAG  Can be shared by all Agents
-  But each Agent can still only call its own ability range
- Avoid "You can adjust tools randomly with just one prompt and changing your identity."

### How to speak during an interview

>  I made the tools into a unified tool layer, Then perform whitelist control by role. This way capabilities can be shared, The border will not get out of control, In terms of engineering, it is more stable than writing the tools into their respective prompts.

---

## Highlight four: Intent-driven RAG

**File**:`api/main.py`,`mcp/tool_manager.py`,`mcp/knowledge_base.py`

###  Problem solved

 Not all questions are suitable for retrieval.

- Greetings,Chat, Convert to manual, No need to check the knowledge base
-  Order status,Refund rules,Invoice Policy, This type of business problem is suitable for retrieval

###  Current link

```text
 User message
  ->  Make intention judgment first
  ->  Decide whether to search the knowledge base again
  ->  Build knowledge context only in business class requests
```

### Why do this?

-  Reduce invalid searches
-  Avoid stuffing irrelevant documents into context
-  Reduce the probability of answers being interfered by knowledge noise

###  Engineering Features

 The search layer is not a simple vector search, It is a tool-based design around real customer service links:

- Query rewriting
-  Parallel recall
-  Merge and remove duplicates
- fallback
-  Cache
-  Meltdown

### How to speak during an interview

>  I put the RAG into the main link, But you don’t just search for words when you see them. Instead, the intent judgment determines whether to search or not. This will not only improve the recall of business issues, Also avoid chat requests being polluted by knowledge base noise.

---

##  Highlight five: Three-layer memory management

**File**:`memory/conversation_memory.py`

###  Problem solved

Customer service dialogue requires remembering the current round.We can’t stuff all the history into prompt, Also preserve cross-session preferences.

### Three layers of memory

- ** Working memory**:Redis, Save recent messages of current conversation
- ** Episodic memory**:ChromaDB `episodic`, Save compressed summary
- **User portrait**:ChromaDB `user_profile`, Preserving long-term preferences and stable entities

###  Current implementation features

-  Working memory will automatically compress when it exceeds the threshold
-  The abstract is not a simple splicing, Merge updates instead
- `to_prompt_text()` Only a few recent messages
- User portrait button `user_id`  Stable storage

###  Why layering is necessary

 Because the time scales of the three types of information are different:

-  The current round is a short-term context
-  Historical summary is a cross-wheel clue
-  User portraits are long-term preferences

 Put it in a window, Effects often interfere with each other.

### How to speak during an interview

>  I split the memory into working memory, Three layers of episodic memory and user portrait, respectively correspond to the current round, Cross-turn cues and long-term preferences. This not only controls the context length, Cross-session continuity is also preserved.

---

##  Highlight six:Dynamic Skills Injection

**File**:`core/skill_loader.py`

### Resolved issues

 The knowledge base answered "What is the truth?”,Skills  The constraint is "What should be done?”.

For example:

-  For technical failures, you must first collect the error code and environment
-  For billing issues, you cannot arbitrarily promise the arrival time
-  Avoid exposing users to sensitive information when it comes to privacy and security

###  Current implementation

Skills  Support hot reloading, Common formats include Markdown,JSON,TXT. The system will decide whether to inject based on the following conditions:

- Agent Type
-  User message keywords
- `enabled`  Switch

###  Why is it important?

 Business specifications can be updated independently, There is no need to change the main code every time.

###  How to speak during an interview

> Skills  addresses behavioral boundaries and processing specifications, is not a factual question. It is different from the division of labor in the knowledge base. And it can be hot updated, There is no need to change the main code link when adjusting business rules.

---

##  Highlight seven:Monitor Online observation and routing downgrade

**File**:`monitor/performance_monitor.py`

###  Problem solved

 Multi-Agent systems cannot just look reasonable at design time; Also stay healthy while running.

 Even if an Agent is the most suitable semantically, It may also be due to increased delay, Success rate decreases, The tool is abnormal and is no longer suitable for taking orders.

### Monitor What did

-  Regularly collect Agent success rate and average delay
- Success rate and delay of scheduled collection tools
-  Do anomaly detection
-  Generate alerts and recommendations
- Write the result back `monitor_penalty`

### What does this mean

 Routes are not static.
 Agent with poor online performance, The probability of selection will be automatically reduced in the future.

### How to speak during an interview

>  I sent the monitoring results back to the routing layer. Instead of just showing.Agent  success rate, Delays and exceptions can affect routing_score, In this way, the system can automatically avoid nodes whose status has deteriorated based on their online performance.

---

##  Highlight eight: End-to-end evaluation closed loop

**File**:`evaluation/evaluator.py`

###  Problem solved

 If there is no review,Optimization can only rely on feeling.

### Current review content

-  Intent identification Accuracy
- Macro-F1
- Single class Precision/Recall/F1
- Conversation reply quality
- Regression Detection
- Optimization suggestions

### LLM-as-Judge

Response quality is scored by LLM from four dimensions:

- relevance
- accuracy
- completeness
- helpfulness

### Why this matters

 It takes the project from "Can run” becomes " Energetic iteration”.

###  How to speak during an interview

>  I not only did multi-Agent arrangement, also integrates intent recognition and reply quality into the evaluation closed loop. In this way, the system is not adjusted by feeling. Instead, you can use Accuracy,Macro-F1  Do continuous regression with LLM-as-Judge.

---

## Data storage design
In

AgentCore , ChromaDB serves as both knowledge base and long-term memory.

| Collection |  Write source |  Query purpose |
|---|---|---|
| `knowledge_base` | Default document,`/knowledge/add`,`/knowledge/upload` | `/search`  and
Knowledge retrieval for  `/chat`  |
| `episodic` |  Working memory compressed summary |  Historical clues for the next round of dialogue |
| `user_profile` | Every time `/chat`  Post asynchronous update |  Personalization and long-term preferences |

---

## Module collaboration relationship

```text
api/main.py
  ├── /chat
  │     ├── MemoryManager.get_context()
  │     ├── IntentRecognizer.recognize()
  │     ├── _build_knowledge_context()
  │     ├── AgentOrchestrator.run()
  │     ├── MemoryManager.add_message()
  │     └── MemoryManager.update_profile()
  │
  ├── /skills
  │     └── SkillManager.summary()
  │
  ├── /skills/reload
  │     └── SkillManager.reload()
  │
  ├── /search
  │     └── MCPToolManager.search_with_rewrite()
  │           └── KnowledgeBase.search_handler()
  │
  ├── /monitor
  │     └── PerformanceMonitor.summary()
  │
  └── /eval/run
        └── EndToEndEvaluator.run()
```

---

##  One sentence summary
The technical highlight of

AgentCore  is not the single point module, But it connects the following capabilities into a closed loop:

- Identification problem
-  Routing role
-  Collaborative execution
-  Retrieve knowledge
- Manage memory
-  Injection rules
-  Monitor quality
- Quantitative evaluation

Summary in one sentence:

> AgentCore  is an observable, Evaluable, Downgradeable multi-agent customer service runtime, rather than a simple chatbot.
