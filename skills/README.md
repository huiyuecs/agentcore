# AgentCore Skills

AgentCore loads Skill packages from `AGENTCORE_SKILLS_DIR` and injects matching guidance into the selected agent's system prompt. Skills keep operational policies, diagnostic procedures, escalation criteria, and safety boundaries outside the application code.

The repository includes three Skill packages:

```text
skills/general_customer_service/SKILL.md  General support and request triage
skills/technical_support/SKILL.md         Technical diagnosis and escalation
skills/billing_support/SKILL.md           Billing, refund, invoice, and payment handling
```

## File format

Each Skill uses its own directory and a `SKILL.md` entry point:

```text
skills/<skill_name>/SKILL.md
```

Example front matter:

```markdown
---
name: Technical support operating policy
description: Diagnostic and escalation guidance for TechnicalAgent
keywords: error,failure,API,deployment,timeout,500,401,log
agents: technical
enabled: true
---
```

The supported fields are:

- `name`: display name included in the injected prompt
- `description`: concise purpose shown by the Skills API
- `keywords`: comma-separated trigger terms
- `agents`: comma-separated agent roles such as `general`, `technical`, or `billing`
- `enabled`: `true` or `false`

## Authoring guidelines

- Put mandatory rules near the beginning because long content is limited by a prompt budget.
- Keep each Skill focused on one operational domain.
- Define the role, workflow, required inputs, escalation conditions, and prohibited actions.
- Never request or expose passwords, verification codes, complete payment-card numbers, API keys, tokens, or private keys.
- Use qualified language for outcomes that require verification or external processing.
- Escalate cases that require privileged access, financial approval, security investigation, or human judgment.

## Hot reload

Reload Skill files without restarting the service:

```bash
curl -X POST http://localhost:8000/skills/reload
```

Inspect loaded Skills and parsing errors:

```bash
curl http://localhost:8000/skills
```
