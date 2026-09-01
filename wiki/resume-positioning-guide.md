# AgentCore  Resume Packaging Guide

 This document is used to package the AgentCore project into a resume, Experience that can be explained clearly in interviews and project presentations. It is recommended to describe according to the real implementation, If the quantitative data is not supported by stress testing or annotation sets, should be written as "Design Goal” or " on built-in review set".

 Packaging focus:AgentCore  It is currently not recommended to just wrap theIntelligent Customer Service Agent", is better positioned as "Multi-Agent Customer Service Orchestration/Multi-Agent Customer Support”. The project already supports fine-grained intent recognition, Structured routing decisions, Primary and secondary Agent collaboration,RAG  Knowledge enhancement,Dynamic Skills, Asynchronous memory access,Monitor  Routing downgrade and LLM-as-Judge evaluation closed loop.This is the difference"Normal Chat Demo” and " Observable, Evaluable, Sustainable iteration of Agent engineering project"
Key points of .

## One sentence description of the project

> AgentCore  is a multi-Agent orchestration runtime for complex customer service tasks. Integrated fine-grained intent recognition, Structured primary and secondary Agent routing,Dynamic Skills rule injection,Redis + ChromaDB  Memory system, RAG knowledge enhancement triggered by intent,MCP  Tool reliability management,Monitor  Online weight reduction closed-loop and LLM-as-Judge end-to-end evaluation.

##  How to write resume project experience

###  General version

```text
AgentCore Multi-Agent customer service orchestration runtime
 Technology stack:Python / FastAPI / Anthropic Claude / DeepSeek Compatible API / Redis / ChromaDB / Docker / Prometheus

-  Design and implement fine-grained intent recognition module, Combined with LLM semantic understanding,Embedding  Similarity and keyword Pattern,
   Output via weighted voting `intent`,`intent_group`, Fusion confidence, Source score, Urgency and structured entities;
   Support refund,Invoice, Payment abnormality, Login failure, Crash error,Logistics, Transfer to labor and other business subdivisions.
-  Implement MCP tool calling framework, Package parameter verification,TTL  Cache, Timeout control, fuse and fallback,
   and rewrite through query, Parallel recall and LLM rearrangement optimize RAG knowledge base retrieval quality.
-  Access RAG knowledge base search `/chat`  Primary link, First identify the intention, Search ChromaDB only for business type intentions `knowledge_base`
   and inject Top-K knowledge fragments, Reduce model illusion and reduce invalid retrieval costs.
-  Implement dynamic Skills loading capability, Support loading general customer service from Markdown/JSON files,Technical support, Bill refund specifications,
   Inject system prompt according to Agent type and user message keyword, and passed `/skills/reload`  Hot update.
-  Design Redis + ChromaDB three-level memory architecture, Use asynchronous Redis to manage current session working memory,
   Use ChromaDB to store historical conversation summaries and user portraits, and put synchronized vector library operations into the thread pool, Reduce the risk of main link congestion.
-  Implementing a structured multi-Agent orchestration system, Based on intent, Keyword and entity calculation `general/technical/billing`  Domain score,
   Generate `primary_agent`,`supporting_agents`,`routing_reason`  and `routing_confidence`,
   For compound problems, dispatch the results in parallel according to main processing/auxiliary processing and merge the results.
-  Build Monitor online monitoring closed loop, Regularly collect Agent/tool success rate and delay,
   Writing back to Orchestrator via monitor_penalty, Dynamically lower the routing_score of the problem Agent.
-  Implementing an end-to-end evaluation framework, Actual call to Orchestrator to generate reply, and use LLM-as-Judge
   From correlation, Accuracy, Completeness and usefulness four-dimensional scoring, Support regression detection and optimization suggestion generation.
```


### Java / Spring Boot  Version

Suitable for Java backend,AI  Application engineering, Used in platform engineering direction. Highlights: It’s not just about rewriting Python into Java. Instead, a set of deployable and Observable, Evaluable Agent services.

```text
AgentCore Java Multi-Agent customer service orchestration platform
 Technology stack:Java 21 / Spring Boot 3.5 / Spring AI / LangChain4j / Redis / Maven / Micrometer / Prometheus / Docker Compose / Swagger

-  Reconstruct AgentCore backend service based on Spring Boot 3.5,Provide `/chat`,`/search`,`/skills`,`/monitor`,
  `/metrics`,`/eval/run`  and other interfaces, and provide Swagger documentation through Springdoc OpenAPI, Support one-click deployment of Docker Compose.
-  Use Spring AI to encapsulate Anthropic and DeepSeek model calls, Support via Spring Profile in `anthropic`  and
Switch between  `deepseek`
  , and implement local fallback when LLM call fails, Reduce the strong dependence of development and demonstration environments on external model services.
-  Design Java version of fine-grained intent recognition module, Combined with LLM Few-shot, Three-way fusion of character n-gram semantic similarity and keyword pattern,
  Output `intent`,`intent_group`,`intent_confidence`,`source_scores`, Urgency and structured entities;
   Support refund,Invoice, Repeated deductions, Login 401. Page 500,Logistics, Transfer to labor and other business subdivisions.
-  Implementing a structured multi-agent orchestrator `AgentOrchestrator`, Based on intent, Keyword and entity calculation `general/technical/billing`
   Domain score, Generate `primary_agent`,`supporting_agents`,`routing_reason`  and `routing_confidence`,
   and " Login abnormality + repeated deductions” and other complex problems are processed in parallel by the primary and secondary agents and the results are merged.
-  Build Java version of Hybrid RAG knowledge base link, Use LangChain4j to slice the document after importing it.
   Combined with BM25 keyword score, Local hash vector semantic score and LLM rerank complete recall ranking,
   and avoid greetings, Convert to manual, Unknown intent and other requests produced an invalid retrieval.
-  Implementation `KnowledgeToolManager`  Tool governance capabilities, Add query rewriting, Multiple subquery parallel recall,TTL  Cache,
   Timeout control,Fuse,fallback Downgrade,rerank  and tool statistics, Improve RAG toolchain reliability.
-  Design Redis + JSON persistent memory system:Redis  Save current session working memory,
  JSON store  Save historical conversation summary, Long-term memory and user portraits, Implement memory recovery capabilities in the Java version that are consistent with what users see in the Python version.
-  Implement dynamic Skills loading mechanism,Support from `skills/*/SKILL.md` Read general customer service,Technical support, Bill Refund Rules,
   Inject system prompt according to Agent type and user message keyword, and passed `/skills/reload`  Implement runtime hot reloading.
-  Build a Monitor online observation closed loop, Agent exposure success rate based on Micrometer/Prometheus, Latency and tool statistics,
   and calculated based on success rate and delay `monitor_penalty`  Write back to Orchestrator, Dynamically affects subsequent routing scores.
-  Implement end-to-end evaluation capabilities of Java version, Override Intent Accuracy,Macro-F1,per-class Precision/Recall/F1,
  LLM-as-Judge  Four-dimensional quality score,baseline  Saving and regression detection, Support continuous verification of Agent link quality.
```

 If resume space is limited, can be compressed into:

```text
-  Use Java 21 + Spring Boot 3.5 + Spring AI to reconstruct the AgentCore multi-Agent customer service orchestration platform,Support Anthropic/DeepSeek model switching,Swagger Documentation,Docker Compose  Deployment and Prometheus monitoring.
-  Implement fine-grained intent recognition and structured routing, Output intent_group, Entity, Source score,primary_agent,supporting_agents,routing_reason  and routing_confidence, Supports parallel processing of primary and secondary agents for compound problems.
-  Build Hybrid RAG knowledge base link, Combined with LangChain4j document slicing,BM25,Local hash vector,LLM  Query rewriting and rerank, And reduce invalid RAG costs by triggering retrieval by intent.
-  Implement dynamic Skills,Redis  Working memory,JSON  Long-term memory/user portrait, Tool fuse degradation,Monitor  Routing downgrade and LLM-as-Judge evaluation closed loop.
```



###   Another concise version

```text
-  Implementing an end-to-end fine-grained intent recognizer, Using LLM Few-shot,Embedding  Three-way fusion of similarity and keyword Pattern,
   Output intent,intent_group,source_scores, Structured Entities and Urgency, and reduce the risk of misjudgment through low-confidence clarification.
-  Design RAG retrieval optimization link, Use LLM to rewrite user queries into subqueries for multiple perspectives,
   Merge deduplication and LLM rearrangement after parallel recall of ChromaDB knowledge base.
-  Realize structured multi-Agent orchestration and collaboration,According to intention, Keywords and entities score different Agents,
   Distinguish between primary Agent and secondary Agent for compound problems, and pass agent_types,routing_reason  Exposing routing observability.
-  Implement dynamic Skills injection mechanism, Let different Agents use their own business processing specifications, Reduce the risk of unauthorized replies and speech drift.
-  Implement LLM-as-Judge evaluation process, Coverage intent recognition accuracy, End-to-end reply quality, Regression detection and optimization recommendations.
```






###  How to evaluate end-to-end Agent?

** Answer ideas**

The review is divided into two parts:

1.  Intent recognition evaluation: Computing Accuracy and Macro-F1 with annotated use cases.
2.  End-to-end reply evaluation:Real call `Orchestrator.run()`  Generate reply, Then use LLM-as-Judge to score from four dimensions.

 The four dimensions are:

- `relevance`: Whether to answer user questions.
- `accuracy`: Whether the information is accurate.
- `completeness`: Whether the requirements are completely solved.
- `helpfulness`: Can the user act accordingly.

 The evaluator will also compare the results of the previous round. If a metric degrades by more than 5%, will be marked as regression, and generate optimization suggestions.


##  Technology stack keywords

```text
LLM / Anthropic Claude / DeepSeek Compatible API / Agent Orchestration /
Multi-Agent / Structured Routing / RoutingDecision /
Intent Recognition / Fine-grained Intent / Intent Group / Few-shot Prompting / Embedding Fallback /
Dynamic Skills / Prompt Injection Guardrails /
RAG / Query Rewriting / Reranking / MCP Tool Calling /
Redis AsyncIO / ChromaDB / Vector Search / Conversation Memory /
FastAPI / Docker Compose / Prometheus /
LLM-as-Judge / Evaluation / Circuit Breaker / TTL Cache / Fallback
```