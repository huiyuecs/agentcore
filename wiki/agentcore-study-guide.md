# AgentCore  Study documents

 This is a document that positions the project andBusiness process,Key code, Learning documents merged with usage methods and technical highlights. The content is rewritten based on the current code, Try to press " First understand the system, Then understand the code, Finally able to run”
Sequential organization of .

## 1. Project positioning

AgentCore  is a multi-agent customer service orchestration runtime for complex customer service tasks.

 What it solves is not "Can chat”, But this kind of real problem:

-  Users make multiple demands at one time,There are both technical and billing issues
- User information is incomplete, The system needs to ask questions before processing.
-  The user wants to switch to manual or the scene is urgent. The system must be able to be upgraded
-  The knowledge base must be able to access real business rules. Instead of relying solely on model memory
-  The system must be able to evaluate,Monitoring,Reduce power,Return, Form a closed loop

 From an engineering point of view, Its goal is not to simply build a stronger model, Instead, we take apart the layers in the customer service system that are most likely to cause problems:

- Judge first "What exactly is this sentence asking?”
-  Then judge "Who should handle it?”
-  Then judge " Do you need to check the knowledge base?”
-  Then judge " Do you want to add additional information? Do you want to upgrade?”
-  Finally write the results back to the memory and monitoring system

The significance of this type of split is that, The real difficulty in customer service systems is often not generating replies. It is the previous judgment chain. If you make mistakes in the previous steps, No matter how strong the model is, the answer will be wrong.

## 2.  Overall architecture

```text
 User request
  -> /chat
  -> MemoryManager Read working memory, Episodic memory, User portrait, Abstract
  -> IntentRecognizer  Three-way fusion identifies fine-grained intentions, Urgency, Entity
  ->  Determine whether to trigger knowledge base retrieval based on intent
  -> AgentOrchestrator  Generate structured routing decisions
     - primary_agent
     - supporting_agents
     - routing_reason
     - routing_confidence
  ->  Call the corresponding Agent
  -> Inject memory,Knowledge base, Structured entity,Skills
  -> LLM  Generate reply
  ->  Write back to working memory
  ->  Asynchronous update of user portrait
  -> Monitor  and Evaluator form a closed loop of observation and evaluation
```

### 2.1 Why this order?

 This sequence corresponds to the most common dependencies of customer service systems:

1. **Memory first**: No context, Many problems will be misjudged as new problems.
2. ** Intent takes precedence**: Only by first knowing what the user is probably asking, can decide whether to check the knowledge base.
3. ** Knowledge base front-end**: If business problems rely entirely on model recall, Prone to factual errors.
4. ** Routing Decision**: Problems in different fields should be handed over to different Agents. Avoid one prompt handling all scenarios.
5. ** Memory writeback**: The system must deposit new information in each round. Otherwise, multiple rounds will be distorted.
6. ** Monitoring and evaluation closed loop**: There is no closed loop, The system can only "Looks like it will work”, Unable to continue optimization.

### 2.2  The difference between this architecture and ordinary Chatbot

 Common chatbots tend to be:

```text
 User message -> Single LLM -> Reply
```

AgentCore  is:

```text
 User message ->  Memory ->  Intent -> Knowledge Base -> Routing ->  Tools -> Reply -> Writeback ->  Review -> Monitoring
```

The difference is not just a few more modules, Instead, put "Answering ability" Split into several manageable capability layers.

## 3.  Core business process

### 3.1 `/chat`  Primary link

The entrance is [api/main.py](../api/main.py).

 The current link is:

1. Read Redis working memory,ChromaDB  Episodic memory and user portraits
2.  Construct recent conversation history, For intent recognition use
3.  Do three-way fusion intent recognition first
4.  Determine whether to call the knowledge base based on intent
5.  Generate routing decisions
6.  Call the main Agent or the main and auxiliary Agents
7.  Write back to memory, and update the portrait asynchronously

 There are two key details here:

- ** Intent recognition before Agent**, Because it determines whether a knowledge base is needed,Whether clarification is needed, Whether it should be upgraded directly.
- ** Portrait updates are asynchronous**, Because it belongs to " Delayed precipitation”, Should not slow down the user's current request.

### 3.2 When to switch to Agent?

- Technical issues -> `TechnicalAgent`
- Bill,Refund,Invoice, Payment exception -> `BillingAgent`
-  General consultation -> `GeneralAgent`
- Clearly requires manual, or high risk upgrade -> `EscalationAgent`

 The principle behind this is " Segmented by risk and responsibility”:

-  General Agent is responsible for the reception on the first floor. Not responsible for troubleshooting and fund handling
-  Technical Agent focuses on error codes,Environment, version,Reproduction path
-  Billing Agent focuses on orders,Amount, Payment,Refund,Invoice
-  Upgrading the Agent is responsible for sorting out the known information.Leave it to manual processing for continued processing

 The advantage of this is that the prompt of each Agent is shorter. Tool boundaries are clearer, Risks are easier to control.

### 3.3  When to collaborate in parallel

 When a request hits multiple realms at the same time, Multiple Agents will be dispatched at the same time. The results are then merged by the orchestrator.

 For example:

```text
 Login keeps getting 401, And the payment was deducted repeatedly just now
```

 May get:

-  Main Agent:`technical`
-  Auxiliary Agent:`billing`

This kind of " Primary and secondary collaboration” Than "Simple multi-channel concurrent reply" More like real business collaboration:

-  The main agent is responsible for giving the main conclusion
-  Auxiliary Agent is responsible for supplementing evidence or limitations in another field
-  Finally unified into a readable reply by the orchestrator

 Its value lies in, Users do not need to understand "This is what the two models said", The system will organize the results into one for the user.

### 3.4 When to downgrade

-  Professional Agent is not available
- Insufficient confidence
-  Request exceeds current role boundaries

 At this time it will be downgraded to `GeneralAgent`  or upgrade to `EscalationAgent`.

This step is very important, Because it avoids system "Hard answer”:

-  When not sure enough,Ask for necessary fields first
-  When the risk is too high, Directly handed over to manual labor
-  When the professional Agent is offline or fails, First guarantee the return to the general reception logic

 Rather than letting the system make nonsense in uncertain scenarios, Clearly downgrading is more in line with the production requirements of customer service scenarios.

### 3.5  When to compress memory

 When working memory exceeds a threshold, Old messages will be compressed into digests:

- Old news -> LLM  Abstract
-  Summary written to Redis
-  Old messages are written to ChromaDB contextual memory
-  Working memory only retains a small number of recent messages

 In the current implementation, User portraits have also been changed to be stored stably by user. Avoid per-session drift.

 The real purpose of compression is not "Save a few words”, Rather, it prevents high-value information from being flushed out after context expansion.
 In the customer service scene, The latest rounds of news are usually the most important,But the previous history cannot be lost entirely.That’s why “ Summary + recent rounds + long-term portrait” combination.

## 4. Key module

### 4.1  Intent recognition

File:
The intent recognition of `core/intent_recognizer.py`

AgentCore  is not a single-model classification, But three-way fusion:

- LLM  Semantic understanding
- Embedding  Similarity
- Pattern Keyword matching

 Output includes:

- `intent`
- `intent_group`
- `confidence`
- `source_scores`
- `urgency`
- `entities`

####  How to do it in the code

`recognize()`  will start at the same time:

- `llm_task`
- `emb_task`
-  Synchronous pattern recognition

 Then use `_vote()`  Fusion results.The benefits of this are:
LLM  is responsible for semantic understanding,Embedding  is responsible for template similarity,Pattern  is responsible for immediate disclosure, The three are complementary.

#### Why is it designed this way?

- LLM  Responsible for complex semantics
- Embedding  Responsible for template similarity
- Pattern  Responsible for zero delay
-  Three-way parallel, Reduce serial time consumption

 To be more specific:

-  When there is only LLM, High cost and easily affected by prompt word fluctuations
-  When there is only Pattern, Narrow coverage, If you change the wording slightly, it will become invalid.
-  When there is only Embedding, Not stable enough for fine-grained business boundaries

 The value of three-way integration is not " Multiple channels are better than one channel”, Instead, let different error types correct each other.

####  Confidence and downgrade

 The recognition result will not unconditionally believe the highest score, Instead there is threshold control:

- The score is high enough, Preserve fine-grained intent
-  Insufficient points, Fallback to `OTHER`
-  When model fails, Priority is taken over by Embedding or Pattern

 This ensures that the system will not misroute to the wrong Agent due to jitter on a certain path.

####  Supported fine-grained intents

|  Intention |  Example |
|---|---|
| `order_status` | Where is the order now? |
| `logistics` | When will the express arrive? |
| `refund` | How long does it take for the refund to arrive? |
| `invoice` | Help me issue an invoice |
| `payment_issue` | Why repeated deductions? |
| `technical_login` |  Login keeps reporting 401 |
| `technical_crash` |  App keeps crashing |
| `human_handoff` | I want to find manual customer service |

####  Entity extraction

 The current entity extraction is rule priority, Not letting the model draw every round:

- `order_id`
- `date`
- `amount`
- `error_code`

 The reasons for this are practical:

-  These entities are very structured, Rule extraction is more stable
-  No additional LLM cost required
-  Subsequent routing and tool calls can be directly reused

####  Urgency

 There are four levels of emergency:

- `LOW`
- `MEDIUM`
- `HIGH`
- `CRITICAL`

 It doesn't just display fields; It will affect whether to upgrade or not.Whether to give priority to manual transfer? Whether to increase routing conservatism.

### 4.2 Agent Arrangement

 File:`agents/agent_orchestrator.py`

 The orchestrator is responsible for:

-  Identify intent
-  Calculate domain score
-  Select Primary Agent and Secondary Agent
-  Execute single Agent or multiple Agents in parallel
-  Merge responses
-  Record routing reason and routing confidence

####  Routing is not a black box

`RoutingDecision`  will be explicitly logged:

- Who is the main Agent?
-  Is there any auxiliary agent?
- Why route like this
-  How high is the confidence of the current route?

 This is easy to talk about in interviews. Because it states that the system is not " I chose a model by chance”, Instead there is an interpretable routing layer.

####  Current character design

| Agent |  Responsibilities |
|---|---|
| `GeneralAgent` |  General triage and clarification |
| `TechnicalAgent` | Technical troubleshooting |
| `BillingAgent` | Bill Verification |
| `EscalationAgent` |  Manual upgrade handover |

#### Character Contract

Each Agent has its own `AgentProfile`, Contains:

- `role`
- `mission`
- `workflow`
- `input_contract`
- `output_contract`
- `handoff_conditions`
- `tool_scope`

 This is more controllable than relying solely on prompt to differentiate roles.
The real difference in

#### Agent

 The current Agent difference goes beyond the system prompt:

- Input contracts are different
- The output contract is different
-  Tool whitelist is different
-  Required risk margins are different
- temperature  is also different from max_tokens

 In other words,They are no longer " Change the prompt word for the same model”, Rather, it is a runtime role with different responsibilities.

### 4.3 Tool system

 File:`agents/tools.py`

Tools are managed centrally, and whitelist exposure by role:

-  General tools
- Technical Tools
- Billing Tools
- Upgrade tool
- Share RAG tools

####  Typical Tools

- `inspect_request_context`
- `suggest_required_fields`
- `lookup_error_code`
- `build_diagnostic_plan`
- `check_billing_fields`
- `compare_amounts`
- `create_handoff_summary`
- `search_knowledge_base`

#### Design points

-  Tool parameters have JSON Schema
-  The orchestrator will perform parameter verification
-  Tool only exposes whitelist
- RAG  is a capability shared by all Agents

####  Why should we concentrate it into one file?

 There are three benefits of centralized tools:

1. ** Easier to audit**: See what each tool can do at a glance
2. ** Easier to reuse**: Shared RAG does not need to be written repeatedly in multiple Agents
3. ** Easier to control risks**: An Agent will not mistakenly call capabilities that it should not have.

####  Tool Design Principles

-  Tools must be deterministic
-  Tools must be as interpretable as possible
-  Tool does not fake external system results
-  Tool only returns " Confirmable facts” or " Clear downgrade result"

 This matches the customer service scenario, Because what customer service is most afraid of is " The model compiled an operation result that seemed reasonable but was actually incorrect.”.

### 4.4 Level 3 memory

File:`memory/conversation_memory.py`

 Currently there are three levels of memory:

| Memory layer |  Storage | Function |
|---|---|---|
|  Working memory | Redis |  Recent messages in current conversation |
|  Episodic memory | ChromaDB |  Summary of historical conversation,Support semantic retrieval |
|  User portrait | ChromaDB |  Long-term preferences and key entities |

####  Current implementation features

-  Working memory compresses beyond threshold
-  The abstract is updated with merge, No longer infinite splicing
-  Episodic memory retrieval prioritizes the current session,Return to the same user global search
- User portrait button `user_id`  Stable storage
- `to_prompt_text()` Only a few recent messages, Avoid contexts that are too long

#### Why should it be divided into three layers?

 If only recent conversations are kept, The system forgets long-term user preferences.
 If you only keep long-term portraits, The system will lose the current context.
 If you put all the history into prompt, Context explosion is triggered again.

 So the three-layer memory is essentially doing " Time scale separation":

-  Working memory manages the current round
-  Episodic memory manages cross-session cues
-  User portrait management long-term preferences

####  Current optimization direction

 The current layer is much more stable than the initial one.But you can continue to do the following:

-  Abstracts are more structured, Explicit logging " To-do,Risk, Entity,Conclusion”
-  Retrieve join time decay
-  Portraits are merged by field, Instead of a full block rewrite
-  Explicitly index high-value entities

 These can further reduce the " Remember,But I didn’t remember it correctly” problem.

### 4.5 Knowledge Base and RAG

 File:`mcp/tool_manager.py`,`mcp/knowledge_base.py`

 Knowledge base links include:

1. Query rewriting
2.  Parallel Recall
3.  Merge and remove duplicates
4. LLM Rearrange
5. Top-K  Inject context

 The knowledge base is not a stand-alone demonstration feature,But accessed `/chat`  Primary link.

####  Why should we check the intent first and then check the knowledge base?

 Not all requests are worth retrieving:

- Greetings,Feedback, No need to check when switching to manual
-  Clear technical troubleshooting requires checking technical documents
-  Billing issues require checking policies and procedures

 If all questions are searched blindly, The system will:

-  Add delay
-  Introducing irrelevant context
-  Let the model be disturbed by noise

 So here it is done" Intent-driven retrieval”, instead of "Search whenever you see a word”.

####  Tool Reliability Design

RAG  The tool does not just check it directly. Also added:

-  Parameter verification
-  Cache
-  Timeout
-  Meltdown
- fallback

 This is a very typical production processing method. Because the retrieval system can also be broken, The main conversation link cannot be brought down with it.

### 4.6 Skills  Dynamic injection

 File:`core/skill_loader.py`

Skills  is used to combine customer service specifications, Handling boundaries, Role constraints are dynamically injected into the Agent's system prompt.

 Suitable for expression:

-  How to troubleshoot technical Agent
-  Billing Agent cannot promise refund
-  General Agent clarify first and then process

 Support hot reloading, No service restart is required.

#### Skills The difference between tools

- **Tools** Resolve "
What can  do?"
- **Skills** Resolve "What should be done”

For example:

-  Tool can check whether bill fields are complete
- Skills  will tell the billing agent that it cannot promise the refund arrival time

This layering is very important. Because it allows business specifications to be updated independently, without having to change the code.

### 4.7 Monitor  and downgrade

 File:`monitor/performance_monitor.py`

Monitor  will collect:

- Agent Success rate
- Agent Average latency
- Tool success rate
-  Tool average latency

 and feedback the exception to the routing layer, Impact on follow-up `routing_score()`.

####  Why does routing require monitoring results?

 Because static routing is not realistic enough.
 Even if an Agent is logically the most suitable, may actually appear online:

-  Success rate decreased
-  Latency becomes high
-  Tool dependency exception
The function of

Monitor  is to convert "Runtime Health”Include routing, Enables the system to bypass nodes that have deteriorated.

### 4.8  End-to-end evaluation

 File:`evaluation/evaluator.py`

 Reviews include:

-  Intent identification Accuracy
- Macro-F1
- LLM-as-Judge  Four-dimensional scoring
- Regression Detection
- Optimization suggestions

LLM-as-Judge  Scoring dimensions:

-  Relevance
-  Accuracy
- Integrity
-  Usefulness

#### Why do you do this?

 If there is no review, System optimization will become pure feeling:

- You may think prompt is better
-  But the actual intent recognition may be worse
- You may think the reply is longer
- But the user experience is worse

So the evaluation is to put "Feeling" becomes "Indicator".

####  How to say it’s suitable for an interview

 It can be said:

>  Not only did I do multi-Agent arrangement, also integrated intent recognition and reply quality into the evaluation link.Support Accuracy,Macro-F1  and LLM-as-Judge four-dimensional scoring, Can do regression detection.

## 5.  Key code reading order

 It is recommended to read in this order:

1. [api/main.py](../api/main.py)
2. [core/intent_recognizer.py](../core/intent_recognizer.py)
3. [agents/agent_orchestrator.py](../agents/agent_orchestrator.py)
4. [agents/tools.py](../agents/tools.py)
5. [memory/conversation_memory.py](../memory/conversation_memory.py)
6. [mcp/tool_manager.py](../mcp/tool_manager.py)
7. [mcp/knowledge_base.py](../mcp/knowledge_base.py)
8. [core/skill_loader.py](../core/skill_loader.py)
9. [monitor/performance_monitor.py](../monitor/performance_monitor.py)
10. [evaluation/evaluator.py](../evaluation/evaluator.py)

### 5.1 Why is this order the least labor-intensive?

 This sequence is from "Request entry" Go to "Support system” Go:

- Look at the entrance first, Know how the system receives requests
- Look at the recognition again, Know how the system understands the problem
- Look at the arrangement again, Know how the system decides who will handle it
- Looking at tools and memory again, Know how the system adds context
- Look at the knowledge base and Skills again, Know how to bring business rules to the system
-  Finally, look at monitoring and evaluation, Know how the system continues to get better

## 6. Usage Guide

### 6.1 Project structure

```text
api/            HTTP  Entrance
agents/         Agent, Routing,Tools
core/            Intent recognition,Skills,LLM Tools
memory/         Level 3 memory
mcp/            Knowledge Base and Tool Management
monitor/        Online monitoring
evaluation/      Review
skills/         Dynamic Skill Document
wiki/            Project Documentation
```

 This structure itself is also suitable for explaining during interviews:

- `core`  is " Understanding layer”
- `agents`  is " Decision-making and execution layer”
- `memory`  is "Context Layer"
- `mcp`  is " External Knowledge and Tools Layer"
- `monitor`  and `evaluation`  is "Governance"

### 6.2 Environment preparation

 Core dependencies:

- Anthropic API Key
- Redis
- ChromaDB
- Python  Operating environment

 Configuration is usually required before starting `.env`, Contains at least:

- `ANTHROPIC_API_KEY`
- `ANTHROPIC_MODEL`
- `REDIS_URL`
- `CHROMA_HOST`
- `CHROMA_PORT`

 If running locally,The first thing to confirm is:

- Anthropic Key Available
- Redis  Is it connected?
- ChromaDB  Whether to start
- `.env`  Whether it is loaded

 Because any one of these components is missing, will affect the main link.

### 6.3 Start mode

 The project supports two common methods:

- Docker Compose  Full stack startup
-  Local development mode running API

 If you are learning code, It is recommended to run the API locally first; If verifying the complete link, Use Docker Compose again.

### 6.4 Common interfaces

| Interface | Function |
|---|---|
| `GET /health` | Health Check |
| `POST /chat` |  Main conversation interface |
| `GET /skills` | View Skills |
| `POST /skills/reload` | Hot Loading Skills |
| `GET /monitor` |  View monitoring status |
| `GET /metrics` | Prometheus Indicator |
| `POST /search` | Knowledge base search |
| `POST /knowledge/add` |  Add knowledge base document |
| `POST /knowledge/upload` |  Upload files into the knowledge base |
| `GET /knowledge/stats` | Knowledge Base Statistics |
| `POST /eval/run` |  Run end-to-end evaluation |

 Among them, the most worthy of attention are:

- `/chat`:Real business main link
- `/eval/run`: Quality evaluation closed loop
- `/skills/reload`:Business rules hot update
- `/monitor`: Running Health Status

### 6.5 `/chat`  How to go

In one request,
The key actions of `/chat`  are actually:

1.  First get the context from memory
2.  Then get structured judgment from intent recognizer
3. The orchestrator then decides the primary and secondary Agents
4.  Check the knowledge base as needed
5.  Let the Agent generate a reply again
6. Write this round of information back to memory

 The highlights of this link are:** Every step can be plugged and unplugged, Observable, Playable**.

### 6.6  Debug Memory

 If you want to troubleshoot context issues,Look first:

- Redis  Working memory
- Redis summary
- ChromaDB `episodic`
- ChromaDB `user_profile`

 The general troubleshooting sequence is:

1.  First check whether the working memory has been written into
2.  Check again to see if the summary is generated
3.  Let’s see if the episodic memory is successfully saved
4. Finally check whether the portrait has been updated

 This can quickly determine whether the problem is writing, Compression or retrieval.

### 6.7  Debugging Knowledge Base

If `/chat`  Knowledge base not triggered:

-  First check whether the intention belongs to the business category
- Look again `_should_use_knowledge()`  Judgment
- Last look `knowledge_search`  Whether the result is returned successfully

 If the knowledge base results are inaccurate, Usually check these points:

-  Check whether the rewriting is off topic
-  Is the recall too small?
- Whether key documents have been suppressed by rearrangement?
-  Too much truncation when injecting context

### 6.8  Debug routing

 If the wrong Agent is selected, Usually look at three places:
Is

- `intent_group`  correct?
- `RoutingDecision`  `routing_reason`
- `AgentStats.routing_score()`  Whether it is affected by the demotion

 This is more useful than just looking at the final reply, Because routing issues usually don't arise during the build phase.

### 6.9  Evaluation suggestions

 It is recommended to run first:

1.  Intent recognition use case
2.  Conversation Quality Use Case
3.  Return to baseline

 This can quickly locate the problem in identifying, Routing or reply quality.

 If it is for an interview, It is best to say:

- Which indicator represents recognition ability?
-  Which indicator represents build quality
-  Which indicator represents system stability
- Which indicator represents regression risk

 In this way, the interviewer will feel that you are not just " Adjust a system that can run”,But really know how to measure it.

## 7.  Highlights of the interview

 If you want to take this project for an interview, You can give priority to these sentences:

-  What I am building is a multi-Agent customer service orchestration system. Not a single chatbot.
-  Intent recognition uses LLM,Embedding  and Pattern three-way fusion.
- Agent  Not only prompt is different, Also made character contracts and tool whitelisting.
-  Memory is divided into working memory, Three layers of episodic memory and user portrait.
-  The system has a knowledge base,Monitoring, Evaluation and routing de-weighting closed loop.
-  Multiple Agents support primary and secondary collaboration, It’s not just about hitting a model and it’s over.

 If the interviewer continues to ask questions, You can expand further:

-  Why do we need three-way intention fusion? Instead of using just one model
-  Why should we extract the tools into a unified file?
- Why should memory be divided into three layers?
-  Why should the knowledge base enter the main link?
-  Why should monitoring results be fed back to routing?

 These questions can naturally deepen the project.

## 8.  FAQ

### 8.1  Why not answer directly with a large model?

 Because in real customer service scenarios, Single model is easy:

-  Diversion is not accurate
-  Context Break
-  Unable to constrain business boundaries
-  Unable to evaluate and manage

### 8.2 Why do we need multiple Agents?

 Because of the input of different business domains, Risk boundaries and tools are different.

### 8.3  Why not cram all abilities into one big Prompt

 Because there will be three problems:

-  Role boundaries are unclear
-  Unclear tool permissions
-  Difficult to locate after error

 After splitting into multiple Agents,Each character can be tuned independently,Independent evaluation, Independent power reduction.

### 8.4  Why do we need three layers of memory?

 Because one round of history is not enough, Long-term user information cannot be stuffed into prompt every time.

### 8.5 Why do we need to evaluate?

 Because there is no review, It is difficult to know whether it is a model or Routing, There is something wrong with the knowledge base or the tool.

### 8.6 Why do we need to monitor?

 Because online systems are not static.Model, Tools,Knowledge base, Delay, Failure rates will vary, There must be runtime governance.

## 9.  One sentence summary
The core of

AgentCore  is not "Can chat”, Instead, we have engineered the most critical things in the customer service system:

- Identification problem
-  Assign roles
-  Call Tool
-  Maintain memory
-  Access to knowledge base
-  Monitor quality
- Quantitative evaluation

 If you compress it into one interview phrase, It can be said:

>  What I do is an observable, Evaluable, Downgradable multi-Agent customer service orchestration system, Identify the intention, Routing, Knowledge retrieval,Memory,Skills, Monitoring and evaluation form a complete closed loop.

