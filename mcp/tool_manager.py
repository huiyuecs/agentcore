"""
 Highlights:MCP Tool call framework

 Core question: Tool call error ( Incomplete search, Recall bad)How to optimize?

 Answers to this module:
  1.  Query Rewrite (Query Rewriting)——  Use LLM to expand the user's original problem into subqueries from multiple perspectives,
      Merge and remove duplicates,Solved"Incomplete recall" Question.
  2.  Result rearrangement (Reranking)——  Use LLM to score the recall results,Reorder by relevance,
     Solved" Bad recall/poor sorting" Question.
  3.  Fuse (Circuit Breaker)——  Automatically disconnect when continuous failure exceeds the threshold. Prevent avalanches.
  4.  Result cache (TTL Cache)——  The same parameters are directly returned to the cache. Reduce duplicate calls.
  5. Downgrade strategy (Fallback)——  Return meaningful degradation results when tool is unavailable.
"""
import asyncio
import hashlib
import inspect
import json
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple

from anthropic import AsyncAnthropic

from core.llm_utils import extract_text_content

logger = logging.getLogger(__name__)


# ── Data structure ──────────────────────────────────────────────────────────────────

class CircuitState(Enum):
    CLOSED    = "closed"     # Normal
    OPEN      = "open"       #  Melted, Request denied
    HALF_OPEN = "half_open"  #  Detection recovery


@dataclass
class ToolResult:
    success:        bool
    data:           Any
    tool_name:      str
    error:          Optional[str] = None
    cached:         bool = False
    latency_ms:     float = 0.0
    reranked:       bool = False   #  Whether it has been rearranged


@dataclass
class ToolStats:
    """ Tool runtime statistics, for Monitor to read."""
    total:              int = 0
    success:            int = 0
    failed:             int = 0
    total_latency_ms:   float = 0.0
    consecutive_fails:  int = 0

    @property
    def success_rate(self) -> float:
        return self.success / self.total if self.total else 1.0

    @property
    def avg_latency_ms(self) -> float:
        return self.total_latency_ms / self.total if self.total else 0.0


# ── Fuse ────────────────────────────────────────────────────────────────────

class CircuitBreaker:
    """
    Three-state fuse:CLOSED → OPEN → HALF_OPEN → CLOSED

     Open after failure_threshold times in succession;
     Enter HALF_OPEN detection after opening recovery_s seconds;
     Close if detection is successful. Re-open if failed.
    """

    def __init__(self, failure_threshold: int = 5, recovery_s: float = 60.0):
        self.threshold   = failure_threshold
        self.recovery_s  = recovery_s
        self.state       = CircuitState.CLOSED
        self.fail_count  = 0
        self.opened_at:  Optional[float] = None

    def allow(self) -> bool:
        if self.state == CircuitState.CLOSED:
            return True
        if self.state == CircuitState.OPEN:
            if time.monotonic() - self.opened_at >= self.recovery_s:  # type: ignore
                self.state = CircuitState.HALF_OPEN
                return True
            return False
        return True  # HALF_OPEN: Release one detection

    def record_success(self) -> None:
        self.fail_count = 0
        self.state = CircuitState.CLOSED

    def record_failure(self) -> None:
        self.fail_count += 1
        if self.fail_count >= self.threshold:
            self.state     = CircuitState.OPEN
            self.opened_at = time.monotonic()
            logger.warning(f" Fuse open ( Continuous failures {self.fail_count}  times)")


# ──  Tool definition ──────────────────────────────────────────────────────────────────

@dataclass
class Tool:
    name:        str
    description: str
    handler:     Callable                    # async (params, context) -> Any
    schema:      Dict[str, Any]              # JSON Schema
    cache_ttl:   float = 0.0                 # 0 =  Do not cache
    timeout_s:   float = 30.0
    supports_rerank: bool = False            #  Whether to support result rearrangement
    fallback:    Optional[Callable] = None    # sync/async (params, context, error) -> Any

    #  Runtime status ( does not participate in construction)
    stats:   ToolStats    = field(default_factory=ToolStats, init=False)
    breaker: CircuitBreaker = field(default_factory=CircuitBreaker, init=False)


# ── MCP  Tool Manager ────────────────────────────────────────────────────────────

class MCPToolManager:
    """
    MCP  Tool call framework.

     Core Optimization Link ( For search tools):
       User Query →  Query Rewrite (Multi-angle subquery)→  Parallel recall → Result rearrangement → Return to Top-K
    """

    def __init__(self, api_key: str, base_url: Optional[str] = None, model: str = "claude-3-5-sonnet-20241022"):
        kwargs: Dict[str, Any] = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        self._client = AsyncAnthropic(**kwargs)
        self._model  = model
        self._tools: Dict[str, Tool] = {}
        self._cache: Dict[str, tuple] = {}   # key → (result, expire_at, reranked)

    # ── Register/Logout ───────────────────────────────────────────────────────────

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool
        logger.info(f"Registration Tool: {tool.name}")

    def unregister(self, name: str) -> None:
        self._tools.pop(name, None)

    # ──  Core call ──────────────────────────────────────────────────────────────

    async def call(
        self,
        name: str,
        params: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
        *,
        use_cache: bool = True,
        rerank_top_k: int = 0,          # >0  rearranges the results,Take Top-K
    ) -> ToolResult:
        """
         Call tool, Complete execution chain:
           Cache check →  Meltdown check →  Parameter verification →  Execute ( including timeout)→  Optional rearrangement →  Cache write
        """
        tool = self._tools.get(name)
        if not tool:
            return ToolResult(success=False, data=None, tool_name=name, error=f" Tool does not exist: {name}")

        cache_rerank_top_k = rerank_top_k if rerank_top_k > 0 and tool.supports_rerank else 0

        #  Cache hit
        if use_cache and tool.cache_ttl > 0:
            cached = self._get_cache(name, params, cache_rerank_top_k)
            if cached is not None:
                cached_data, cached_reranked = cached
                tool.stats.total += 1
                tool.stats.success += 1
                return ToolResult(
                    success=True,
                    data=cached_data,
                    tool_name=name,
                    cached=True,
                    reranked=cached_reranked,
                )

        #  Meltdown check
        if not tool.breaker.allow():
            error = f"Tool is fusing: {name}, Please try again later"
            return await self._fallback_result(tool, params, context, error)

        t0 = time.monotonic()
        tool.stats.total += 1
        try:
            #  Parameter verification ( According to JSON Schema's required and properties.type)
            self._validate_params(tool, params)

            data = await asyncio.wait_for(self._run_handler(tool, params, context), timeout=tool.timeout_s)
            latency = (time.monotonic() - t0) * 1000

            tool.stats.success += 1
            tool.stats.consecutive_fails = 0
            tool.stats.total_latency_ms += latency
            tool.breaker.record_success()

            # Rearrange ( Search tool for returned list)
            reranked = False
            if rerank_top_k > 0 and tool.supports_rerank and isinstance(data, list):
                query = params.get("query", "")
                data, reranked = await self._rerank(query, data, rerank_top_k), True

            #  Write cache: Cache eventually returns the result, Avoid hitting the original result without rearrangement next time.
            if tool.cache_ttl > 0:
                self._set_cache(name, params, data, tool.cache_ttl, cache_rerank_top_k, reranked)

            return ToolResult(success=True, data=data, tool_name=name,
                              latency_ms=latency, reranked=reranked)

        except asyncio.TimeoutError:
            tool.stats.failed += 1
            tool.stats.consecutive_fails += 1
            tool.breaker.record_failure()
            logger.error(f" Tool timeout: {name} ({tool.timeout_s}s)")
            return await self._fallback_result(tool, params, context, " Execution timeout")

        except Exception as ex:
            tool.stats.failed += 1
            tool.stats.consecutive_fails += 1
            tool.breaker.record_failure()
            logger.error(f"Tool exception: {name} — {ex}")
            return await self._fallback_result(tool, params, context, str(ex))

    async def _fallback_result(
        self,
        tool: Tool,
        params: Dict[str, Any],
        context: Optional[Dict[str, Any]],
        error: str,
    ) -> ToolResult:
        """ Returns downgrade results when tool is unavailable, Instead of exposing null errors directly to the caller."""
        if tool.fallback is None:
            return ToolResult(success=False, data=None, tool_name=tool.name, error=error)
        try:
            data = tool.fallback(params, context, error)
            if asyncio.iscoroutine(data):
                data = await data
            return ToolResult(
                success=True,
                data=data,
                tool_name=tool.name,
                error=error,
            )
        except Exception as ex:
            logger.error(f" Tool downgrade failed: {tool.name} — {ex}")
            return ToolResult(success=False, data=None, tool_name=tool.name, error=f"{error}; fallbackFailed: {ex}")

    async def _run_handler(
        self,
        tool: Tool,
        params: Dict[str, Any],
        context: Optional[Dict[str, Any]],
    ) -> Any:
        """
         Execution tool handler.

         Prioritize support for async handler; If the history tool is still a synchronous function, is put into the thread pool for execution.
         Avoid blocking the event loop.
        """
        if inspect.iscoroutinefunction(tool.handler):
            return await tool.handler(params, context)
        result = await asyncio.to_thread(tool.handler, params, context)
        if inspect.isawaitable(result):
            return await result
        return result

    # ──  Query Rewrite ( Solve incomplete recall)────────────────────────────────────────────────

    async def rewrite_query(self, query: str, n: int = 3) -> List[str]:
        """
         Use LLM to rewrite the original query into n subqueries from different angles.

         Purpose: A single query can often only recall documents from a certain angle.
         Multi-angle subqueries are merged after parallel retrieval, Significantly improves recall rate.

         Example:
          Original: "Refund Process"
          Rewrite: ["How to apply for a refund", "How many days does it take to get a refund?", "What is the refund policy?"]
        """
        prompt = f""" Rewrite the following user query as {n}  Search subqueries from different angles, is used to search the knowledge base.
 Requirements: Each subquery angle is different, Covers different aspects of the original problem.
Original query: "{query}"
 Returns JSON array,For example: [" Subquery 1", " Subquery 2", " Subquery 3"]"""
        prompt = self._clean_text(prompt)
        try:
            resp = await self._client.messages.create(
                model=self._model, max_tokens=256, temperature=0.3,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = extract_text_content(resp.content)
            s, e = raw.find("["), raw.rfind("]") + 1
            queries = json.loads(raw[s:e])
            #  The original query is also retained,Remove duplicates
            return list(dict.fromkeys([query] + queries))
        except Exception as ex:
            logger.warning(f" Query rewrite failed, Using original query: {ex}")
            return [query]

    async def search_with_rewrite(
        self,
        tool_name: str,
        query: str,
        top_k: int = 5,
        context: Optional[Dict[str, Any]] = None,
    ) -> ToolResult:
        """
         Complete search optimization link:Query rewriting →  Parallel recall → Remove duplicates → Rearrange → Top-K

        This is the solution" Incomplete search,Recall is not good
The complete scheme of ".
        """
        # 1. Query rewritten: Generate multi-angle subqueries
        sub_queries = await self.rewrite_query(query, n=3)
        logger.info(f"Query rewriting: {query!r} → {sub_queries}")

        # 2.  Parallel recall: All subqueries are retrieved simultaneously
        recall_k = max(top_k, 5)
        tasks = [
            self.call(tool_name, {"query": q, "top_k": recall_k}, context, use_cache=True)
            for q in sub_queries
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 3.  Merge Deduplication ( Deduplication by content hash)
        seen, merged = set(), []
        for r in results:
            if isinstance(r, ToolResult) and r.success and isinstance(r.data, list):
                for item in r.data:
                    key = hashlib.md5(str(item).encode()).hexdigest()
                    if key not in seen:
                        seen.add(key)
                        merged.append(item)

        if not merged:
            return ToolResult(success=False, data=[], tool_name=tool_name, error=" No results for all subqueries")

        # 4. Rearrange: Use LLM to score merged results by relevance,Take Top-K
        reranked = await self._rerank(query, merged, top_k)
        return ToolResult(success=True, data=reranked, tool_name=tool_name, reranked=True)

    # ──  Result rearrangement ( Resolving the recall is not good)──────────────────────────────────────────────

    async def _rerank(self, query: str, items: List[Any], top_k: int) -> List[Any]:
        """
         Re-scoring recall results using LLM.

         To solve the problem: The similarity score for vector retrieval is not equal to" Useful to users",
        LLM  Can understand semantic correlations, Top-K quality improved significantly after rearrangement.
        """
        if len(items) <= top_k:
            return items

        #  Serialize results to text for LLM scoring
        items_text = "\n".join(f"{i}. {json.dumps(item, ensure_ascii=False)[:200]}"
                               for i, item in enumerate(items))
        prompt = f""" According to user query, Score the following search results according to their relevance (0-10), Return JSON array.
User Query: "{query}"
Search results:
{items_text}

Return format ( List of indexes in descending order of relevance): [ Most relevant index, ...,  Least relevant index]
 Only JSON arrays are returned,No other text is required."""
        prompt = self._clean_text(prompt)

        try:
            resp = await self._client.messages.create(
                model=self._model, max_tokens=256, temperature=0.0,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = extract_text_content(resp.content)
            s, e = raw.find("["), raw.rfind("]") + 1
            order: List[int] = json.loads(raw[s:e])
            reranked = [items[i] for i in order if 0 <= i < len(items)]
            return reranked[:top_k]
        except Exception as ex:
            logger.warning(f" Reordering failed, Return to original order: {ex}")
            return items[:top_k]

    # ──  Cache ──────────────────────────────────────────────────────────────────

    def _cache_key(self, name: str, params: Dict, rerank_top_k: int = 0) -> str:
        payload = {"params": params, "rerank_top_k": rerank_top_k}
        return f"{name}:{hashlib.md5(json.dumps(payload, sort_keys=True).encode()).hexdigest()}"

    def _get_cache(self, name: str, params: Dict, rerank_top_k: int = 0) -> Optional[Tuple[Any, bool]]:
        key = self._cache_key(name, params, rerank_top_k)
        if key in self._cache:
            data, expire_at, reranked = self._cache[key]
            if time.monotonic() < expire_at:
                return data, reranked
            del self._cache[key]
        return None

    def _set_cache(
        self,
        name: str,
        params: Dict,
        data: Any,
        ttl: float,
        rerank_top_k: int = 0,
        reranked: bool = False,
    ) -> None:
        if len(self._cache) >= 5000:
            # Clear the oldest 1/4
            for k in list(self._cache)[:1250]:
                del self._cache[k]
        self._cache[self._cache_key(name, params, rerank_top_k)] = (data, time.monotonic() + ttl, reranked)

    # ──  Parameter verification ──────────────────────────────────────────────────────────────

    _TYPE_MAP = {"string": str, "number": (int, float), "integer": int, "boolean": bool, "array": list, "object": dict}

    def _validate_params(self, tool: Tool, params: Dict[str, Any]) -> None:
        """ According to the JSON Schema verification parameters of the tool, ValueError is thrown when illegal."""
        schema = tool.schema
        required = schema.get("required", [])
        properties = schema.get("properties", {})

        for field in required:
            if field not in params:
                raise ValueError(f"Tools {tool.name}  Required parameter missing: {field}")

        for key, value in params.items():
            if key in properties:
                expected_type = properties[key].get("type")
                if expected_type and expected_type in self._TYPE_MAP:
                    if not isinstance(value, self._TYPE_MAP[expected_type]):
                        raise ValueError(
                            f"Tools {tool.name}  Parameters {key} Type error: Expectation {expected_type}, Actual {type(value).__name__}"
                        )

    @staticmethod
    def _clean_text(value: Any) -> str:
        """ Remove Unicode surrogate characters, Avoid LLM request encoding failure."""
        if value is None:
            return ""
        if not isinstance(value, str):
            value = str(value)
        return value.encode("utf-8", errors="ignore").decode("utf-8")

    # ──  Statistics ──────────────────────────────────────────────────────────────────

    def get_stats(self) -> Dict[str, Any]:
        return {
            name: {
                "total": t.stats.total,
                "success_rate": round(t.stats.success_rate, 3),
                "avg_latency_ms": round(t.stats.avg_latency_ms, 1),
                "consecutive_fails": t.stats.consecutive_fails,
                "circuit_state": t.breaker.state.value,
            }
            for name, t in self._tools.items()
        }
