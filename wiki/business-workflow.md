# AgentCore Business process description

 This document explains how AgentCore handles a customer service request from a business perspective:When to identify intention first?When to switch Agent? When to collaborate in parallel, When to compress a session,When will the user portrait be updated? When is an upgrade or downgrade triggered?

 and early "One prompt solves all problems”
The version of  is different, The current main link of AgentCore has become a** Route-driven multi-agent runtime**.It is not a one-point answer, Instead, identify, Routing,Execute,Memory, Monitoring and evaluation are strung together into a business chain.

## 1.  Complete process of a user request

User call `/chat`  or after entering a message in the CLI, The system processes it in the following order:

```text
 User message
  ->  Read memory context
     - Redis  Recent messages in current conversation
     - ChromaDB  Relevant historical summary
     - ChromaDB  User portrait
  ->  Intent recognition
     - LLM  Semantic understanding
     - Embedding  Similarity
     - Pattern  Keywords
     -  Output fine-grained intent,Normalized intent_group, Structured entity, Urgency
  ->  Determine whether to query the knowledge base based on intent
     - Query rewriting
     -  Parallel recall of ChromaDB knowledge_base
     - LLM  Rearrange Top-K
  -> Agent Routing
     -  General questions -> GeneralAgent
     - Technical Issue -> TechnicalAgent
     - Billing/Account Issues -> BillingAgent
     -  Transfer to manual/urgent issue -> EscalationAgent
  ->  If necessary, Execute parallel collaboration between primary and secondary Agents
  -> Skills  Matching and Injection
     -  Filter by Agent type general / technical / billing
     -  Inject the matched processing specification into system prompt
  -> Agent  Generate responses based on memory + knowledge base + structured entities + Skills
  ->  Write to working memory
  ->  Asynchronous update of user portrait
  ->  Return to user
```

 Evaluation call
When  `/eval/run` , The system processes it in the following order:

```text
 Evaluation use case
  ->  Intent recognition evaluation
     -  Compare predicted_intent and expected_intent
     -  Calculate Accuracy/Macro-F1
  ->  End-to-end dialogue evaluation
     -  Calling AgentOrchestrator.run()
     -  Single or multiple rounds to generate real Agent replies
  -> LLM-as-Judge
     - Relevance relevance
     -  accuracy accuracy
     - completeness completeness
     -  Helpfulness helpfulness
  -> Regression detection
     -  Comparison with historical baseline
     -  Output regressions and recommendations
```

## 2. When will Agent be switched?

AgentCore  It is not a fixed use of an Agent. Instead, dynamic selection is based on user questions.

### 2.1  Technical issues go to TechnicalAgent

 When the intent recognition result is `technical`,`technical_login`,`technical_crash`, Or when the question contains obvious technical keywords, Will switch to the technical agent.

 Typical input:

```text
 The application keeps reporting 401 errors
Webpage cannot be opened
 System crashed
 500 error occurs
Unable to log in
```

 Common keywords:

```text
Crash, Error report,error,crash, Unable to log in, Login failed,500,401
```

Business effect:

```text
GeneralAgent -> TechnicalAgent
```

TechnicalAgent  will be more inclined to give troubleshooting steps, Error cause and next step suggestions.The current TechnicalAgent will also match `skills/technical_support/SKILL.md`, Follow fault information collection, Error code troubleshooting, Deployment configuration check, Security boundaries and second-tier escalation rules.

### 2.2  Billing/refund/account issues go to BillingAgent

 When the intent recognition result is `billing`,`refund`,`invoice`,`payment_issue`,`account_security`  or `account`, Or when the question contains billing keywords, will switch to the billing agent.

 Typical input:

```text
I want a refund
Why was the payment deducted repeatedly?
Help me issue an invoice
I want to cancel my subscription
Modify my email
```

 Common keywords:

```text
Refund, Deduction,Invoice,Bill, Payment,Subscribe,refund,invoice
```

Business effect:

```text
GeneralAgent -> BillingAgent
```

BillingAgent  Will pay more attention to refunds,Invoice,Subscribe,Account information and other issues.The current BillingAgent will also match `skills/billing_support/SKILL.md`,Follow billing verification in reply,Refund review, Rules such as invoice processing and protection of sensitive information.

### 2.3  General consultation uses GeneralAgent

 If the issue does not fall specifically into the technical or billing areas, GeneralAgent will be used by default.

 Typical input:

```text
Hello
What features do you support?
When will the order arrive?
How to contact customer service?
```

 Order status and logistics issues retain fine-grained intent,For example `order_status`,`logistics`, But the normalized intent group will fall to `query`, Still handled by GeneralAgent by default.

Business effect:

```text
GeneralAgent
```

GeneralAgent  Responsible for general Q&A and simple guidance.The current GeneralAgent will also match `skills/general_customer_service/SKILL.md`, Follow the first round of reception, Information clarification, Problem triage, Rules for escalating complaints and prohibiting requests for sensitive information.

### 2.4  Switching to manual or high urgency will trigger an upgrade

 If the user explicitly requests to switch to manual, or the issue is identified as urgent, The upgrade flag will be triggered. Fine-grained intent `human_handoff`  will be normalized to `escalation`  Intent group.

 Typical input:

```text
I want to switch to artificial intelligence
I want to complain
 Find your manager
Very urgent, Process immediately
```

Business effect:

```text
escalated = true
```

 The upgrade in the current project is marked; The production system can access the work order system at this location. Manual customer service queue or alarm notification.

## 3. When will multiple Agents collaborate in parallel?

 If a sentence involves multiple business areas at the same time, The system will first calculate the scores in each field. Then decide the main Agent and auxiliary Agent.The highest score field becomes `primary_agent`, Other professional areas where the evidence is strong enough to enter `supporting_agents`.

 The areas currently involved in scoring include:

| Field |  Corresponding Agent | Main evidence |
|------|------------|----------|
| `general` | GeneralAgent | Query,Order,Logistics,Member,General consultation |
| `technical` | TechnicalAgent |  Login failed,401/500,Crash, Error report, Error code entity |
| `billing` | BillingAgent | Refund, Deduction,Invoice, Payment,Amount entity |

 The auxiliary Agent needs to meet the following requirements at the same time:

```text
score >= 0.45
score >= primary_score * 0.55
 and is not a GeneralAgent
```

### 3.1 Technology + Billing Compound Problem

 Typical input:

```text
 Login error 401, And there were repeated deductions this month.
```

 The system will recognize:

```text
Technical issues: Login error 401
Billing issue: Repeated deductions
```

Business processing:

```text
primary_agent = technical
supporting_agents = [billing]
TechnicalAgent + BillingAgent  Parallel processing
```

 The return form is similar:

```text
[technical -  Main processing]
Troubleshooting steps for 401 login errors...

[billing -  Auxiliary processing]
 Suggestions for handling repeated deductions...
```

### 3.2  Why do we need to parallelize instead of just selecting one Agent?

 If only TechnicalAgent is selected, Billing issues may be ignored; If only BillingAgent is selected, The login issue may not be resolved.

 The value of parallel collaboration:

| Business issues |  Benefits of Parallel Collaboration |
|----------|----------------|
| A problem spans multiple domains |  Avoid missing answers |
|  Users submit multiple requests at one time | Processing by field,More complete |
|  Exclusive Agent has different abilities |  The main agent is responsible for the main appeal, Assist Agent to supplement relevant professional opinions |
|  Observable routing required | Return `primary_agent`,`supporting_agents`,`routing_reason`  and domain scores |

## 4. When will it be downgraded to GeneralAgent?

 Downgrade is a system reliability strategy. Even if there is a problem with the dedicated Agent,Also try to give users a generic reply.

 Situations that will downgrade:

|  Situation | Results |
|------|------|
|  No instances available for target Agent type |  Using GeneralAgent |
| TechnicalAgent  Execution failed | Downgrade to GeneralAgent |
| BillingAgent  Execution failed | Downgrade to GeneralAgent |
| LLM  Call exception | Return to general error message |

Business effect:

```text
 Dedicated Agent failed -> GeneralAgent  Keep the whole story in mind
```

 This way the user will not directly see the system crash, Instead received "Try again later" or general handling recommendations.

## 5.  When will a session be compressed?

AgentCore  The latest messages of the current session will be stored in Redis. It’s called working memory.

Default rules:

```text
WORKING_MAX = 20
COMPRESS_AT = 15
```

When the same
When  `user_id + conv_id` 's working memory reaches 15 messages, Compression will be triggered.

### 5.1  Before compression
There may be many rounds of messages in

Redis :

```text
user: Hello
assistant: Hello, How can I help you?
user: I want a refund
assistant: Please provide order number
...
```

### 5.2  When compressing

 The system will:

```text
Old News -> LLM  Summary ->  Session summary
```

 Then do three things:

```text
1.  Summary writing Redis summary:{user_id}:{conv_id}
2.  Digest write to ChromaDB episodic
3. Redis  Working memory only retains the latest 5 items
```

### 5.3 After compression

 The subsequent conversation context consists of three parts:

```text
 Session Summary
Related history
Last 5 messages
```

Business Value:

| Question |  Benefits from Compression |
|------|----------------|
| Conversation too long |  Control prompt length |
| Historical information cannot be lost |  Use summaries to retain key information |
|  We need to check the history later |  Writing to ChromaDB for semantic retrieval |

## 6. When will user portraits be updated?

Every time `/chat`  After the reply is completed, The system will update user portraits asynchronously.

Trigger timing:

```text
Agent Reply completed -> Write this round of conversation -> Update user portrait in the background
```

 Portrait content example:

```json
{
  "preferences": [" I like concise answers", " Frequently inquire about refunds"],
  "entities": {
    "Product": ["Member Service"],
    " Question Type": ["Bill", "Login"]
  }
}
```

Business role:

| User portrait information | Follow-up effects |
|--------------|----------|
|  Preference | Make replies closer to user habits |
|  Common products |  Help Agent understand user context |
|  FAQ Type |  Helps follow-up replies to be more focused |

 NOTE: User portrait update is performed asynchronously. Current reply will not be blocked.

## 7. When will the knowledge base be queried?

 The knowledge base can now be used in two ways:

|  Entrance | Usage |
|------|------|
| `/chat` |  The main dialogue link determines whether to retrieve the knowledge base according to the intent, and put the Top-K results into the Agent context |
| `/search` |  Separate demonstration and debugging query rewrite, Parallel recall,Rearrangement effect |

Typical business problems:

```text
 How long does it take for the refund to arrive?
 What should I do if the order has not arrived for more than 7 days?
 How to calculate membership points?
 How to deal with login 401?
```

Retrieval process:

```text
 Business user query
  ->  Intent identified to determine whether RAG is required
  -> LLM  Query rewriting
  ->  Parallel retrieval of multiple subqueries ChromaDB knowledge_base
  ->  Merge and remove duplicates
  -> LLM Rearrange
  ->  Return to Top-K
  ->  Insert Agent background information
```

 When the knowledge base is unavailable, Can walk fallback, Return interpretable downgrade results, instead of reporting an error directly.

### 7.1  Access
What changes have occurred in the business after  `/chat`

 Before access:

```text
/chat  Mainly relies on LLM common sense + dialogue memory
/search  Display knowledge base search alone
```

 After access:

```text
/chat  Automatically retrieve knowledge_base for business intentions
Agent  Replies will give priority to the knowledge base search results
Intents such as
```

`greeting`,`feedback`,`human_handoff`,`other`  will not trigger knowledge base retrieval, Avoid invalid RAGs interfering with recovery and reduce costs.

 For example, a user asked:

```text
 How long does it take for the refund to arrive?
```

The system will search first
Refund policy in  `knowledge_base` , Then put something like the following into the Agent context:

```text
[Knowledge base search results]
1. Title: Refund Policy
   Content:  After the refund request is submitted, Please allow 1-3 business days for review.After passing the review, Payment will be returned to the original payment account within 5-7 working days.
```

Agent  Then reply based on this content, It can reduce the risk of the model making up business rules out of thin air.

## 8.  When Skills are loaded and injected

Skills  is a hot-loadable business processing specification. Complementary to the knowledge base:

|  Type |  Problem solved |  Example |
|------|------------|------|
| Knowledge Base | What are the business facts? | Refund policy, Shipping instructions,Membership Rules |
| Skills | What should customer service do? | How to clarify information,When to switch to manual work?What words not to say |

 On startup,`api/main.py`  will create `SkillManager`,From
The directory pointed to by  `AGENTCORE_SKILLS_DIR`  loads Skills.The default directory is within the project `./skills`.

 Currently there are three types of built-in Skills:

| Skill | Applicable Agent | Trigger mode |
|-------|------------|----------|
| `general_customer_service` | GeneralAgent |  Hit consultation,After sales,Customer service, Complaint, Transfer to manual and other keywords |
| `technical_support` | TechnicalAgent |  Hit error, Interface,API, Deployment,Log,500,401  and other keywords |
| `billing_support` | BillingAgent |  Hit refund, Deduction,Invoice,Subscribe, Payment, Bill and other keywords |

Injection process:

```text
 User message
  -> Orchestrator Select Agent
  -> BaseAgent._build_system_prompt()
  -> SkillManager.prompt_for(message, agent_type)
  ->  Traverse loaded Skills
  -> Filtering enabled
Skill of =true
  ->  Check whether the agents in Skill front matter contain the current agent_type
  ->  Check if user message hits keywords
  ->  spell system prompt [Dynamic Skills]  Block
```

### 8.1  Specific examples of universal Agent loading Skills

 If the user message is:

```text
Hello, I would like to inquire about the progress of after-sales processing
```

 The system first identifies it as a general consultation.Route to `GeneralAgent`. Then execute:

```text
GeneralAgent
  -> agent_type.value = "general"
  -> BaseAgent._build_system_prompt(req)
  -> SkillManager.prompt_for("Hello, I would like to inquire about the progress of after-sales processing", "general")
```

`SkillManager` Will check `skills/general_customer_service/SKILL.md`  Top configuration:

```yaml
agents: general
keywords: Hello,Hello,Consultation,Help,Customer Service,Order,After sales,Activity,Member,Account,Information,Complaint, Recommendation, Manual, Convert to manual,Processing progress,Service
enabled: true
```

 This Skill meets three conditions at the same time:

| Conditions |  Current results |
|------|----------|
| `enabled=true` |  Satisfaction |
| `agents`  Contains `general` | Satisfied |
|  User message hit `Hello`,`Consultation`,`After sales`  or ` Processing progress` | Satisfied |

Therefore ` General customer service reception specifications`  will be spelled in `GeneralAgent`  system prompt.

 If the same message is routed to `TechnicalAgent`,Due to `general_customer_service`  `agents`  Not included `technical`, It will not be injected.This is designed to avoid generic customer service rules, Technical troubleshooting rules and bill refund rules contaminate each other.

 If the Skill file is modified, can be called:

```bash
curl -X POST http://localhost:8000/skills/reload
```

 The system will rescan the Skill directory. No service restart is required.

 View current loading status:

```bash
curl http://localhost:8000/skills
```

 The returned content will include Skill name, Description,File path, Keywords,Applicable to Agent, Whether to enable and parse error lists.

## 9.  When does Monitor affect routing?

Monitor  Agent and tool performance is collected every 10 seconds.

 Collection indicators:

```text
Agent Success rate
Agent Average latency
 Tool success rate
 Tool average latency
 Number of consecutive tool failures
```

 If an Agent has a low success rate or high latency,Monitor Can calculate `monitor_penalty`  and write back to Orchestrator.

 Route score:

```text
base_score = success_rate * 0.7 + latency_score * 0.3
routing_score = base_score * (1 - monitor_penalty)
```

Business effect:

```text
Poorly performing Agent -> routing_score  Lower ->  Follow-up is less selected
```

 If the same type of Agent is expanded into multiple instances in the future, This mechanism automatically selects better performing instances.

## 10.  Common business scenario examples

###  Scenario 1: General greetings

```text
 User:Hello
Agent:GeneralAgent
 Result:General welcome
```

###  Scenario 2:Technical failure

```text
 User: App login keeps reporting 401
Agent:TechnicalAgent
Skills: Injection technical support processing specifications
 Result: Provides login failure troubleshooting steps. and remind not to disclose Token, Password or verification code
```

###  Scene three:Refund issue

```text
 User: I want a refund, Why hasn’t the payment arrived yet?
Agent:BillingAgent
 Result: Explain the refund review and payment cycle
```

###  Scene four:Technology + bill compounding issues

```text
 User: Login error 401,Moreover, repeated deductions were made
Agent:primary_agent + supporting_agents, For example, the TechnicalAgent master handles,BillingAgent  Auxiliary processing
 Result: After two Agents reply in parallel, they will be processed by the master. Auxiliary processing merge
```

###  Scene five: Billing Skill Constraint Refund Commitment

```text
 User: I want a refund, The account must be received today
Agent:BillingAgent
Skills: Inject bill refund processing specifications
 Result: Explain that the order and payment channel need to be verified first. No commitment” It will definitely arrive today”
```

###  Scene six: Long dialogue

```text
 User has more than 15 consecutive messages in conversation
 System: Trigger working memory compression
 Result: Old messages become digests, Keep the latest 5 items
```

###  Scene seven: Strong complaint

```text
 User:I want to complain, Switch to manual immediately
 System: Flag escalated = true
 Result: The production environment can be transferred to work orders or manual customer service
```

## 11. Business Rules Cheat Sheet

| Trigger condition |  System Behavior |
|----------|----------|
| General consultation |  Using GeneralAgent |
|  Technical keywords or technical intent |  Using TechnicalAgent |
| Refund/debit/invoice/subscription/account issues |  Using BillingAgent |
| GeneralAgent  Handling general inquiries |  Inject universal customer service reception specifications Skill |
| TechnicalAgent  Dealing with technical issues |  Inject technical support processing specifications Skill |
| BillingAgent  Handling billing issues |  Inject bill refund processing specifications Skill |
|  Modify Skill file |  Call `/skills/reload`  Hot loading |
|  Both technical + billing scores reach the threshold | Multi-Agent parallel collaboration, Return to Primary Agent and Secondary Agent |
|  Dedicated Agent failed | Downgrade to GeneralAgent |
|  User requested to switch to manual |  Mark `escalated = true` |
|  Working memory reaches 15 items |  Compressing old messages,Keep the latest 5 items |
|  Each reply is completed |  Asynchronously update user portraits |
| Agent  Low success rate or high latency | Monitor  Write back the rights reduction, Lower routing_score |
|  User passed `/chat`  Question and it is a business intention |  Retrieve the knowledge base and integrate into the Agent context |
|  Knowledge base is unavailable | MCP  Tool returns fallback downgrade results, Main dialog continues running |

