"""
 Highlights: End-to-end intent recognition

Three-way fusion strategy:
  1. LLM  Semantic understanding ( weight 70%)——  Main force, Understand complex semantics and context
  2. Embedding  Vector similarity ( weight 20%)——  Quickly match common expressions
  3.  Keyword pattern matching ( weight 10%)——  Zero delay

 Three-way results merged via weighted voting, Downgrade to OTHER when confidence is below threshold.
LLM  and Embedding are called in parallel, No serial wait.
"""
import asyncio
import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from anthropic import AsyncAnthropic

from core.llm_utils import extract_text_content

logger = logging.getLogger(__name__)


class IntentCategory(Enum):
    QUERY      = "query"       #  Query information
    COMPLAINT  = "complaint"   #  Complaint dissatisfaction
    REQUEST    = "request"     #  Request operation
    GREETING   = "greeting"    # Greetings
    ESCALATION = "escalation"  #  Request to upgrade/convert to manual
    TECHNICAL  = "technical"   # Technical issues
    BILLING    = "billing"     # Billing/Refund
    ACCOUNT    = "account"     # Account Management
    FEEDBACK   = "feedback"    # Positive feedback
    ORDER_STATUS = "order_status"        # Order status
    LOGISTICS = "logistics"              # Logistics distribution
    REFUND = "refund"                    # Refund/Return
    INVOICE = "invoice"                  # Invoice
    PAYMENT_ISSUE = "payment_issue"      #  Payment/debit abnormality
    ACCOUNT_SECURITY = "account_security" #  Account security
    TECHNICAL_LOGIN = "technical_login"  #  Login authentication failure
    TECHNICAL_CRASH = "technical_crash"  #  Crash/Error code
    HUMAN_HANDOFF = "human_handoff"      #  Convert to manual
    OTHER      = "other"


class UrgencyLevel(Enum):
    LOW      = 1
    MEDIUM   = 2
    HIGH     = 3
    CRITICAL = 4


@dataclass
class IntentResult:
    intent:     IntentCategory
    confidence: float
    urgency:    UrgencyLevel
    intent_group: str
    entities:   Dict[str, List[str]]   #  Entity extracted from message
    reasoning:  str
    latency_ms: float
    source_scores: Dict[str, float] = field(default_factory=dict)


# ── Few-shot  Template ( for both LLM examples and Embedding matching)────────────────────────
_TEMPLATES: Dict[IntentCategory, List[str]] = {
    IntentCategory.QUERY:      ["What is the status of my order?", "How to reset password?", "When will the express arrive?"],
    IntentCategory.COMPLAINT:  ["Waiting for several hours!", "The service is terrible!", " No one has been handling it!"],
    IntentCategory.REQUEST:    ["Help me cancel the order", "I need to change the address", " Please assist in refunding"],
    IntentCategory.GREETING:   ["Hello", "Hi,Is anyone there?", "Good morning"],
    IntentCategory.ESCALATION: ["I want to complain!", " Transfer to manual customer service", " Find your manager"],
    IntentCategory.TECHNICAL:  [" App keeps crashing", "Unable to log in", " 500 error occurred"],
    IntentCategory.BILLING:    ["Why was the payment deducted twice?", " Apply for a refund", "Invoice problem"],
    IntentCategory.ACCOUNT:    ["Modify email", " Cancel account", "Update personal information"],
    IntentCategory.FEEDBACK:   [" The service is great!", "Very satisfied", " Give a good review"],
    IntentCategory.ORDER_STATUS: ["What is the status of my order now?", " Has the order been shipped?", " At what stage is the order processed?"],
    IntentCategory.LOGISTICS: ["When will the express arrive?", " Logistics has not been updated", "How long does delivery take?"],
    IntentCategory.REFUND: ["I want to apply for a refund", " How to handle returns and refunds?", " How long does it take for the refund to arrive?"],
    IntentCategory.INVOICE: ["Help me issue an invoice", " How to change the invoice title?", " Where is the electronic invoice?"],
    IntentCategory.PAYMENT_ISSUE: [" Why are the charges deducted repeatedly?", " What should I do if the payment fails?", " Overpaid this month"],
    IntentCategory.ACCOUNT_SECURITY: ["Account stolen", " Abnormal login found", "I want to reset my password"],
    IntentCategory.TECHNICAL_LOGIN: [" Login keeps reporting 401", "Verification code not received", " Unable to log in to account"],
    IntentCategory.TECHNICAL_CRASH: [" App keeps crashing", " The page reported a 500 error", " System crashes"],
    IntentCategory.HUMAN_HANDOFF: [" Transfer to manual customer service", "I want to find artificial intelligence", " Please upgrade"],
}

_SPECIFIC_INTENTS = {
    IntentCategory.ORDER_STATUS,
    IntentCategory.LOGISTICS,
    IntentCategory.REFUND,
    IntentCategory.INVOICE,
    IntentCategory.PAYMENT_ISSUE,
    IntentCategory.ACCOUNT_SECURITY,
    IntentCategory.TECHNICAL_LOGIN,
    IntentCategory.TECHNICAL_CRASH,
    IntentCategory.HUMAN_HANDOFF,
}

_GENERIC_INTENTS = {
    IntentCategory.QUERY,
    IntentCategory.BILLING,
    IntentCategory.TECHNICAL,
    IntentCategory.ACCOUNT,
    IntentCategory.ESCALATION,
}

_INTENT_GROUPS: Dict[IntentCategory, IntentCategory] = {
    IntentCategory.ORDER_STATUS: IntentCategory.QUERY,
    IntentCategory.LOGISTICS: IntentCategory.QUERY,
    IntentCategory.REFUND: IntentCategory.BILLING,
    IntentCategory.INVOICE: IntentCategory.BILLING,
    IntentCategory.PAYMENT_ISSUE: IntentCategory.BILLING,
    IntentCategory.ACCOUNT_SECURITY: IntentCategory.ACCOUNT,
    IntentCategory.TECHNICAL_LOGIN: IntentCategory.TECHNICAL,
    IntentCategory.TECHNICAL_CRASH: IntentCategory.TECHNICAL,
    IntentCategory.HUMAN_HANDOFF: IntentCategory.ESCALATION,
}

# Emergency keyword
_URGENCY_KEYWORDS = {
    UrgencyLevel.CRITICAL: ["Urgent", "emergency", "urgent", "asap", "immediately"],
    UrgencyLevel.HIGH:     ["Today", "Right away", " ASAP", "hurry", "now"],
    UrgencyLevel.MEDIUM:   ["This week", "soon", "Hurry up"],
}


def _cosine(a: List[float], b: List[float]) -> float:
    """ Pure Python cosine similarity, No dependency on numpy."""
    dot = sum(x * y for x, y in zip(a, b))
    na  = sum(x * x for x in a) ** 0.5
    nb  = sum(x * x for x in b) ** 0.5
    return dot / (na * nb) if na and nb else 0.0


class IntentRecognizer:
    """
     End-to-end intent recognizer.

     No local models are loaded during initialization, All AI capabilities are called through the Anthropic API.
     Template Embedding is lazy loaded and cached on first request, Subsequent reuse.
    """

    def __init__(
        self,
        api_key: str,
        base_url: Optional[str] = None,
        model: str = "claude-3-5-sonnet-20241022",
        confidence_threshold: float = 0.5,
    ):
        kwargs: Dict[str, Any] = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        self.client    = AsyncAnthropic(**kwargs)
        self.model     = model
        self.threshold = confidence_threshold
        #  Native character n-gram vectors are always available; If the client exposes embeddings resources in the future,
        # _embed_text  Remote vectors will be tried first, Otherwise automatically fall back to the local vector.
        self._embedding_enabled = True

        self._tpl_embeddings: Dict[IntentCategory, List[List[float]]] = {}
        self._cache: Dict[str, IntentResult] = {}
        self.cache_hits   = 0
        self.cache_misses = 0

    # ── Public interface ──────────────────────────────────────────────────────────────

    async def recognize(
        self,
        message: str,
        history: Optional[List[Dict[str, str]]] = None,
    ) -> IntentResult:
        """
         Identify user intent.

        history Format:[{"role": "user"/"assistant", "content": "..."}]
        """
        key = self._cache_key(message, history)
        if key in self._cache:
            self.cache_hits += 1
            return self._cache[key]
        self.cache_misses += 1

        t0 = time.monotonic()

        # LLM  Parallel with Embedding (Embedding  Skip if not available)
        llm_task = asyncio.create_task(self._llm_recognize(message, history))
        emb_task = asyncio.create_task(self._embedding_recognize(message)) if self._embedding_enabled else None
        pat      = self._pattern_recognize(message)

        if emb_task:
            llm, emb = await asyncio.gather(llm_task, emb_task)
        else:
            llm = await llm_task
            emb = {"intent": IntentCategory.OTHER, "confidence": 0.0}

        intent, confidence, source_scores = self._vote(llm, emb, pat)
        entities = self._extract_entities(message)
        urgency  = self._urgency(message, intent)

        result = IntentResult(
            intent=intent,
            confidence=confidence,
            urgency=urgency,
            intent_group=self._intent_group(intent),
            entities=entities,
            reasoning=llm.get("reasoning", ""),
            latency_ms=(time.monotonic() - t0) * 1000,
            source_scores=source_scores,
        )

        # LRU  Cache
        if len(self._cache) >= 1000:
            for k in list(self._cache)[:500]:
                del self._cache[k]
        self._cache[key] = result
        return result

    def learn(self, message: str, correct: IntentCategory) -> None:
        """ Online learning: Add the corrected sample to the template, Clear the corresponding Embedding cache."""
        tpls = _TEMPLATES.setdefault(correct, [])
        if message not in tpls:
            tpls.append(message)
            self._tpl_embeddings.pop(correct, None)  # Recalculate next time
            self._cache.clear()  #  Old cache may correspond to outdated results after template update
            logger.info(f" Learning new samples → {correct.value}: {message[:40]}")

    # ── Three-way identification strategy ──────────────────────────────────────────────────────────

    async def _llm_recognize(
        self,
        message: str,
        history: Optional[List[Dict[str, str]]],
    ) -> Dict[str, Any]:
        """ Strategy 1:LLM  Semantic understanding (Few-shot + Context)."""
        message = self._clean_text(message)
        #  Building Few-shot Example
        examples = "\n".join(
            f'  Message: "{t}" →  Intention: {cat.value}'
            for cat, tpls in _TEMPLATES.items()
            for t in tpls[:1]  #  Take 1 item from each category,Control prompt length
        )
        # Context of the last 3 rounds of dialogue
        ctx = ""
        if history:
            ctx = "\n Recent conversations:\n" + "\n".join(
                f"  {self._clean_text(m.get('role', 'user'))}: {self._clean_text(m.get('content', ''))}"
                for m in history[-3:]
            )

        prompt = f"""You are an expert in customer service intent analysis. Determine user intent based on examples, Return JSON.
 If user questions can match fine-grained business intent, Please prioritize returning fine-grained intents. rather than broad categories.
 For example, refund priority is returned to refund, Invoices are returned first, Login failures return technical_login first.

        {ctx}
         User message: "{message}"

Return format ( JSON only, No other text required):
{{"intent": "< Intent value>", "confidence": <0-1>, "reasoning": "<One sentence explanation>"}}

 Optional intent: {", ".join(c.value for c in IntentCategory)}"""
        prompt = self._clean_text(prompt)

        try:
            resp = await self.client.messages.create(
                model=self.model,
                max_tokens=256,
                temperature=0.1,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = extract_text_content(resp.content)
            s, e = raw.find("{"), raw.rfind("}") + 1
            data = json.loads(raw[s:e])
            try:
                data["intent"] = IntentCategory(data["intent"])
            except ValueError:
                data["intent"] = IntentCategory.OTHER
            return data
        except Exception as ex:
            logger.warning(f"LLM  Recognition failed: {ex}")
            return {"intent": IntentCategory.OTHER, "confidence": 0.0, "reasoning": "LLM Failed", "failed": True}

    async def _embedding_recognize(self, message: str) -> Dict[str, Any]:
        """ Strategy 2:Embedding  Vector similarity matching."""
        try:
            await self._load_template_embeddings()
            msg_vec = await self._embed_text(message)

            best_cat, best_score = IntentCategory.OTHER, 0.0
            for cat, vecs in self._tpl_embeddings.items():
                score = max(_cosine(msg_vec, v) for v in vecs)
                if score > best_score:
                    best_score, best_cat = score, cat

            return {"intent": best_cat, "confidence": best_score}
        except Exception as ex:
            logger.warning(f"Embedding  Recognition failed: {ex}")
            return {"intent": IntentCategory.OTHER, "confidence": 0.0}

    def _pattern_recognize(self, message: str) -> Dict[str, Any]:
        """ Strategy 3: Keyword pattern matching ( Sync, Zero delay)."""
        msg = message.lower()
        specific_patterns = {
            IntentCategory.HUMAN_HANDOFF: [" Convert to manual", "Manual customer service", " Looking for labor"],
            IntentCategory.ORDER_STATUS: ["Order status", "Has it been shipped?", "Where to process", "order status"],
            IntentCategory.LOGISTICS: ["Logistics", "Express delivery", " Delivery", " Waybill", "delivery", "shipping"],
            IntentCategory.REFUND: ["Refund", "Return", "refund", "return"],
            IntentCategory.INVOICE: ["Invoice", "Look up", "Tax ID number", "invoice"],
            IntentCategory.PAYMENT_ISSUE: [" Repeated deductions", "More deductions", " Payment failed", "Deduction", "payment failed"],
            IntentCategory.ACCOUNT_SECURITY: [" Stolen", " Abnormal login", "Reset password", " Two-Step Verification", "Safety"],
            IntentCategory.TECHNICAL_LOGIN: ["Unable to log in", " Login failed", "401", "Verification code"],
            IntentCategory.TECHNICAL_CRASH: ["Crash", "Crash back", "500", " Error report", "crash"],
        }
        generic_patterns = {
            IntentCategory.ESCALATION: ["Complaint", " Manager", "supervisor"],
            IntentCategory.COMPLAINT:  ["Too bad", "Oops", "horrible", "Waiting for a long time"],
            IntentCategory.QUERY:      ["?", "?", "How?", "What", "status"],
            IntentCategory.REQUEST:    ["Help me", "Required", "please", "help"],
            IntentCategory.GREETING:   ["Hello", "Hi", "hello", "hi"],
            IntentCategory.BILLING:    ["Refund", "Deduction", "Invoice", "refund"],
            IntentCategory.TECHNICAL:  [" Crash", " Error report", "error", "crash"],
            IntentCategory.ACCOUNT:    [" Password", " Email", "Account", "password"],
        }

        best_cat, best_score = self._best_pattern_match(msg, specific_patterns)
        if best_cat != IntentCategory.OTHER:
            return {"intent": best_cat, "confidence": best_score}

        best_cat, best_score = self._best_pattern_match(msg, generic_patterns)
        return {"intent": best_cat, "confidence": best_score}

    # ──  Vote to merge ──────────────────────────────────────────────────────────────

    def _vote(self, llm: Dict, emb: Dict, pat: Dict) -> tuple[IntentCategory, float, Dict[str, float]]:
        """ Weighted voting.Return to final intention, Fusion of confidence and scores from various sources."""
        source_scores = {
            "llm": float(llm.get("confidence", 0.0) or 0.0),
            "embedding": float(emb.get("confidence", 0.0) or 0.0),
            "pattern": float(pat.get("confidence", 0.0) or 0.0),
        }
        if llm.get("failed"):
            if emb.get("intent") != IntentCategory.OTHER and emb.get("confidence", 0.0) > 0:
                return emb["intent"], source_scores["embedding"], source_scores
            if pat.get("intent") != IntentCategory.OTHER and pat.get("confidence", 0.0) > 0:
                return pat["intent"], source_scores["pattern"], source_scores
            return IntentCategory.OTHER, 0.0, source_scores

        if self._embedding_enabled:
            weights = [(llm, 0.7), (emb, 0.2), (pat, 0.1)]
        else:
            weights = [(llm, 0.85), (pat, 0.15)]
        scores: Dict[IntentCategory, float] = {}
        for result, w in weights:
            cat  = result.get("intent", IntentCategory.OTHER)
            conf = result.get("confidence", 0.0)
            scores[cat] = scores.get(cat, 0.0) + w * conf

        best = max(scores, key=scores.get)  # type: ignore
        best_score = scores[best]
        pat_intent = pat.get("intent", IntentCategory.OTHER)
        pat_conf = float(pat.get("confidence", 0.0) or 0.0)
        if best in _GENERIC_INTENTS and pat_intent in _SPECIFIC_INTENTS and pat_conf >= 0.5 and best_score < 0.8:
            source_scores["refined_by_pattern"] = pat_conf
            return pat_intent, max(best_score, pat_conf), source_scores
        if best_score < self.threshold:
            return IntentCategory.OTHER, best_score, source_scores
        return best, best_score, source_scores

    # ──  Entity extraction ──────────────────────────────────────────────────────────────

    def _extract_entities(self, message: str) -> Dict[str, List[str]]:
        """ Use rules to extract high-value entities, Avoid additional calls to LLM for each identification."""
        message = self._clean_text(message)
        return {
            "order_id": self._unique(re.findall(r"(?:Order number?|order(?:_id)?|#)\s*[::#]?\s*([A-Za-z0-9_-]{4,32})", message, re.I)),
            "product": [],
            "date": self._unique(re.findall(r"(Today|Tomorrow|Yesterday|This week|This week|Next week|\d{4}[-/. year]\d{1,2}[-/.Month]\d{1,2}Day?)", message)),
            "amount": self._unique(re.findall(r"(?:¥|CNY\s*)\d+(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?\s*(?:yuan|RMB|CNY|USD)", message, re.I)),
            "error_code": self._unique(
                re.findall(r"(?:error(?:_code)?| Error code| Status code|http)\s*[::#]?\s*([45]\d{2})\b", message, re.I)
                + re.findall(r"\b([45]\d{2})\b", message)
            ),
        }

    # ──  Auxiliary ──────────────────────────────────────────────────────────────────

    async def _load_template_embeddings(self) -> None:
        """ Lazy loading of all templates' Embedding( Only executed on first call)."""
        missing = [cat for cat in _TEMPLATES if cat not in self._tpl_embeddings]
        if not missing:
            return

        all_texts = [t for cat in missing for t in _TEMPLATES[cat]]
        vecs = [await self._embed_text(text) for text in all_texts]
        idx = 0
        for cat in missing:
            n = len(_TEMPLATES[cat])
            self._tpl_embeddings[cat] = vecs[idx: idx + n]
            idx += n

    async def _embed_text(self, text: str) -> List[float]:
        """
         Generate text vectors.

         If future official/compatible clients provide embeddings.create, Remote vectors will be used first;
         When the current Anthropic SDK does not have this resource, Degenerate into character n-gram hash vectors. This will not happen because
        Embedding  Loss of service causes three-way convergence outage.
        """
        embeddings = getattr(self.client, "embeddings", None)
        if embeddings is not None:
            try:
                resp = await embeddings.create(model="voyage-3-lite", input=[text])
                return list(resp.data[0].embedding)
            except Exception as ex:
                logger.warning(f" Remote Embedding failed, Use local vectors to find out: {ex}")

        return self._local_embedding(text)

    @staticmethod
    def _local_embedding(text: str, dims: int = 256) -> List[float]:
        """ Stable character n-gram hash vector, Semantic approximate matching without remote embedding."""
        normalized = text.lower().strip()
        vec = [0.0] * dims
        tokens = set()
        for n in (1, 2, 3):
            if len(normalized) >= n:
                tokens.update(normalized[i:i + n] for i in range(len(normalized) - n + 1))
        if not tokens:
            tokens.add(normalized)

        for token in tokens:
            digest = hashlib.md5(token.encode("utf-8")).digest()
            idx = int.from_bytes(digest[:4], "big") % dims
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vec[idx] += sign
        return vec

    def _urgency(self, message: str, intent: IntentCategory) -> UrgencyLevel:
        msg = message.lower()
        for level, kws in _URGENCY_KEYWORDS.items():
            if any(kw in msg for kw in kws):
                return level
        if intent in (IntentCategory.ESCALATION, IntentCategory.HUMAN_HANDOFF):
            return UrgencyLevel.HIGH
        if intent == IntentCategory.COMPLAINT:
            return UrgencyLevel.MEDIUM
        return UrgencyLevel.LOW

    def _cache_key(self, message: str, history: Optional[List[Dict[str, str]]] = None) -> str:
        payload = {"message": self._clean_text(message)[:200]}
        if history:
            payload["history"] = [
                {
                    "role": self._clean_text(item.get("role", ""))[:20],
                    "content": self._clean_text(item.get("content", ""))[:160],
                }
                for item in history[-3:]
            ]
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        return hashlib.md5(raw.encode("utf-8")).hexdigest()

    @staticmethod
    def _unique(values: List[str]) -> List[str]:
        return list(dict.fromkeys(value.strip() for value in values if value and value.strip()))

    @staticmethod
    def _best_pattern_match(
        message: str,
        patterns: Dict[IntentCategory, List[str]],
    ) -> tuple[IntentCategory, float]:
        best_cat, best_score = IntentCategory.OTHER, 0.0
        for cat, kws in patterns.items():
            hits = sum(1 for kw in kws if kw in message)
            if not hits:
                continue
            #  A single clear business keyword gives available confidence; Improve confidence when multiple keywords are hit.
            score = min(1.0, 0.5 + 0.25 * (hits - 1))
            if score > best_score:
                best_score, best_cat = score, cat
        return best_cat, best_score

    @staticmethod
    def _intent_group(intent: IntentCategory) -> str:
        return _INTENT_GROUPS.get(intent, intent).value

    @staticmethod
    def _clean_text(value: Any) -> str:
        """ Remove Unicode surrogate characters, Avoid HTTP client crash when encoding prompt."""
        if value is None:
            return ""
        if not isinstance(value, str):
            value = str(value)
        return value.encode("utf-8", errors="ignore").decode("utf-8")

    @property
    def cache_stats(self) -> Dict[str, Any]:
        total = self.cache_hits + self.cache_misses
        return {
            "size": len(self._cache),
            "hits": self.cache_hits,
            "misses": self.cache_misses,
            "hit_rate": self.cache_hits / total if total else 0.0,
        }
