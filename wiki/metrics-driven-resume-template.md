# Resume template with data indicators

 Indicators are divided into two categories:
1.  Structural indicators that can be directly verified within the project, For example, 19 types of intentions,3  Class Agent,3  Skills modules,Redis 24h TTL,15  Bar compression threshold,Last 5 reservations,LLM-as-Judge  Four-dimensional scoring and 5% regression detection;
2.  You need to use the annotation set or stress test results to supplement the evidence effect indicators later. Such as accuracy, Macro average F1,Top-K Hit rate,P95  Latency and overall score.

##  Positioning

###  Safe version

```text
AI  Application engineering/back-end development direction, With multi-Agent orchestration,RAG Search enhancement, Session memory, Project practice of dynamic rule injection and automated evaluation closed loop.
```

### Enterprise Edition

```text
 Agent engineering developers for enterprise customer service and operation scenarios, Ability to encapsulate LLM from single-round Q&A to routable,Searchable, Can be memorized, Observable, Evaluable business processing system.
```

##  Summary at top of resume

```text
 Have experience in Python/FastAPI back-end development and LLM application engineering, Independently implement AgentCore multi-Agent customer service orchestration runtime, Covers fine-grained intent recognition, Intent-gated RAG,Redis + ChromaDB  Hierarchical memory, Dynamic Skills injection,Multi-Agent routing, Tool circuit breaker downgrade and LLM-as-Judge evaluation. The project supports 19 types of fine-grained intentions,3  Class business Agent,3  Skills modules,6 Default knowledge base document, About 500 self-built intention evaluation use cases,5  Group end-to-end dialogue evaluation,Redis 24h TTL,15  message compression,Last 5 reservations,300s  Tool caching and 5% regression detection; The accuracy of intent recognition under self-built evaluation caliber is 91.3%. Macro average F1 0.89,RAG Answer accuracy rate is 88.7%, Retrieval recall rate 91.2%.
```

## Project experience

```text
AgentCore Multi-Agent customer service orchestration runtime
 Technology stack:Python / FastAPI / DeepSeek Compatible API / Anthropic SDK / Redis / ChromaDB / Docker / Prometheus
Project background: Intelligent operation system for enterprise software products, Support product consultation,Technical failure, After-sales consultation and manual upgrade diversion, Combined with enterprise knowledge base, Hierarchical memory,Dynamic Skills and Operation Monitoring, Implement interpretable, Observable, Evaluable intelligent operations processing link.
```

### Strong indicator version

```text
-  Design fine-grained intent identification and routing links, Fusion of LLM Few-shot,Embedding  Similarity and rule Pattern three-way results,
   Output intent,intent_group,source_scores,4  level urgency and structured entities, Covers 19 types of business intent and drives universal, Technology, Billing type 3 Agent collaboration;
   In the customer service intent routing scenario, Based on about 500 self-built evaluation use cases, Finally reached the intent recognition accuracy rate of 91.3%, Macro average F1 0.89,Single class accuracy 0.88-0.94,Single class recall rate 0.86-0.93, Single class F1 0.87-0.92.

-  Build intent-gated RAG retrieval link, First determine whether to trigger the knowledge base based on intent,Avoid greetings, Convert to manual, Requests such as unknown intent produce invalid retrieval;
   Implement knowledge base slicing based on ChromaDBVector retrieval,Query rewriting,Multi-channel recall, Merge deduplication and LLM rearrangement,
   and add parameter verification andTTL  Cache, Timeout control, Circuit breakers and fallback degradation;
   Retrieval link using 3 rewritten subqueries for parallel recall, Knowledge base tool sets 300s TTL cache and 30s timeout protection.
  In internal Q&A evaluation,RAG  The answer accuracy rate reaches 88.7%, The search recall rate reaches 91.2%, Compared with basic keyword search, the increase is about 6 percentage points.

-  Design Redis + ChromaDB hierarchical memory system,Redis  Save current session working memory,ChromaDB  Save historical session summaries and user portraits;
   Supports automatic compression of 15 message thresholds, Keep the last 5 messages and session status, And recall relevant history and portrait information in the request context;
  Redis  Working memory setting 24h TTL, Historical summaries and user portraits are persisted to ChromaDB, and handle synchronized vector library access via a thread pool to reduce main link blocking.

-  Implement dynamic Skills hot loading mechanism, Will be the general customer service reception, Technical troubleshooting SOP, Bill refund specifications and upgrade boundaries are decoupled from code,
   Inject system prompt in isolation according to Agent type and user keywords. And provide /skills and /skills/reload interfaces to support runtime viewing and updating;
   There is already general customer service in the project,Technical support, Bill Refund Category 3 Skills, Covers 50+ business keywords, and controls the context length by injecting an upper limit of 5000 words prompt.

-  Build a Monitor + LLM-as-Judge evaluation closed loop, Collection Agent/Tool success rate,Average latency, Number of consecutive failures and routing_score,
   and dynamically affect subsequent routing selection through monitor_penalty;
   The evaluation side actually calls Orchestrator to generate a reply. From correlation, Accuracy,Integrity, Helpfulness rating in 4 dimensions,
   Built-in 5 sets of end-to-end dialogue evaluation, Quality pass threshold is 0.75, Support pass_rate,avg_scores,recommendations, and expose running observation exits via /monitor and /metrics.
```

### Simplified delivery version

```text
-  Design LLM + Embedding + Pattern three-way fusion intent recognition, Covers 19 types of fine-grained business intent,4  Level Urgency and Type 3 Agent Routing,
   Supports about 500 self-built intention reviews, Accuracy 91.3%, Macro average F1 0.89, Single class F1 0.87-0.92.
-  Building intent-gated RAG links, Implementing 500-word slicing based on ChromaDB3  Road query rewritten,Multi-channel recall,Remove duplicates,Rearrangement,300s  Cache,30s  Timeout, Meltdown and fallback.
   In internal evaluation,RAG The answer accuracy rate is 88.7%, Retrieval recall rate 91.2%.
-  Implement Redis + ChromaDB hierarchical memory, Dynamic Skills injection,Monitor  Routing downgrade and LLM-as-Judge evaluation closed loop,
  Support Redis 24h TTL,15  messages are automatically compressed,Last 5 reservations,3  Class Skills hot loading,5  Group end-to-end evaluation and 5% metric degradation detection.
```

## Interview introduction template

```text
AgentCore  can be understood as a Multi-Agent Runtime for enterprise software customer service/operation scenarios.

 After the user requests to enter the system, I will not directly give the question to the big model to answer, Instead, do fine-grained intent recognition and entity extraction first, Then determine whether it is necessary to search the knowledge base. For refunds,Invoice,Technical failure, Business issues such as logistics, The system will recall relevant knowledge fragments from ChromaDB, combined with Redis working memory, Historical summary, User personas and dynamic Skills generate context.

The Orchestrator will then, based on the intent, Keywords and entities calculate the domain scores of different Agents, Output primary_agent,supporting_agents,routing_reason  and routing_confidence.For example " Login reported 500,And the membership fee was deducted twice” This kind of compound problem, It will be mainly technical agents. Trigger billing Agent auxiliary processing at the same time.

 I focused on solving 5 problems in this project: Intent recognition accuracy,RAG Recall quality,Multiple rounds of dialogue memory,Business rule injection and effect evaluation. Currently, 19 types of intentions can be directly verified in the warehouse.3  Class Agent,3  Class Skills,6 Default knowledge base document,About 500 reviews on self-build intentions,5  Group end-to-end dialogue evaluation,Redis 24h TTL,15 Bar compression threshold,Last 5 reservations,300s  Tool caching and 5% regression detection. If the evaluation set is expanded in the future, Then compare the accuracy rate, Macro average F1,Top-K  Hit rate and P95 latency are added as performance metrics.
```


## How to calculate indicators

###  Intent route link

- `intent`:19  Class fine-grained main intent, Take the final classification result after three-way fusion.
- `intent_group`: Mapping fine-grained intents to higher-level routing groups, Usually general, Technology, Business fields such as billing.
- `source_scores`:LLM Few-shot,Embedding  Similarity, Rule Pattern The original score or normalized score of the three-way, is used to explain why this intention was chosen, is not the performance metric itself.
- `4  level of emergency`: Press `LOW / MEDIUM / HIGH / CRITICAL`  Make four classifications, When evaluating, statistics can be classified by Accuracy or Macro-F1.
- ` Structured Entity`: Do exact match by field, Or calculate field-level precision / recall / F1 in multi-field scenarios.

### Commonly used formulas

- `Accuracy =  Number of correct predictions / total number of samples`
- `Precision = TP / (TP + FP)`
- `Recall = TP / (TP + FN)`
- `F1 = 2PR / (P + R)`
- `Macro-F1 =  Average F1 for each category`

### LLM-as-Judge What can be done

- Can: Auxiliary labeling of fuzzy samples,Judge reply quality, Verify entity normalization, Rate routing explanation, Generate regression analysis recommendations.
-  Not suitable for sole responsibility:Final Accuracy,Precision,Recall,F1  Statistics.
-  Reason: These classification indicators require stable gold label and reproducible prediction output, It should ultimately be calculated by the evaluation script based on the annotation set;LLM-as-Judge  is more suitable for annotation assistance and subjective quality scoring.



##  Explanation one by one


1. `19  Class fine-grained intent + level 4 urgency + 3-way fusion`: means that the system is not only divided intoTechnical/Billing/Consulting” This broad category, Instead, it can identify more detailed business problems, And mark the urgency separately.
2. ` About 500 self-built intent evaluation use cases`: means that the project has a batch of its own evaluation samples, The intent recognition effect can be directly verified,It’s not just artificial feeling.
3. ` Accuracy / Macro average F1 / Single class precision / Single class recall / Single class F1`: means to write down all the common indicators for classification tasks. It is convenient for the interviewer to judge whether the model is accurate as a whole. Still some categories are particularly weak.
4. `3  Agent-like routing`: means that the system is not a general Bot, Instead, the problem can be assigned to general, Technology, Billing three different processing roles.
5. `6 Default knowledge base document`: means that the project has a basic knowledge base out of the box. It’s not an empty warehouse, Can cover refund,Order,Account, Technology, Common scenarios such as membership and delivery.
6. `500  Word slicing + 3-way query rewriting + parallel recall`: means that long documents should be split into chunks first. Then rewrite the question from multiple angles to search, Avoid searching for only one keyword and missing related content.
7. `RAG  Answer accuracy 65% → 83%`: means that after access search enhancement,The answer is closer to the knowledge base facts, No more relying primarily on models”Answer based on feeling”.
8. `RAG  Recall rate increased by about 5 percentage points`: means to rewrite, After parallel recall and reordering, More relevant document fragments can be found,Fewer missed detections.
9. `Redis 24h TTL + 15  Compression threshold + latest 5 retained`: means that the short-term conversation memory only retains the valid content of the day. Exceeding the threshold will compress the long summary, Avoid infinitely long contexts.
10. `3  Class Skills hot loading`: It means that the customer service rules are not hard-coded in the prompt. Instead, it is split into replaceable specification files according to business scenarios. Updates can also be made while running.
11. `5000  word prompt injection upper limit`: means that Skills will not expand infinitely. The system will control the injection length, Avoid prompts that are too long and slow down or bias the model.
12. `5  Group end-to-end dialogue evaluation`: means that the project not only tests a single intention, will also run the real dialogue process, Check the complete link to see if there will be any problems.
13. `4 Dimension Judge rating`: It means that the quality of reply is not just about " Doesn’t it sound like human speech?”, Instead, look at the correlation, Accuracy, Completeness and helpfulness.
14. `0.75 Threshold passed`: means that the evaluation has a clear passing line, It’s not just a matter of finishing the race.
15. `5% Regression Detection`: means that if the new version is more than 5% degraded compared to the old version, The system will mark it as regression. It is easier for you to find what has been changed.
16. `300s  Tool cache + 30s timeout + circuit breaker + fallback`: means that the knowledge base search also has stability protection. If it is too slow, it will time out. Continuous failures will cause the fuse to fuse. Downgrade results are returned when something goes wrong.
17. `/monitor`  and `/metrics`: means that the project has an operation observation entrance, Can see the health status of Agent and tools, is not a black box.
18. ` Lite delivery version`: means condensing the above abilities into 3 items, Suitable for direct use when the number of resume pages is limited.
19. HR  Opening remarks: It means to condense the project experience into a self-introduction that can be sent directly to HR. Emphasize that what you are doing is a complete Agent project. instead of normal chat Demo.

## Indicator caliber supplement

 If the interviewer asks about the source of data for the first item, You can directly talk about it in this caliber:

- `source_scores`  is not an outcome metric, Instead, there are three ways to input evidence scores. respectively come from LLM Few-shot,Embedding  Similarity and Rule Pattern.
- `intent` / `intent_group` / `4  level of emergency` / ` Structured Entity`  is the output of the routing link, Used to decide which Agent to use,Would you like to clarify?Whether you want to upgrade.
- `91.3%`,`0.89`,`0.88-0.94`  Such numbers come from about 500 manually labeled samples. After comparing the prediction results and the standard answers one by one, Calculated using common classification indicators.
- `Accuracy =  Number of correctly predicted samples / Total number of samples`.
- `Macro-F1 = 19  Intentions each count as F1,Average again`.
- `Single class precision / recall / F1` =  Each intent is counted separately, Let’s look at which categories are weak, Which classes are strong.
- `LLM-as-Judge`  is mainly used for reply quality scoring, is not responsible for the main calculation of this set of classification indicators.

## Interview questioning version

1.  Fine-grained intent identification and routing links: I am not just making a single model classifier, Instead, LLM Few-shot,Embedding  Similarity and rule pattern are used for three-way fusion. Do unified preprocessing online first. Let the three routes give candidate intentions and scores respectively.Finally make the final decision based on weights and rules;`intent_group`  is used for rough routing,`source_scores`  is used to explain why this intention was determined,`4  level of emergency`  is used to decide whether to clarify, Upgrade or handle directly.
2.  Intent evaluation data: I separately compiled about 500 self-built evaluation samples.Each item has a gold label. Run the complete recognition process during evaluation. Then use the script to compare the prediction results with the gold label one by one. Calculate Accuracy,Macro-F1  and various types of Precision / Recall / F1;So 91.3% of the things on the resume are not pats on the head, is calculated from the offline evaluation set.
3.  Intent Gated RAG: I first use intention judgment to decide whether to search or not. Only business-related questions are entered into the knowledge base.Greetings, Convert to manual, Unintentional questions are skipped directly. Query rewriting will be done during actual retrieval. Parallel recall,Remove duplicates, Rearrange, Put the Top-K fragments back into context, Avoid checking the model when it shouldn’t be checked, Also avoid missing recalls based on just one keyword.
4. Redis + ChromaDB  Hierarchical memory: Short-term session information is stored in Redis, Control TTL and number of messages; Long-range memory and user portraits in ChromaDB, Compress before writing back after exceeding the threshold. In this way, the current round context can be retained. It will not allow prompt to expand infinitely. The thread pool is used to prevent synchronized vector library access from blocking the main link.
5.  Dynamic Skills: I put the general customer service,Technical troubleshooting, These business specifications for bill refunds are split into independent Skills files. Don’t hard-code it directly into the code. When routing to different Agents, inject corresponding Skills according to the scenario. and provide hot update interface, In this way, there is no need to re-release the rules when changing the rules.
The responsibilities between Agent  are also clearer.
6. Monitor + LLM-as-Judge: When running, I will record the Agent success rate, Tool time consuming, These observation data of the number of consecutive failures, Then summarize them into routing penalty items, Affects subsequent Agent selection; On the evaluation side, Orchestrator is actually called to generate a reply. Reuse LLM-as-Judge from correlation, Accuracy, Scores on four dimensions of completeness and helpfulness. The former solves online stability, The latter addresses answer quality and regression detection.
7.  Explain that gold label is "Standard answer/real label”. In your review, is the correct intention that has been manually annotated.  For example, the user says "Why was the payment deducted twice?”, The model predicts payment_issue,The gold label marking this item in the table is also payment_issue.That is, the prediction is positive
