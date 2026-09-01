# AgentCore  Positioning and technical highlights

 This document is intended for people who are new to AgentCore. is used to quickly understand:What is this project?What is the current multi-Agent architecture?It is the same as before" Only prompt distinguishes Agent”
What is the difference between the versions of ? And why it's not just a customer service chat demo.

##  Positioning in one sentence

AgentCore  is a multi-agent customer service orchestration runtime for complex customer service tasks.

It is not a single "Customer Service Robot", It’s not just a matter of putting several prompts together. Rather, it is about identifying intentions andKnowledge retrieval,Memory, Routing, Tools, Monitoring and evaluation of strung collaborative systems. The system first understands the user’s problem, Then decide which Agent is responsible for processing, Do you need other Agent assistance? Should I check the knowledge base? Should I upgrade to manual? Finally, the results are written back to the memory and observation system.

## What problem does it solve?

A real customer service scenario is not a simple question and answer.

Users often mention both:

- Order,Logistics,Member, General consultation on points and other matters
-  Login failed,401/500, Technical issues such as page crashes
- Refund,Invoice, Repeated deductions, Accounting issues such as payment failure
-  Convert to manual, Complaint, Emergency processing and other upgrade requests

 If only one Agent is used, Three types of problems usually occur:

1. ** Diversion is not accurate**
    Technical questions were answered by ordinary customer service, Billing issue ignored by technical agent.

2. ** Context Break**
    In multiple rounds of dialogue, the user supplements the order number,Amount,
After  error code, The system cannot be continued stably.

3. ** Difficult to iterate**
    No review, Monitoring and rule hot updates, Items can only be "Looks like we can talk”, It is difficult to optimize continuously.
The goal of

AgentCore  is to make these capabilities into a complete link, Instead of just making a model shell that can talk.

## What is the current architecture?

 The current AgentCore is not "Single Agent + prompt variant" approach.
It is currently a ** Route-driven multi-Agent orchestration architecture**, The core form can be summarized as:

```text
 Intent Recognition ->  Routing Decision ->  Single Agent / Parallel Multi-Agent Execution ->  Response merge ->  Memory writeback ->  Monitoring/evaluation feedback
```

 To be more specific:

- `IntentRecognizer`  First do three-way fusion intent recognition
- `AgentOrchestrator`  Based on intent, Entity,Keywords, Routing in running state
- `GeneralAgent / TechnicalAgent / BillingAgent / EscalationAgent`  is not a simple copy of the same prompt, Instead, they have respective role contracts, Tool whitelist, Runtime roles of input and output boundaries
-  When the request covers multiple business domains at the same time, The orchestrator will dispatch multiple Agents in parallel. Then `ResponseComposer`  Merge results
-  The running process will change the Agent success rate, Delay, Tool quality is written back into the routing score, Form a closed loop

This means,AgentCore ’s multi-agent design focus is not on “Agent Quantity”,But** Routing,Collaboration, Downgrade and Governance**.

## Differences from previous versions

 If you only look at the earliest version,AgentCore  More like:

```text
 User message ->  An orchestrator -> Several prompts with different Agents
```

That is no longer the case. There are four key changes in the current version:

### 1. From "prompt Distinguish” becomes " Role contract distinction"

 Now each Agent has its own `AgentProfile`, It’s not just the character name, Also includes:

- `role`
- `mission`
- `workflow`
- `input_contract`
- `output_contract`
- `handoff_conditions`
- `tool_scope`

 This means that Agent differences are not just " Different speaking styles”, Instead:

-  What input is received
- What structure is produced?
- What tools can be used?
-  Under what circumstances must it be upgraded?

 This is much more stable than simply changing prompt.

### 2. From " Single point routing" becomes " Structured routing + primary and secondary collaboration”

 Now the orchestrator doesn’t just select an Agent, Instead, it will generate `RoutingDecision`:

- `primary_agent`
- `supporting_agents`
- `routing_reason`
- `routing_confidence`

 This allows the system to handle compound problems.
For example " Login error + repeated deductions”, can be handled by the technical agent master, Bill Agent assists processing, Instead of forcing a model to answer.

### 3.  From "An Agent has a set of capabilities" becomes "Sharing Tools + Role Whitelist"

Tools are now centralized `agents/tools.py`, And:

-  There is a shared RAG tool
-  There are general tools
- Have technical tools
-  There is a billing tool
-  There is an upgrade tool

Agent No longer " Look at prompt and decide for yourself whether you can call something.", Instead, it is explicitly subject to the tool whitelist.

### 4. From "Can answer” becomes " Governable”

 Currently there are:

-  Monitoring:Look at the success rate, Delay, Fusing,Tool quality
- Downgrade: Poorly run Agents will be suppressed by routing weights
-  Review: Intent to identify Accuracy/Macro-F1, Reply quality LLM-as-Judge

 This means that it is not a static orchestration, Rather, it is a customer service runtime that continuously adjusts based on performance.

##  Core processing link

```text
 User request
  -> /chat
  -> Read Redis working memory,ChromaDB  Historical summary and user portrait
  ->  Identify fine-grained intent, Intent group, Confidence and Structured Entities
  ->  Determine whether to trigger RAG knowledge base search based on intent
  ->  Generate structured routing decisions
     - primary_agent
     - supporting_agents
     - routing_reason
     - routing_confidence
  ->  Single Agent execution or parallel multi-Agent execution
  -> Inject memory,Knowledge base, Structured Entities and Dynamic Skills
  -> LLM  Generate reply
  ->  Write to working memory
  ->  Asynchronously update user portraits
  -> Monitor  and Evaluator form a closed loop of observation and evaluation
```

 The point of this link is not " Long process”, Instead, each step is solving an independent problem:

-  Memory resolution context
-  Intent to resolve diversion
-  Routing solves primary and secondary collaboration
- RAG  Addressing factual correctness
- Skills  Resolve business specifications
-  Monitor and resolve online health
-  Evaluate and resolve iteration quality

##  Core technology highlights

### 1.  Fine-grained intent recognition

AgentCore  Not only identifies "Consultation, Complaint, Technology,Bill” This coarse-grained intent, also supports fine-grained classification that is closer to the business.

 For example:

|  Fine-grained intent |  Normalized intent group |  Example |
|---|---|---|
| `logistics` | `query` | When will the express arrive? |
| `refund` | `billing` | How long does it take for the refund to arrive? |
| `invoice` | `billing` | Help me issue an invoice |
| `payment_issue` | `billing` | Why repeated deductions? |
| `technical_login` | `technical` |  Login keeps reporting 401 |
| `technical_crash` | `technical` |  App keeps crashing |
| `human_handoff` | `escalation` | I want to find manual customer service |

 Intent recognition uses three-way fusion:

- **LLM**: Responsible for semantic understanding and context judgment
- **Embedding /  Local hash vector**: Responsible for template similarity matching
- **Pattern**:Responsible for keeping the secret of keywords

 The final output is not just `intent`, Also includes:

- `intent_group`
- `intent_confidence`
- `intent_source_scores`
- `urgency`
- `entities`

 This makes intent recognition more than just a classifier, but subsequent routing, Clarified and upgraded structured input layer.

### 2.  Structured multi-agent routing

AgentCore  Multi-Agent routing is not simple" Hitting two keywords will result in parallel”.

 The current implementation is a route-driven multi-Agent orchestration architecture:

1.  First obtain the business direction through intent recognition
2.  Press Intention again,Keyword and entity scoring
3.  Select the main agent
4.  Choose auxiliary agents for other areas that are strong enough
5.  Parallel execution if necessary and merge results

 The scoring logic within the system is not just " Choose whoever looks like you”, Also considers:

-  Intent Category
- Keyword hit
-  Structured Entity
-  Is the current Agent available?
-  Online performance and monitoring downgrade

####  Current routing structure

```text
general
technical
billing
escalation
```

 Main Processing Agent by `primary_agent`  means, Auxiliary Agent consists of `supporting_agents`  means.
 If it is a compound problem, The system will allow multiple Agents to work at the same time. Rather than forcing the answer to a single model.

#### Differences from previous versions

 Before it was more like "An Agent is responsible for a prompt version".
 Now is " Multiple runtime roles with contracts and whitelists + an interpretable routing layer + a result merging layer".

 These two levels are completely different.

### 3. RAG  Knowledge base enhancement

AgentCore  Building a knowledge base using ChromaDB, is used to store refund policies, Delivery instructions,Technical troubleshooting, Member rules and other documents.

 Search links include:

```text
Original question
  ->  Query rewriting
  ->  Multiple subquery parallel recall
  -> Merge and remove duplicates
  -> LLM Rearrange
  -> Top-K  Inject Agent context
```

 But not all requests trigger RAG.

 The system will first identify the intent, Only business questions are searched in the knowledge base.Greetings,Feedback, Convert to manual, Unknown intent does not trigger RAG, Avoid invalid retrieval and contextual interference.

### 4. Redis + ChromaDB Memory system

AgentCore  Split the memory into three layers:

|  Memory type |  Storage | Function |
|---|---|---|
|  Working memory | Redis |  Recent messages in current conversation |
|  Episodic memory | ChromaDB `episodic` |  Summary of historical dialogue,Support semantic retrieval |
| User portrait | ChromaDB `user_profile` |  User preferences and key entities |

Redis  Read and write using asynchronous client,
The synchronization operation of ChromaDB  is put into the thread pool, Reduce main request link blocking.

 When there are too many messages in the current session, Old messages will be compressed. Generate summary, Keep recent rounds of conversations, Avoid infinite context bloat.

### 5. Dynamic Skills Injection

 The knowledge base solves "What are the business facts?”,Skills  The solution is "What should customer service do?”.

 For example:

-  Technical support needs to collect error codes first. version,Operation steps
-  Bill refund cannot be promised to be received immediately
-  General customer service needs to clarify user appeals first
-  Users need to be reminded not to disclose passwords or verification codes when sensitive information is involved

AgentCore Support from `skills/`  Directory loading Markdown/JSON/TXT rule files, and dynamically injected into the system prompt according to the Agent type and keywords.

 After modifying the rules, you can hot load through the interface. No service restart is required.

### 6. MCP  Tool Reliability Governance

AgentCore  Encapsulate knowledge base retrieval into a tool, and add a complete reliability mechanism:

-  Parameter verification
- TTL  Cache
-  Timeout control
-  Fuse
- fallback Downgrade
-  Query rewriting
- LLM Rearrange
-  Tool success rate and latency statistics

 This makes tool calls not just "Can be adjusted”, also has the ability to manage, Observable and degradable capabilities.

### 7. Monitor  Online observation and routing downgrade

Monitor  will be collected regularly:

- Agent Success rate
- Agent  Average latency
- Tool success rate
-  Tool average latency
-  Number of consecutive failures
-  Meltdown status

 If an Agent's performance deteriorates,Monitor  will write back `monitor_penalty`, Impact on follow-up `routing_score`.

 In other words, Monitoring is more than just displaying metrics; also affects subsequent routing.

### 8. LLM-as-Judge  End-to-end evaluation

AgentCore  Built-in `/eval/run`  Evaluation entrance.

 Evaluation content includes:

-  Intent identification Accuracy
- Macro-F1
-  End-to-end Agent reply quality
- LLM-as-Judge  Four-dimensional scoring
- Regression Detection
- Optimization suggestions

LLM-as-Judge  will evaluate the reply from four dimensions:

-  Relevance
-  Accuracy
- Integrity
-  Usefulness

 This makes the project more than just "Can answer”, Instead, the quality of answers can be continuously assessed.

## Why is it not a normal customer service demo?

 Ordinary customer service demo usually only has:

```text
 User input -> LLM Reply
```

AgentCore  is:

```text
 User input
  ->  Intent recognition
  ->  Entity extraction
  ->  Memory read
  ->  RAG by intent
  ->  Structured multi-agent routing
  -> Skills Injection
  -> Agent Reply
  ->  Memory writing
  -> Portrait update
  ->  Monitoring feedback
  ->  Evaluation return
```

 It is more like a small Multi-Agent Runtime, Instead of a one-wheel chatbot.