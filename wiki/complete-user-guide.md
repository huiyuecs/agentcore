# AgentCore  Complete User Guide

 This document describes the deployment of AgentCore, Start,API  Call, Knowledge base usage,ChromaDB Data viewing, Monitoring evaluation and common troubleshooting.

Important Note:AgentCore  Currently, end-to-end evaluation capabilities that can be directly called are supported. After starting the HTTP service, This can be done via Swagger or `curl`  Call `POST /eval/run`, Automatically evaluate intent recognition accuracy,End-to-end Agent reply quality,LLM-as-Judge  Four-dimensional scoring, Regression detection and optimization recommendations. This capability is not a document design draft.But by `evaluation/evaluator.py`  and `api/main.py`  in `/eval/run`  Real implementation of the interface.

AgentCore  is an enterprise-level intelligent customer service system. The core link is:

```text
 User request
  -> FastAPI /chat
  -> MemoryManager  Read Redis working memory + ChromaDB episodic memory + user portrait
  -> IntentRecognizer  Identify fine-grained intents + intent groups + structured entities
  ->  Determine whether to trigger RAG knowledge base retrieval based on intent
  -> AgentOrchestrator  Route to General/Technical/Billing Agent
  -> SkillManager  Match Skills by message keyword and Agent type
  -> Agent  Call LLM to generate responses based on memory + knowledge base + structured entities + Skills
  -> Write to Redis, and update ChromaDB user portrait asynchronously
```

 In addition to the main conversation link, The system also provides an independent evaluation link:

```text
 Review request
  -> FastAPI /eval/run
  -> IntentEvaluator  Calculate Accuracy/Macro-F1
  -> EndToEndEvaluator  Call Orchestrator to generate real Agent responses
  -> LLMJudge  From correlation, Accuracy, Completeness, Four dimensions of usefulness rating
  ->  Compared with historical baseline, Output regressions and recommendations
```

## 1.  Project structure

```text
AgentCore/
├── api/main.py                    # FastAPI  Entrance,/chat /search /knowledge /monitor /eval
├── core/intent_recognizer.py      #  Three-way fusion intent recognition, Fine-grained intent, Entity extraction
├── core/skill_loader.py           # Skills Loading, Analysis, Matching and prompt injection
├── agents/agent_orchestrator.py   # Multi-Agent routing orchestration
├── memory/conversation_memory.py  # Redis + ChromaDB Memory management
├── mcp/tool_manager.py            # MCP  Tool call,Query rewriting,Rearrangement, Fusing, Cache,Downgrade
├── mcp/knowledge_base.py          # ChromaDB RAG Knowledge Base
├── monitor/performance_monitor.py # Agent/ Tool online monitoring
├── evaluation/evaluator.py        #  End-to-end evaluation
├── skills/                        #  Hot-loadable customer service skills document
│   ├── general_customer_service/  #  General customer service reception specifications
│   ├── technical_support/         # Technical Support Processing Specifications
│   └── billing_support/           #  Bill refund processing specifications
├── data/demo_docs/                #  Demo knowledge base document
├── docker-compose.yml             # Docker  Full stack orchestration
├── Dockerfile
├── requirements.txt
└── .env
```

## 2. Environment preparation

### 2.1 Required dependencies

- Docker
- Docker Compose
- Anthropic API Key, or third-party API Key compatible with Anthropic protocol

### 2.2  Configuration `.env`

 Copy the sample file:

```bash
cp .env.example .env
```

 Minimum configuration required:

```env
ANTHROPIC_API_KEY=your_api_key
```

 If using an Anthropic compatible interface such as DeepSeek, Can be configured:

```env
ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic
ANTHROPIC_MODEL=deepseek-v4-pro
ANTHROPIC_API_KEY=your_deepseek_key
```

Docker Compose  scene,Redis  Connection to ChromaDB is provided by `docker-compose.yml`  Overwrite to the address within the container. Usually does not need to be changed manually:

```env
REDIS_PASSWORD=agentcore123
CHROMA_HOST=localhost
CHROMA_PORT=8001
```

Skills Default from within the project `./skills` Read, can also be overridden via environment variables:

```env
AGENTCORE_SKILLS_DIR=./skills
AGENTCORE_SKILLS_MAX_PROMPT_CHARS=5000
```

### 2.3 The difference between full-stack deployment and run development mode

AgentCore  There are two commonly used Docker startup methods:`docker compose up`  Full stack deployment, and `docker run`  Development mode.The biggest difference between the two is:** Full-stack deployment will start applications and dependent services at the same time;run  Development mode usually only manually runs an application container, Dependent services need to be started in advance**.

|  Comparison item | Docker Compose  Full stack deployment | Docker run  Development mode |
|--------|--------------------------|----------------------|
|  Start command | `docker compose up -d --build` | `docker run ... agentcore ...` |
|  Startup content | AgentCore,Redis,ChromaDB,Prometheus,Nginx |  Only start a single container you specify |
| Redis/ChromaDB |  Automatically start and join the same network |  Must be executed first `docker compose up -d redis chromadb` |
| Container Network | Compose  Automatically create and manage |  Need to be specified manually `--network agentcore_agentcore-network` |
| Service name resolution |  Application has direct access `redis`,`chromadb` |  Accessible only after joining the same network `redis`,`chromadb` |
|  Code update |  Usually requires rebuilding or restarting the service | Mount
After  `-v "$(pwd):/workspace"` , Code modifications can take effect directly. Just restart the container |
|  Suitable for scene |  Demonstration,Joint debugging, Complete deployment,HTTP API Service |  Local development,Debug CLI, Temporarily overwriting environment variables |
|  FAQ | API Key  Or dependency health check failed |  Forgot to start Redis/ChromaDB,Cause `redis:6379 Name or service not known` |

Select suggestions:

-  Want to fully experience HTTP API,Swagger,Nginx,Prometheus:Use **Docker Compose  Full stack deployment**.
-  Want to debug source code or CLI, And hope to quickly rerun after changing the code locally:Use **Docker run  Development mode**.
-  If you just run the CLI,The most worry-free way is `docker compose run --rm agentcore python api/main.py --cli`, It automatically uses the Compose network.

## 3. Docker Compose  Full stack deployment

 It is recommended to use this method to start the complete service.

```bash
docker compose up -d --build
```

 View service status:

```bash
docker compose ps
```

 View application log:

```bash
docker compose logs -f agentcore
```

 After seeing the AgentCore startup log and the health check passed, Service available.

 Port after startup:

| Service |  Container name | Host port |  Container port | Usage |
|------|--------|------------|------------|------|
| AgentCore API | `agentcore-app` | `8000` | `8000` |  Main API Service |
| Nginx | `agentcore-nginx` | `80` | `80` | Reverse proxy |
| ChromaDB | `agentcore-chromadb` | `8001` | `8000` |  Vector database |
| Redis | `agentcore-redis` | `6379` | `6379` |  Working memory |
| Prometheus | `agentcore-prometheus` | `9090` | `9090` |  Monitoring data |

Health Check:

```bash
curl http://localhost:8000/health
```

Swagger  Documentation:

```text
http://localhost:8000/docs
```

 Also accessible via Nginx:

```bash
curl http://localhost/health
```

## 4. Docker Run  Development Mode

 You can only use Compose to start dependencies during development. Then use `docker run`  Mount the current code directory.

 Start Redis and ChromaDB first:

```bash
docker compose up -d redis chromadb
```

 Build image:

```bash
docker compose build --no-cache agentcore
```

 Start HTTP service:

```bash
docker run -it --rm \
  --network agentcore_agentcore-network \
  -p 8000:8000 \
  -e ANTHROPIC_BASE_URL="https://api.deepseek.com/anthropic" \
  -e ANTHROPIC_API_KEY="your_key" \
  -e ANTHROPIC_MODEL="deepseek-v4-pro" \
  -e REDIS_URL="redis://:agentcore123@redis:6379/0" \
  -e CHROMA_HOST="chromadb" \
  -e CHROMA_PORT="8000" \
  -e CHROMA_PERSIST_DIRECTORY="/workspace/data/chroma" \
  -v "$(pwd):/workspace" \
  -w /workspace \
  agentcore
```

CLI Interactive mode:

```bash
docker run -it --rm \
  --network agentcore_agentcore-network \
  -e ANTHROPIC_BASE_URL="https://api.deepseek.com/anthropic" \
  -e ANTHROPIC_API_KEY="your_key" \
  -e ANTHROPIC_MODEL="deepseek-v4-pro" \
  -e REDIS_URL="redis://:agentcore123@redis:6379/0" \
  -e CHROMA_HOST="chromadb" \
  -e CHROMA_PORT="8000" \
  -v "$(pwd):/workspace" \
  -w /workspace \
  agentcore \
  python api/main.py --cli
```

## 5. Swagger  and interface overview

AgentCore  Built on FastAPI, After starting the HTTP service, you can directly access the Swagger UI call interface in the browser.

Local Swagger address:

```text
http://localhost:8000/docs
```

 If using Nginx reverse proxy:

```text
http://localhost/docs
```

 After opening Swagger, You can click on the right side of any interface **Try it out**, Fill in the parameters and click **Execute**  Call local service directly. Common debugging sequence:

```text
1. GET /health                 Confirm whether the service is ready
2. POST /chat                  Test main conversation link
3. GET /knowledge/stats        Check whether the knowledge base already has data
4. POST /knowledge/upload      Upload demo knowledge base file
5. POST /search                Test knowledge base retrieval, Query rewriting and reordering
6. GET /monitor                View Agent and tool running indicators
7. GET /skills                View currently loaded Skills
8. POST /skills/reload         Hot loading after modifying Skill file
9. GET /metrics                View Prometheus indicator text
10. POST /eval/run             Run end-to-end evaluation
```

### 5.1 Interface Overview

|  Method | Path |  Parameter location | Function |  Suitable for scene |
|------|------|----------|------|----------|
| `GET` | `/health` | None | Health check, Return service status and Agent statistics |  Confirm that the service is available after startup |
| `POST` | `/chat` | JSON Body |  Main conversation interface,Complete memory reading, Intent recognition,Agent  Routing, Reply generation, Memory writing | Business main link |
| `GET` | `/monitor` | None |  View Agent/Tool statistics, Alarm and optimization suggestions | Observe online performance |
| `GET` | `/metrics` | None |  Exposing Prometheus metric text | Prometheus  Crawl and troubleshoot monitoring |
| `POST` | `/search` | Query  Parameters |  Execute knowledge base search optimization link:Query rewriting, Parallel recall, Merge and remove duplicates,LLM Rearrange |  Test RAG retrieval |
| `GET` | `/skills` | None |  View currently loaded Skills,Applicable to Agent, Keyword and parsing errors |  Confirm whether the dynamic rules are effective |
| `POST` | `/skills/reload` | None |  Rescan Skill Directory at Runtime |  No need to restart after modifying business specifications |
| `POST` | `/knowledge/add` | JSON Body |  Batch import documents into ChromaDB knowledge base | Programmatically import documents |
| `POST` | `/knowledge/upload` | Form File | Upload `.txt`,`.md`,`.json`  File import into knowledge base |  Manually upload knowledge base files |
| `GET` | `/knowledge/stats` | None |  View the total number of knowledge base document fragments |  Confirm whether the knowledge base has data |
| `POST` | `/eval/run` |  Optional JSON Body |  Run built-in or custom intent recognition and end-to-end conversation measurements |  Demo LLM-as-Judge review |
| `GET` | `/docs` |  Browser access | Swagger UI |  Browse and debug all interfaces |

### 5.2 Skills  Dynamic capability loading

Skills  is a hot-loadable business rules document, is used to combine general customer service,Technical support, Bill refund and other specifications are dynamically injected into the system prompt of the corresponding Agent. Its positioning is different from that of the knowledge base: Knowledge base answers "What are the business facts?”,Skills  Constraints"What should customer service do?How to word,When to upgrade?What not to do”.

 Currently there are three types of built-in Skills:

| Skill | File | Applicable Agent | Function |
|-------|------|------------|------|
|  General customer service reception specifications | `skills/general_customer_service/SKILL.md` | `general` |  First round of reception, Information clarification, Diversion, Complaint and transfer to labor |
| Technical Support Processing Specifications | `skills/technical_support/SKILL.md` | `technical` |  Troubleshooting,Interface error, Deployment configuration, Security Boundary |
|  Bill refund processing specifications | `skills/billing_support/SKILL.md` | `billing` |  Deduction,Refund,Invoice,Subscribe,Financial Review |

 View loading results:

```bash
curl http://localhost:8000/skills
```

 Hot loading after modifying the Skill file:

```bash
curl -X POST http://localhost:8000/skills/reload
```

`SKILL.md`  Recommended format:

```markdown
---
name: Technical Support Processing Specifications
description:  Troubleshooting and upgrade handling specifications for TechnicalAgent
keywords:  Error report, Error,Interface,API, Deployment, Timeout,500,401, Log
agents: technical
enabled: true
---

# Technical Support Processing Specifications

##  Role positioning

...
```

 Field description:

|  field | Function |
|------|------|
| `name` | Skill  display name, Will enter the model prompt |
| `description` |  Short description, Convenience `/skills` Troubleshooting |
| `keywords` |  The user message is injected after hitting the keyword |
| `agents` |  Limited applicable Agent, For example `general`,`technical`,`billing` |
| `enabled` |  Whether to enable this Skill |

### 5.3 `/health`

Use: Confirm whether the service is initialized.

```bash
curl http://localhost:8000/health
```

 Response example:

```json
{
  "status": "ok",
  "agents": {
    "general_0": {
      "total": 0,
      "success_rate": 1.0,
      "avg_ms": 0.0,
      "monitor_penalty": 0.0,
      "routing_score": 1.0
    }
  }
}
```

### 5.4 `/chat`

Use: Main conversation interface.

 Request body:

```json
{
  "message": "I want a refund",
  "user_id": "user_001",
  "conv_id": "session_001"
}
```

 Field description:

| Field | Required |  Description |
|------|------|------|
| `message` | Yes |  User input |
| `user_id` | No | User ID,Default `anonymous` |
| `conv_id` | No |  Session ID, If not passed, it will be automatically generated. |

 Return fields:

|  field |  Description |
|------|------|
| `conv_id` |  Session ID |
| `response` | Agent Reply |
| `intent` |  Fine-grained intent recognition results, For example `refund`,`logistics`,`technical_login` |
| `intent_group` |  Normalized intent group, For example `billing`,`query`,`technical`,`escalation` |
| `agent_type` |  Master returns to Agent, Usually equivalent to the main processing Agent |
| `agent_types` |  List of Agents actually participating in execution |
| `primary_agent` |  Main Processing Agent |
| `supporting_agents` |  Auxiliary Agent list, Used to supplement professional opinions when compounding problems |
| `routing_reason` |  Routing reason, Contains intent, Intent group, Primary and secondary Agents and domain scores |
| `routing_confidence` |  Primary Agent routing score |
| `escalated` |  Whether to trigger upgrade |
| `latency_ms` |  End-to-end time consuming |
| `knowledge_used` |  Whether this reply is injected with knowledge base search context |
| `entities` |  Structured entities extracted by local rules, For example, order number,Amount, Error code |
| `intent_confidence` |  Intent confidence after fusion |
| `intent_source_scores` | LLM,Embedding,Pattern  Other source scores |

### 5.5 `/search`

Use: Testing MCP tool calls and RAG retrieval optimizations.

Query  Parameters:

|  Parameters | Required | Default value |  Description |
|------|------|--------|------|
| `query` | Yes | None | User retrieval problem |
| `top_k` | No | `5` | Number of results returned |

 Example:

```bash
curl -X POST "http://localhost:8000/search?query=How long does it take for the refund to arrive&top_k=3"
```

### 5.6 `/knowledge/add`

Use: Batch import of knowledge base via JSON.

 Request body:

```json
{
  "documents": [
    {
      "title": "Refund Policy",
      "content": " Users can apply for a no-reason refund within 7 days of purchase..."
    }
  ]
}
```

### 5.7 `/knowledge/upload`

Use: Upload files to import into the knowledge base.

Supported formats:

| Format |  Description |
|------|------|
| `.txt` |  Entire file as one document |
| `.md` |  Entire file as one document |
| `.json` | JSON  array, The format is `[{ "title": "...", "content": "..." }]` |

 Example:

```bash
curl -X POST http://localhost:8000/knowledge/upload \
  -F "file=@data/demo_docs/sample_knowledge.json"
```

### 5.8 `/knowledge/stats`

Use: View the number of knowledge base fragments.

```bash
curl http://localhost:8000/knowledge/stats
```

### 5.9 `/monitor`

Use: View Agent and tool online metrics.

```bash
curl http://localhost:8000/monitor
```

 The returned content includes:

| Field |  Description |
|------|------|
| `agent_stats` | Agent  Number of calls,Success rate, Delay,routing_score |
| `tool_stats` |  Number of tool calls,Success rate, Delay, Melt status |
| `active_alerts` |  Recent alarm |
| `suggestions` | Optimization suggestions |

### 5.10 `/eval/run`

Use: Run the built-in review, Or submit a custom evaluation case.

```bash
curl -X POST http://localhost:8000/eval/run
```

 Custom single and multi-round evaluation:

```bash
curl -X POST http://localhost:8000/eval/run \
  -H "Content-Type: application/json" \
  -d '{
    "intent_cases": [
      {"message": " The application keeps reporting errors", "expected_intent": "technical_crash"}
    ],
    "dialog_cases": [
      {"question": "My order has not arrived yet"},
      {"turns": ["Hello,I want a refund", "The order number is #12345", " How long does it take for the refund to arrive?"]}
    ]
  }'
```

The returned content includes:

|  field |  Description |
|------|------|
| `pass_rate` |  Evaluation pass rate |
| `total` | Total number of review items |
| `passed` | Number of items passed |
| `avg_scores` | Average rating |
| `regressions` | Regression detection results |
| `recommendations` | Optimization suggestions |
| `results` | Each evaluation result |

 Evaluation regression baseline will be saved to `EVAL_BASELINE_PATH`,Docker Compose  The default path is:

```text
/app/data/eval/baseline.json
```

Host corresponding:

```text
./data/eval/baseline.json
```

## 6.  Usage items

### 6.1  Main conversation interface

 Request:

```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{
    "message": "When will my order arrive?",
    "user_id": "user_001",
    "conv_id": "session_001"
  }'
```

 Response example:

```json
{
  "conv_id": "session_001",
  "response": "Please provide the order number,I can help you check the order status and logistics progress.",
  "intent": "logistics",
  "intent_group": "query",
  "agent_type": "general",
  "agent_types": ["general"],
  "primary_agent": "general",
  "supporting_agents": [],
  "routing_reason": "intent=logistics, group=query, primary=general, supporting=none, scores=[general=0.77, technical=0.00, billing=0.00]",
  "routing_confidence": 0.77,
  "escalated": false,
  "latency_ms": 1234.5,
  "knowledge_used": true,
  "entities": {
    "order_id": [],
    "product": [],
    "date": [],
    "amount": [],
    "error_code": []
  },
  "intent_confidence": 0.86,
  "intent_source_scores": {
    "llm": 0.9,
    "embedding": 0.62,
    "pattern": 0.5
  }
}
```

 Field description:

|  field |  Meaning |
|------|------|
| `message` |  User input |
| `user_id` |  User unique identifier, Used to isolate memories and user portraits |
| `conv_id` |  Session ID,Same `conv_id`  Indicates multiple rounds of dialogue in the same round |
| `intent` |  Fine-grained intent identified |
| `intent_group` |  Normalized intent group, For observing and routing by broad categories |
| `agent_type` |  Master returns to Agent |
| `agent_types` |  List of Agents actually participating in execution |
| `primary_agent` |  Main Processing Agent |
| `supporting_agents` |  Auxiliary Agent List |
| `routing_reason` |  Routing reasons and realm scores |
| `routing_confidence` |  Primary Agent routing score |
| `escalated` |  Whether to trigger upgrade/transfer to manual |
| `latency_ms` |  End-to-end latency |
| `knowledge_used` |  Whether the RAG knowledge base context is used |
| `entities` |  Structured Entity |
| `intent_confidence` |  Fusion Confidence |
| `intent_source_scores` |  Each identification source score |

### 6.2 Multiple rounds of dialogue

 Multiple rounds of dialogue only need to keep the same `user_id`  and `conv_id`.

```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{
    "message": "The order number is A123456",
    "user_id": "user_001",
    "conv_id": "session_001"
  }'
```

 The system will read the latest messages of the current session from Redis. and read relevant history and user portraits from ChromaDB, The spelled context is passed to the Agent.

### 6.3 Example of technical issues

```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{
    "message": " App login keeps reporting 401 error",
    "user_id": "user_tech",
    "conv_id": "tech_001"
  }'
```

 Expected to route to `technical` Agent.

### 6.4  Example of billing issue

```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{
    "message": " Why was the payment deducted repeatedly this month?I want a refund",
    "user_id": "user_bill",
    "conv_id": "bill_001"
  }'
```

 Expected to route to `billing` Agent.

### 6.5  Compound problem example

```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{
    "message": " Login error 401, And there were repeated deductions this month.",
    "user_id": "user_mix",
    "conv_id": "mix_001"
  }'
```

 This type of problem will be calculated first
Domain score for  `general`,`technical`,`billing` .The highest score becomes `primary_agent`, Other professional agents with strong enough evidence will enter `supporting_agents`. If multiple Agent conditions are met at the same time, The system will execute the primary Agent and secondary Agent in parallel. and mark the reply " Main processing/auxiliary processing".

### 6.6 Skills  View and hot load

 View currently loaded Skills:

```bash
curl http://localhost:8000/skills
```

 Expect to see three categories of built-in specifications:

```text
 General customer service reception specifications
Technical Support Processing Specifications
 Bill refund processing specifications
```

 After modifying any Skill file, For example:

```text
skills/technical_support/SKILL.md
```

 Call hot reloading interface:

```bash
curl -X POST http://localhost:8000/skills/reload
```

 Call again `/chat` , New rules will inject prompts based on Agent type and keyword matching.

## 7.  Knowledge base usage
The knowledge base for

AgentCore  is provided by `mcp/knowledge_base.py`  Management, Use ChromaDB collection under the hood:

```text
knowledge_base
```

 On first startup, If the knowledge base is empty, The default customer service document will be automatically imported. Includes refund policy,Order inquiry,Account security, Technical troubleshooting,Member points, Shipping instructions.

### 7.1  View knowledge base statistics

```bash
curl http://localhost:8000/knowledge/stats
```

 Response example:

```json
{
  "total_chunks": 18
}
```

### 7.2 Batch import documents

```bash
curl -X POST http://localhost:8000/knowledge/add \
  -H "Content-Type: application/json" \
  -d '{
    "documents": [
      {
        "title": " Return and exchange policy",
        "content": " Users can apply for a no-reason return within 7 days after purchase.Refunds will be issued within 5-7 working days after approval."
      },
      {
        "title": "Member Rights",
        "content": " Gold card members enjoy a 10% discount, Earn double points in your birthday month."
      }
    ]
  }'
```

 The system will cut long documents into fragments of about 500 words. and written to ChromaDB.

### 7.3  Upload file into knowledge base

Upload Markdown:

```bash
curl -X POST http://localhost:8000/knowledge/upload \
  -F "file=@data/demo_docs/troubleshooting.md"
```

Upload JSON:

```bash
curl -X POST http://localhost:8000/knowledge/upload \
  -F "file=@data/demo_docs/sample_knowledge.json"
```

JSON  The format must be an array:

```json
[
  {
    "title": "Document title",
    "content": "Document content"
  }
]
```

### 7.4 Search knowledge base

```bash
curl -X POST "http://localhost:8000/search?query=How long does it take for the refund to arrive&top_k=3"
```

 Response example:

```json
{
  "query": "How long does it take for the refund to arrive?",
  "results": [
    {
      "title": "Refund Policy",
      "content": " After passing the review, Payment will be returned to the original payment account within 5-7 working days.",
      "score": 0.82,
      "chunk": 0
    }
  ],
  "reranked": true
}
```

`/search`  uses the complete search optimization link:

```text
Original query
  -> LLM  Query rewritten into multiple angles
  ->  Parallel recall of multiple subqueries in ChromaDB
  ->  Merge and remove duplicates
  -> LLM Rearrange
  -> Return to Top-K
```

## 8. ChromaDB  Usage in project

AgentCore  Three ChromaDB collections are used:

| Collection |  Module | Function |
|------------|------|------|
| `knowledge_base` | `mcp/knowledge_base.py` | RAG  Knowledge base document fragment |
| `episodic` | `memory/conversation_memory.py` |  Compressed historical conversation summary |
| `user_profile` | `memory/conversation_memory.py` |  User portrait, Contains preferences and key entities |

 Data writing timing:

| Data | Writing timing |
|------|----------|
| `knowledge_base` |  Automatically import default documents on startup, or call `/knowledge/add`,`/knowledge/upload` |
| `episodic` |  Automatically compress and write the current session working memory after it exceeds the threshold. |
| `user_profile` | Every time `/chat`  Asynchronously refine and update after reply |

## 9.  View ChromaDB content in Docker
The ChromaDB container name in

Compose  is:

```text
agentcore-chromadb
```

 The host access port is:

```text
http://localhost:8001
```

 The container internal port is:

```text
http://localhost:8000
```

### 9.1  Check if ChromaDB is alive

 Host execution:

```bash
curl http://localhost:8001/api/v1/heartbeat
```

 In-container execution:

```bash
docker exec -it agentcore-chromadb curl http://localhost:8000/api/v1/heartbeat
```

### 9.2 View all collections

```bash
curl http://localhost:8001/api/v1/collections
```

 If the ChromaDB version returns tenant/database related errors,Can be viewed using Python client, See next section.

### 9.3  View collections with Python client

 Enter the application container:

```bash
docker exec -it agentcore-app bash
```

 Execute in container:

```bash
python - <<'PY'
import chromadb

client = chromadb.HttpClient(host="chromadb", port=8000)
print("heartbeat:", client.heartbeat())

collections = client.list_collections()
print("collections:")
for c in collections:
    print("-", c.name, "count=", c.count())
PY
```

 Expect to see:

```text
collections:
- knowledge_base count= ...
- episodic count= ...
- user_profile count= ...
```

### 9.4 View `knowledge_base` Document content

```bash
docker exec -it agentcore-app bash
```

 Execute:

```bash
python - <<'PY'
import chromadb

client = chromadb.HttpClient(host="chromadb", port=8000)
col = client.get_collection("knowledge_base")

data = col.get(limit=10, include=["documents", "metadatas"])
for i, doc_id in enumerate(data["ids"]):
    print("=" * 80)
    print("id:", doc_id)
    print("metadata:", data["metadatas"][i])
    print("document:", data["documents"][i][:500])
PY
```

### 9.5 Query `knowledge_base`

```bash
docker exec -it agentcore-app bash
```

 Execute:

```bash
python - <<'PY'
import chromadb

client = chromadb.HttpClient(host="chromadb", port=8000)
col = client.get_collection("knowledge_base")

result = col.query(
    query_texts=["How long does it take for the refund to arrive?"],
    n_results=3,
    include=["documents", "metadatas", "distances"],
)

for doc, meta, dist in zip(
    result["documents"][0],
    result["metadatas"][0],
    result["distances"][0],
):
    print("=" * 80)
    print("title:", meta.get("title"))
    print("distance:", dist)
    print("content:", doc[:300])
PY
```

### 9.6  View user portrait `user_profile`

Call a few more times first `/chat`, Let the system generate user portraits asynchronously:

```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": " I often inquire about membership points and refunds.Please be concise in your answer", "user_id": "profile_user", "conv_id": "profile_session"}'
```

 Wait a few seconds and check:

```bash
docker exec -it agentcore-app bash
```

```bash
python - <<'PY'
import json
import chromadb

client = chromadb.HttpClient(host="chromadb", port=8000)
col = client.get_collection("user_profile")

data = col.get(
    where={"user_id": "profile_user"},
    include=["documents", "metadatas"],
)

for i, doc in enumerate(data["documents"]):
    print("=" * 80)
    print("metadata:", data["metadatas"][i])
    print(json.dumps(json.loads(doc), ensure_ascii=False, indent=2))
PY
```

### 9.7  View episodic memory `episodic`

 Contextual memory is only written after the number of messages in the current session reaches the compression threshold. The default threshold is at `MemoryManager.COMPRESS_AT` , Currently 15 messages.

 Compression can be triggered by sending multiple messages in succession:

```bash
for i in $(seq 1 16); do
  curl -s -X POST http://localhost:8000/chat \
    -H "Content-Type: application/json" \
    -d "{\"message\": \"This is the first $i  test messages, I would like to inquire about refunds and orders\", \"user_id\": \"episodic_user\", \"conv_id\": \"episodic_session\"}" > /dev/null
done
```

 View episodic memory:

```bash
docker exec -it agentcore-app bash
```

```bash
python - <<'PY'
import chromadb

client = chromadb.HttpClient(host="chromadb", port=8000)
col = client.get_collection("episodic")

data = col.get(
    where={"user_id": "episodic_user"},
    include=["documents", "metadatas"],
)

for i, doc in enumerate(data["documents"]):
    print("=" * 80)
    print("metadata:", data["metadatas"][i])
    print("summary:", doc)
PY
```

### 9.8  View ChromaDB persistence files
The persistent volume for

ChromaDB  is defined in Compose as:

```yaml
volumes:
  chromadb-data:
```

 View Docker volume:

```bash
docker volume ls | grep chromadb
docker volume inspect agentcore_chromadb-data
```

 View the data directory in the container:

```bash
docker exec -it agentcore-chromadb sh
ls -lah /chroma/chroma
find /chroma/chroma -maxdepth 2 -type f | head
```

 NOTE: It is not recommended to modify these underlying files directly. Viewing and managing data should preferably use the ChromaDB API or Python client.

### 9.9  Clear ChromaDB data

 Proceed with caution. Stop the service and delete the volume:

```bash
docker compose down
docker volume rm agentcore_chromadb-data
docker compose up -d --build
```

 If you only want to delete a collection, A Python client is available:

```bash
docker exec -it agentcore-app bash
```

```bash
python - <<'PY'
import chromadb

client = chromadb.HttpClient(host="chromadb", port=8000)
client.delete_collection("knowledge_base")
print("deleted knowledge_base")
PY
```

 Restart the application after deletion,`KnowledgeBase`  Default documents are re-imported when collection is empty.

## 10. Redis  Working Memory View

Redis Container name:

```text
agentcore-redis
```

Enter Redis:

```bash
docker exec -it agentcore-redis redis-cli -a agentcore123
```

View key:

```redis
KEYS *
```

 Working memory key format:

```text
wm:{user_id}:{conv_id}
```

 Session summary key format:

```text
summary:{user_id}:{conv_id}
```

 View the latest messages of a conversation:

```redis
LRANGE wm:user_001:session_001 0 -1
```

 View TTL:

```redis
TTL wm:user_001:session_001
```

 The default TTL is 24 hours.

## 11.  View working memory compression content

 Working memory compression occurs when `memory/conversation_memory.py` .Default configuration:

```text
WORKING_MAX = 20
COMPRESS_AT = 15
```

When the same
When  `user_id + conv_id` 's working memory reaches 15 messages, The system will:

```text
Old News -> LLM  Summary -> Redis summary
Old Message Summary -> ChromaDB episodic
Last 5 messages ->  Continue to remain in the Redis wm list
```

 Log example:

```text
 Working memory compression completed: cli_user/5a076f2b-b607-4339-9e9f-f0399862d366,Abstract 19 words
```

 Where:

```text
user_id = cli_user
conv_id = 5a076f2b-b607-4339-9e9f-f0399862d366
```

### 11.1  View session summary in Redis

Enter Redis:

```bash
docker exec -it agentcore-redis redis-cli -a agentcore123
```

Query summary:

```redis
GET summary:cli_user:5a076f2b-b607-4339-9e9f-f0399862d366
```

 One command to quickly view:

```bash
docker exec -it agentcore-redis redis-cli -a agentcore123 \
  GET summary:cli_user:5a076f2b-b607-4339-9e9f-f0399862d366
```

### 11.2  View the 5 most recent working memories that remain after compression

 After entering Redis, execute:

```redis
LRANGE wm:cli_user:5a076f2b-b607-4339-9e9f-f0399862d366 0 -1
```

 One command to quickly view:

```bash
docker exec -it agentcore-redis redis-cli -a agentcore123 \
  LRANGE wm:cli_user:5a076f2b-b607-4339-9e9f-f0399862d366 0 -1
```

 Description:

- Redis Use `LPUSH`  Write,The latest news is at the front of the list.
-  Code reading will `reversed(raws)`  Restore chronological order.
-  After compression, only the latest 5 items are retained in the Redis working memory list; Older content goes into Redis summary and ChromaDB in summary form `episodic`.

### 11.3  View episodic memory summaries in ChromaDB

 If it is a full stack deployment, Application container names are typically:

```text
agentcore-app
```

 Enter the application container:

```bash
docker exec -it agentcore-app bash
```

If you are using `docker run --rm`  Running CLI, Container names may be randomized.Check first:

```bash
docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Networks}}\t{{.Status}}'
```

 Enter the corresponding container:

```bash
docker exec -it < Container name> bash
```

 Execute Python script query `episodic`:

```bash
python - <<'PY'
import chromadb

user_id = "cli_user"
conv_id = "5a076f2b-b607-4339-9e9f-f0399862d366"

client = chromadb.HttpClient(host="chromadb", port=8000)
col = client.get_collection("episodic")

data = col.get(
    where={"user_id": user_id},
    include=["documents", "metadatas"],
)

for i, doc in enumerate(data["documents"]):
    meta = data["metadatas"][i]
    if meta.get("conv_id") == conv_id:
        print("=" * 80)
        print("metadata:", meta)
        print("summary:", doc)
        print("full_text_preview:", meta.get("full_text"))
PY
```

 Field description:

| Field |  Meaning |
|------|------|
| `documents[i]` | LLM  Generated historical conversation summary |
| `metadata.user_id` | User ID |
| `metadata.conv_id` |  Session ID |
| `metadata.ts` | Write time |
| `metadata.full_text` |  First 500 words preview of compressed original old message |

### 11.4  If you only want to see all the episodic memories of a certain user
The difference between

```bash
docker exec -it agentcore-app bash
```

```bash
python - <<'PY'
import chromadb

user_id = "cli_user"

client = chromadb.HttpClient(host="chromadb", port=8000)
col = client.get_collection("episodic")

data = col.get(
    where={"user_id": user_id},
    include=["documents", "metadatas"],
)

for i, doc in enumerate(data["documents"]):
    print("=" * 80)
    print("metadata:", data["metadatas"][i])
    print("summary:", doc)
PY
```

### 11.5 Redis summary  and ChromaDB episodic

|  Location |  Save content | Usage |
|------|----------|------|
| Redis `summary:{user_id}:{conv_id}` |  Current session compressed summary |  The next time you request the same session, directly enter prompt |
| ChromaDB `episodic` |  Compressed summary + metadata |  Retrieve related history semantically across sessions |
| Redis `wm:{user_id}:{conv_id}` | Last 5 messages |  Keep current conversation coherent |

## 12. Monitor Online monitoring

 View monitoring summary:

```bash
curl http://localhost:8000/monitor
```

 Response contains:

```json
{
  "agent_stats": {
    "general_0": {
      "total": 10,
      "success_rate": 1.0,
      "avg_ms": 1200.3,
      "monitor_penalty": 0.0,
      "routing_score": 0.836
    }
  },
  "tool_stats": {
    "knowledge_search": {
      "total": 5,
      "success_rate": 1.0,
      "avg_latency_ms": 80.2,
      "consecutive_fails": 0,
      "circuit_state": "closed"
    }
  },
  "active_alerts": [],
  "suggestions": []
}
```

 Indicator meaning:

| Indicator |  Meaning |
|------|------|
| `total` |  Number of calls |
| `success_rate` | Success rate |
| `avg_ms` / `avg_latency_ms` | Average latency |
| `routing_score` | Agent Route Score |
| `monitor_penalty` | Monitor  Deweighting coefficient written back based on online performance |
| `consecutive_fails` |  Number of consecutive tool failures |
| `circuit_state` |  Tool fuse status,Possibly `closed`,`open`,`half_open` |

Prometheus  Page:

```text
http://localhost:9090
```

## 13.  Run end-to-end evaluation

```bash
curl -X POST http://localhost:8000/eval/run
```

 Evaluation content:

1.  Intent recognition accuracy and Macro-F1
2.  Call Orchestrator to generate real responses
3. LLM-as-Judge  From correlation, Accuracy, Completeness, Usefulness score
4. Regression detection with the last evaluation results
5.  Generate optimization suggestions

 Built-in intent measurement use cases already use fine-grained business intents, For example `logistics`,`refund`,`invoice`,`payment_issue`,`technical_login`,`technical_crash`  and `human_handoff`.

 Custom use cases can also be submitted:

```bash
curl -X POST http://localhost:8000/eval/run \
  -H "Content-Type: application/json" \
  -d '{
    "dialog_cases": [
      {
        "turns": [
          "Hello,I want a refund",
          "Order number is #12345",
          " How long does it take for the refund to arrive?"
        ]
      }
    ]
  }'
```

 Response example:

```json
{
  "pass_rate": 0.83,
  "total": 5,
  "passed": 4,
  "avg_scores": {
    "intent_accuracy": 0.875,
    "relevance": 0.88,
    "accuracy": 0.82,
    "completeness": 0.79,
    "helpfulness": 0.85
  },
  "regressions": [],
  "recommendations": [
    " Intent recognition accuracy < 90%: Add Few-shot example, Or supplement training data for low F1 intent categories"
  ],
  "results": []
}
```

## 14.  Stop, Reboot and clean

 Stop service:

```bash
docker compose stop
```

 Restart service:

```bash
docker compose restart agentcore
```

 Stop and delete container, But keep the data volume:

```bash
docker compose down
```

 Stop and delete containers and data volumes:

```bash
docker compose down -v
```

 Rebuild and boot:

```bash
docker compose up -d --build
```

## 15.  FAQ

### 15.1 `/health` Return 503

 View application log:

```bash
docker compose logs -f agentcore
```

 Key inspections:

- `.env`  Whether to configure `ANTHROPIC_API_KEY`
- Redis Is it healthy?
- ChromaDB Is it healthy?
-  Is the application container being restarted repeatedly?

### 15.2 ChromaDB  Connection failed

 View ChromaDB status:

```bash
docker compose ps chromadb
docker compose logs -f chromadb
curl http://localhost:8001/api/v1/heartbeat
```

 Application in-container testing:

```bash
docker exec -it agentcore-app bash
python - <<'PY'
import chromadb
client = chromadb.HttpClient(host="chromadb", port=8000)
print(client.heartbeat())
PY
```

### 15.3 Redis  Authentication failed

 Confirm `.env`  and
The password used in  `docker-compose.yml`  is consistent. The default password is:

```text
agentcore123
```

 Test connection:

```bash
docker exec -it agentcore-redis redis-cli -a agentcore123 ping
```

### 15.4 `/search` No result

 First confirm that there is data in the knowledge base:

```bash
curl http://localhost:8000/knowledge/stats
```

 If 0, Presentation documents can be re-imported:

```bash
curl -X POST http://localhost:8000/knowledge/upload \
  -F "file=@data/demo_docs/sample_knowledge.json"
```

Test again:

```bash
curl -X POST "http://localhost:8000/search?query=APIHow to access&top_k=3"
```

### 15.5 User portrait cannot be found

 User portraits are updated asynchronously. and the dependent LLM call succeeded.Troubleshooting steps:

1.  Call first `/chat`, Use fixed `user_id`
2.  Wait a few seconds
3. View `docker compose logs -f agentcore`  Does it appear? `User portrait has been updated`
4.  Query using the Python script from Section 8.6 `user_profile`

### 15.6  Situational memory cannot be found

 Episodic memory is not written for every conversation. Write only after the current session message count reaches the compression threshold. Default threshold:

```text
MemoryManager.COMPRESS_AT = 15
```

 Send more than 16 messages in a row before checking again `episodic`.

## 16.  Recommended verification process

 Full verification can be performed in this order:

```bash
# 1.  Start
docker compose up -d --build

# 2. Health Check
curl http://localhost:8000/health

# 3.  Main dialogue
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Hello,I would like to know about the refund policy", "user_id": "demo_user", "conv_id": "demo_conv"}'

# 4. Knowledge Base Statistics
curl http://localhost:8000/knowledge/stats

# 5.  Import demo knowledge base
curl -X POST http://localhost:8000/knowledge/upload \
  -F "file=@data/demo_docs/sample_knowledge.json"

# 6. Search
curl -X POST "http://localhost:8000/search?query=AgentCoreHow to access API&top_k=3"

# 7. Monitoring
curl http://localhost:8000/monitor

# 8. Skills
curl http://localhost:8000/skills

# 9.  Review
curl -X POST http://localhost:8000/eval/run
```
