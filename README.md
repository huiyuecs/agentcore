# AgentCore

AgentCore is a production-oriented multi-agent runtime for customer support and service operations. It turns an incoming request into an observable workflow: classify intent, retrieve relevant knowledge, select specialist agents, generate a coordinated response, update memory, and measure the result.

The project demonstrates more than a chat interface. It combines:

- Fine-grained intent classification using LLM, similarity, and deterministic signals
- Structured routing across general, technical, billing, and escalation agents
- Intent-gated retrieval-augmented generation with query rewriting and reranking
- Redis and ChromaDB memory for recent context, episodic recall, and user profiles
- Hot-reloadable Skill packages for business rules and operational guardrails
- Tool timeouts, caching, circuit breaking, fallbacks, and request-level traces
- Prometheus-compatible monitoring and LLM-as-Judge regression evaluation

## Architecture

```text
Client
  -> FastAPI /chat
  -> MemoryManager loads conversation context
  -> IntentRecognizer combines LLM, similarity, and pattern scores
  -> MCPToolManager retrieves and reranks relevant knowledge
  -> AgentOrchestrator selects primary and supporting specialists
  -> SkillManager injects role-specific policies
  -> ResponseComposer produces the final answer
  -> MemoryManager persists context and profile updates
  -> PerformanceMonitor and Evaluator record operational quality
```

The default agent roles are:

- `GeneralAgent` for product guidance, order questions, and general support
- `TechnicalAgent` for authentication, API, deployment, and incident diagnosis
- `BillingAgent` for payments, invoices, subscriptions, and refund workflows
- `EscalationAgent` for sensitive, high-risk, or human-review cases

AgentCore uses one global model by default and supports per-agent model overrides through `AGENTCORE_<ROLE>_MODEL`. This makes it possible to use a fast model for routine requests and a stronger model for specialist workflows without changing routing code.

## Quick start

### Prerequisites

- Docker and Docker Compose
- An API key for Anthropic or an Anthropic-compatible provider

Create the local environment file:

```bash
cp .env.example .env
```

Set at least these values:

```env
ANTHROPIC_API_KEY=replace-with-your-api-key
REDIS_PASSWORD=replace-with-a-strong-password
REDIS_URL=redis://:replace-with-a-strong-password@redis:6379/0
```

For a compatible provider, also set `ANTHROPIC_BASE_URL` and `ANTHROPIC_MODEL`.

Start the complete stack:

```bash
docker compose up -d --build
docker compose ps
```

Useful endpoints:

- API root: `http://localhost:8000`
- OpenAPI UI: `http://localhost:8000/docs`
- Health check: `http://localhost:8000/health`
- Nginx gateway: `http://localhost`

Follow application logs with:

```bash
docker compose logs -f agentcore
```

## API surface

The primary endpoints are:

- `POST /chat` — run the complete conversational workflow
- `POST /search` — query the knowledge base
- `POST /knowledge/add` — add structured knowledge documents
- `POST /knowledge/upload` — import Markdown, text, or JSON documents
- `GET /knowledge/stats` — inspect knowledge-base statistics
- `GET /skills` — list active Skill packages
- `POST /skills/reload` — reload Skill packages without restarting
- `GET /monitor` — inspect agent and tool health
- `GET /metrics` — expose Prometheus metrics
- `POST /eval/run` — run intent and response-quality evaluation

## Model routing

All LLM-backed components use `ANTHROPIC_MODEL` unless overridden. Specialist agents can select different models:

```env
AGENTCORE_GENERAL_MODEL=
AGENTCORE_TECHNICAL_MODEL=
AGENTCORE_BILLING_MODEL=
AGENTCORE_ESCALATION_MODEL=
```

Intent recognition, memory summarization, tool query processing, and evaluation currently share the global model. The intent recognizer attempts remote `voyage-3-lite` embeddings when the provider exposes an embeddings API and falls back to a deterministic local n-gram vector when it does not.

## Repository structure

```text
api/main.py                    FastAPI application and API lifecycle
agents/agent_orchestrator.py   Agent contracts, routing, and collaboration
agents/tools.py                Role-scoped tool definitions
core/intent_recognizer.py      Hybrid intent classification
core/skill_loader.py           Dynamic Skill discovery and injection
memory/conversation_memory.py  Redis and ChromaDB memory layers
mcp/tool_manager.py            Resilient retrieval and tool execution
mcp/knowledge_base.py          ChromaDB document ingestion and search
monitor/performance_monitor.py Runtime health and routing feedback
evaluation/evaluator.py        Intent metrics and LLM-as-Judge evaluation
skills/                        Role-specific operating policies
data/demo_docs/                English demonstration knowledge documents
wiki/                          Architecture, operations, and project guides
```

Runtime ChromaDB indexes, evaluation baselines, logs, local environments, and secrets are intentionally excluded from version control. The application creates them as needed.

## Documentation

- [Documentation center](wiki/documentation-center.md)
- [Architecture diagrams](wiki/architecture-diagrams.md)
- [Complete user guide](wiki/complete-user-guide.md)
- [Business workflow](wiki/business-workflow.md)
- [Technical highlights](wiki/technical-highlights.md)
- [Key code walkthrough](wiki/key-code-walkthrough.md)

## Validation

Run the automated test suite after installing the dependencies:

```bash
python -m pytest -q
```

Static checks used for this repository include Python byte-compilation, Shell syntax validation, JSON parsing, SVG/XML parsing, Markdown link validation, and a full scan for non-English repository content.

## License

No license has been declared. Add an appropriate license before distributing or accepting external contributions.
