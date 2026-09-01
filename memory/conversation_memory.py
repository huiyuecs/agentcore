"""
 Highlights:Multiple rounds of dialogue memory management

 Three-level memory architecture, Simulate human memory mechanism:
  1.  Working memory (Redis)——  The last N messages of the current session, Millisecond level reading and writing
  2.  Episodic memory (ChromaDB)——  Historical conversations across sessions, Search by semantic similarity
  3.  User portrait (ChromaDB)——  Long-term preferences and entities extracted from conversations

Key design:
  -  Three-level memory fusion during context construction, Sort by importance + timeliness
  -  Automatic compression when working memory exceeds threshold (LLM  Abstract), Prevent context explosion
  -  All Embeddings are generated through the Anthropic API, No local model
"""
import hashlib
import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional

import chromadb
import redis.asyncio as redis
from anthropic import AsyncAnthropic

from core.llm_utils import extract_text_content

logger = logging.getLogger(__name__)


class MsgRole(Enum):
    USER      = "user"
    ASSISTANT = "assistant"
    SYSTEM    = "system"


@dataclass
class Message:
    role:       MsgRole
    content:    str
    timestamp:  datetime = field(default_factory=datetime.now)
    metadata:   Dict[str, Any] = field(default_factory=dict)


@dataclass
class MemoryContext:
    """ The complete context passed to the Agent."""
    recent_messages:  List[Message]   #  Working memory: Recent conversations
    relevant_history: List[str]       #  Episodic memory: Semantically related historical fragments
    user_profile:     Dict[str, Any]  #  User portrait:Preference, Common entities
    summary:          str             #  Current session summary (After compression)

    @staticmethod
    def _clean(text: str) -> str:
        """ Remove Unicode surrogate characters, Prevent encoding errors."""
        return text.encode("utf-8", errors="ignore").decode("utf-8")

    def to_prompt_text(self) -> str:
        """ Format memory context into text usable by LLM."""
        parts = []
        if self.summary:
            parts.append(f"[ Session Summary]\n{self._clean(self.summary)}")
        if self.relevant_history:
            parts.append("[Related history]\n" + "\n".join(f"- {self._clean(h)}" for h in self.relevant_history[:3]))
        if self.user_profile:
            parts.append(f"[ User portrait]\n{json.dumps(self.user_profile, ensure_ascii=True)}")
        if self.recent_messages:
            parts.append("[ Recent conversations]")
            for m in self.recent_messages[-8:]:
                parts.append(f"{m.role.value}: {self._clean(m.content)}")
        return "\n\n".join(parts)


class MemoryManager:
    """
     Level 3 memory manager.

     Working memory storage Redis (TTL 24h), Situational memory and user portrait storage ChromaDB ( Persistence).
    """

    WORKING_MAX   = 20    # The maximum number of working memory items, Trigger compression if exceeded
    COMPRESS_AT   = 15    #  Compress when reaching this number.Keep summary + latest 5 items
    HISTORY_TOP_K = 5     #  Number of items returned by episodic memory retrieval
    SUMMARY_MAX_CHARS = 800
    PROFILE_DOC_PREFIX = "user_profile:"

    def __init__(
        self,
        redis_url:    str = "redis://localhost:6379/0",
        chroma_host:  str = "localhost",
        chroma_port:  int = 8000,
        chroma_path:  str = "./data/chroma",
        api_key:      str = "",
        base_url:     Optional[str] = None,
        model:        str = "claude-3-5-sonnet-20241022",
    ):
        kwargs: Dict[str, Any] = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        self._client = AsyncAnthropic(**kwargs)
        self._model  = model

        self._redis = redis.from_url(redis_url, decode_responses=True)

        # ChromaDB: Prioritize connection to independent services (docker compose  mode), If the connection fails, it will be downgraded to local embedded
        try:
            # HttpClient  ChromaDB telemetry is also initialized by default; Explicitly turning off avoids posthog compatibility error logging.
            chroma = chromadb.HttpClient(
                host=chroma_host,
                port=chroma_port,
                settings=chromadb.Settings(anonymized_telemetry=False),
            )
            chroma.heartbeat()  #  Test connection
            logger.info(f"ChromaDB  Connected: {chroma_host}:{chroma_port}")
        except Exception:
            logger.info(f"ChromaDB  Service is unavailable, Using native embedded mode: {chroma_path}")
            chroma = chromadb.PersistentClient(
                path=chroma_path,
                settings=chromadb.Settings(anonymized_telemetry=False),
            )

        #  Episodic memory: Store historical conversation fragments
        self._episodic = chroma.get_or_create_collection("episodic")
        #  User portrait: Store extracted preferences and entities
        self._profile  = chroma.get_or_create_collection("user_profile")

    # ──  Write ──────────────────────────────────────────────────────────────────

    async def add_message(
        self,
        user_id: str,
        conv_id: str,
        role:    MsgRole,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """ Write a message to working memory, Automatic compression when exceeding threshold."""
        user_id = self._safe_text(user_id)
        conv_id = self._safe_text(conv_id)
        clean_metadata = {
            self._safe_text(k): self._safe_metadata_value(v)
            for k, v in (metadata or {}).items()
        }
        msg = Message(role=role, content=self._safe_text(content), metadata=clean_metadata)
        key = self._wm_key(user_id, conv_id)

        #  Append to Redis list ( Push left,Latest first)
        await self._redis.lpush(key, json.dumps({
            "role":      msg.role.value,
            "content":   msg.content,
            "ts":        msg.timestamp.isoformat(),
            "metadata":  msg.metadata,
        }))
        await self._redis.expire(key, 86400)  # 24h TTL

        #  Trigger compression when compression threshold is exceeded
        if await self._redis.llen(key) >= self.COMPRESS_AT:
            await self._compress(user_id, conv_id)

    async def update_profile(self, user_id: str, conv_id: str) -> None:
        """
         Extract user preferences from current working memory, Update user portrait.
         Preference extraction using LLM, and then save to ChromaDB (ChromaDB  Built-in embedding, Does not rely on external API).
        """
        user_id = self._safe_text(user_id)
        conv_id = self._safe_text(conv_id)
        messages = await self._get_working_memory(user_id, conv_id)
        if not messages:
            return

        current_profile = await self._get_profile(user_id)

        text = self._safe_text("\n".join(f"{m.role.value}: {m.content}" for m in messages[-10:]))
        profile_ctx = json.dumps(current_profile, ensure_ascii=False) if current_profile else "{}"
        prompt = f""" Extract or update user preferences and key entities from the following conversations and existing user portraits, Return JSON.
Dialogue:
{text}

Already have a portrait:
{profile_ctx}

Return format: {{"preferences": ["..."], "entities": {{"Product": [], " Question type": []}}}}"""
        prompt = self._safe_text(prompt)

        try:
            resp = await self._client.messages.create(
                model=self._model, max_tokens=512, temperature=0.0,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = extract_text_content(resp.content)
            s, e = raw.find("{"), raw.rfind("}") + 1
            profile_data = json.loads(raw[s:e])

            doc_id = self._profile_doc_id(user_id)
            doc_text = self._safe_text(json.dumps(profile_data, ensure_ascii=False))

            try:
                await asyncio.to_thread(self._profile.delete, ids=[doc_id])
            except Exception:
                pass

            #  Directly upload documents, Let ChromaDB built-in model generate embedding( Does not rely on Voyage API)
            await asyncio.to_thread(
                self._profile.add,
                ids=[doc_id],
                documents=[doc_text],
                metadatas=[{
                    "user_id": user_id,
                    "conv_id": conv_id,
                    "updated_at": datetime.now().isoformat(),
                }],
            )
            logger.info(f"User portrait has been updated: {user_id}")
        except Exception as ex:
            logger.warning(f" Failed to update user portrait: {ex}")

    # ── Read ──────────────────────────────────────────────────────────────────

    async def get_context(self, user_id: str, conv_id: str, query: str = "") -> MemoryContext:
        """
         Build a complete memory context.

        query  for retrieving semantically relevant historical fragments from episodic memory.
        """
        # 1.  Working memory ( Recent messages in current session)
        user_id = self._safe_text(user_id)
        conv_id = self._safe_text(conv_id)
        query = self._safe_text(query)

        recent = await self._get_working_memory(user_id, conv_id)

        # 2.  Episodic memory ( Cross-session semantic retrieval)
        history = await self._search_episodic(
            user_id,
            conv_id,
            query or (recent[-1].content if recent else ""),
        )

        # 3.  User portrait
        profile = await self._get_profile(user_id)

        # 4.  Session Summary ( If compressed)
        summary = await self._redis.get(self._summary_key(user_id, conv_id)) or ""

        return MemoryContext(
            recent_messages=recent,
            relevant_history=history,
            user_profile=profile,
            summary=summary,
        )

    # ──  Compression ( Prevent context explosion)─────────────────────────────────────────────

    async def _compress(self, user_id: str, conv_id: str) -> None:
        """
         Working memory compression:
          1.  Generating digests of old messages using LLM
          2.  Summary saved in Redis ( Overwrite old summary)
          3.  Old messages are stored in episodic memory (ChromaDB) for cross-session retrieval
          4.  Working memory only retains the latest 5 items
        """
        messages = await self._get_working_memory(user_id, conv_id)
        if len(messages) < self.COMPRESS_AT:
            return

        to_compress = messages[:-5]   # Keep the latest 5 items
        keep        = messages[-5:]

        # LLM  Abstract
        text = self._safe_text("\n".join(f"{m.role.value}: {m.content}" for m in to_compress))
        prompt = self._safe_text(f" Summarize the key messages of the following conversation in 2-3 sentences:\n{text}")
        try:
            resp = await self._client.messages.create(
                model=self._model, max_tokens=256, temperature=0.0,
                messages=[{"role": "user", "content": prompt}],
            )
            summary = self._safe_text(extract_text_content(resp.content)).strip()
        except Exception:
            summary = f" Conversation contains {len(to_compress)}  messages ( Summary generation failed)"

        #  Save summary to Redis
        skey = self._summary_key(user_id, conv_id)
        old_summary = await self._redis.get(skey) or ""
        new_summary = await self._merge_summary(old_summary, summary)
        await self._redis.setex(skey, 86400, new_summary)

        # Old messages are stored in episodic memory
        await self._store_episodic(user_id, conv_id, text, summary)

        # Reset working memory to the last 5 items
        key = self._wm_key(user_id, conv_id)
        await self._redis.delete(key)
        for m in reversed(keep):
            await self._redis.lpush(key, json.dumps({
                "role": m.role.value, "content": m.content,
                "ts": m.timestamp.isoformat(), "metadata": m.metadata,
            }))
        await self._redis.expire(key, 86400)
        logger.info(f" Working memory compression completed: {user_id}/{conv_id}, Abstract {len(summary)}  word")

    # ──  Internal Auxiliary ──────────────────────────────────────────────────────────────

    async def _get_working_memory(self, user_id: str, conv_id: str) -> List[Message]:
        key  = self._wm_key(user_id, conv_id)
        raws = await self._redis.lrange(key, 0, self.WORKING_MAX - 1)
        msgs = []
        for raw in reversed(raws):  # Redis lpush Latest first,reversed Restore timing
            d = json.loads(raw)
            msgs.append(Message(
                role=MsgRole(d["role"]),
                content=d["content"],
                timestamp=datetime.fromisoformat(d["ts"]),
                metadata=d.get("metadata", {}),
            ))
        return msgs

    async def _search_episodic(self, user_id: str, conv_id: str, query: str) -> List[str]:
        """ Semantic retrieval of episodic memory.ChromaDB  Built-in embedding, No reliance on external APIs."""
        query_text = self._safe_text(query).strip()
        if not query_text:
            return []
        try:
            results = await self._query_episodic(
                query_text,
                n_results=self.HISTORY_TOP_K,
                where={"user_id": self._safe_text(user_id), "conv_id": self._safe_text(conv_id)},
            )
            docs = self._extract_docs(results)
            if len(docs) < self.HISTORY_TOP_K:
                fallback = await self._query_episodic(
                    query_text,
                    n_results=self.HISTORY_TOP_K,
                    where={"user_id": self._safe_text(user_id)},
                )
                docs.extend(self._extract_docs(fallback))
            return self._dedupe_texts(docs)[: self.HISTORY_TOP_K]
        except Exception as ex:
            logger.warning(f" Episodic memory retrieval failed: {ex}")
            return []

    async def _store_episodic(self, user_id: str, conv_id: str, text: str, summary: str) -> None:
        """ Store compressed dialogue fragments in episodic memory.ChromaDB  Built-in embedding, No reliance on external APIs."""
        try:
            user_id = self._safe_text(user_id)
            conv_id = self._safe_text(conv_id)
            text = self._safe_text(text)
            summary = self._safe_text(summary)
            doc_id = hashlib.md5(f"{user_id}{conv_id}{time.time()}".encode()).hexdigest()
            #  Directly upload documents,ChromaDB  The built-in model automatically generates embedding
            await asyncio.to_thread(
                self._episodic.add,
                ids=[doc_id],
                documents=[summary],
                metadatas=[{"user_id": user_id, "conv_id": conv_id,
                            "ts": datetime.now().isoformat(), "full_text": self._safe_text(text[:500])}],
            )
        except Exception as ex:
            logger.warning(f" Failed to store episodic memory: {ex}")

    async def _get_profile(self, user_id: str) -> Dict[str, Any]:
        """ Get user portrait ( Take the latest one)."""
        try:
            doc_id = self._profile_doc_id(user_id)
            direct = await asyncio.to_thread(self._profile.get, ids=[doc_id])
            if direct.get("documents"):
                return json.loads(direct["documents"][0])

            results = await asyncio.to_thread(self._profile.get, where={"user_id": user_id})
            return self._latest_profile_from_results(results)
        except Exception:
            pass
        return {}

    async def close(self) -> None:
        """ Close asynchronous Redis connection."""
        await self._redis.aclose()

    @staticmethod
    def _wm_key(user_id: str, conv_id: str) -> str:
        return f"wm:{user_id}:{conv_id}"

    @staticmethod
    def _summary_key(user_id: str, conv_id: str) -> str:
        return f"summary:{user_id}:{conv_id}"

    @classmethod
    def _profile_doc_id(cls, user_id: str) -> str:
        return f"{cls.PROFILE_DOC_PREFIX}{user_id}"

    @staticmethod
    def _safe_text(value: Any) -> str:
        """ Convert to a normal UTF-8 string acceptable to ChromaDB."""
        if value is None:
            return ""
        if not isinstance(value, str):
            value = str(value)
        return value.encode("utf-8", errors="ignore").decode("utf-8")

    @classmethod
    def _safe_metadata_value(cls, value: Any) -> Any:
        """ Recursively clean metadata, Prevent Redis/ChromaDB from encountering illegal UTF-8 in subsequent reads and writes."""
        if isinstance(value, str):
            return cls._safe_text(value)
        if isinstance(value, dict):
            return {cls._safe_text(k): cls._safe_metadata_value(v) for k, v in value.items()}
        if isinstance(value, list):
            return [cls._safe_metadata_value(v) for v in value]
        return value

    async def _query_episodic(
        self,
        query_text: str,
        n_results: int,
        where: Dict[str, Any],
    ) -> Dict[str, Any]:
        return await asyncio.to_thread(
            self._episodic.query,
            query_texts=[query_text],
            n_results=n_results,
            where=where,
        )

    @staticmethod
    def _extract_docs(results: Dict[str, Any]) -> List[str]:
        docs = results.get("documents") or []
        if not docs:
            return []
        first = docs[0] if isinstance(docs[0], list) else docs
        return [doc for doc in first if isinstance(doc, str) and doc.strip()]

    @staticmethod
    def _dedupe_texts(values: List[str]) -> List[str]:
        seen = set()
        deduped: List[str] = []
        for value in values:
            text = value.strip()
            if not text or text in seen:
                continue
            seen.add(text)
            deduped.append(text)
        return deduped

    async def _merge_summary(self, old_summary: str, new_summary: str) -> str:
        old_summary = self._safe_text(old_summary).strip()
        new_summary = self._safe_text(new_summary).strip()
        if not old_summary:
            return new_summary[: self.SUMMARY_MAX_CHARS]
        if not new_summary:
            return old_summary[: self.SUMMARY_MAX_CHARS]

        prompt = self._safe_text(
            f"""You are the conversation summarizer. Please combine the following two abstracts into one paragraph, no longer than
Keep the summary within {self.SUMMARY_MAX_CHARS} characters.
 Reserved: User preference,Key entity,To-do items, Constraints, Issue not resolved.
 Only the summary text is output, No number required,Don't explain.

Old summary:
{old_summary}

New abstract:
{new_summary}
"""
        )
        try:
            resp = await self._client.messages.create(
                model=self._model,
                max_tokens=256,
                temperature=0.0,
                messages=[{"role": "user", "content": prompt}],
            )
            merged = self._safe_text(extract_text_content(resp.content)).strip()
            if merged:
                return merged[: self.SUMMARY_MAX_CHARS]
        except Exception as ex:
            logger.warning(f" Merge summary failed, Fallback to truncation splicing: {ex}")

        merged = self._safe_text(f"{old_summary}\n{new_summary}").strip()
        return merged[-self.SUMMARY_MAX_CHARS :]

    @staticmethod
    def _latest_profile_from_results(results: Dict[str, Any]) -> Dict[str, Any]:
        documents = results.get("documents") or []
        metadatas = results.get("metadatas") or []
        if not documents:
            return {}

        candidates: List[tuple[str, Dict[str, Any], str]] = []
        for idx, doc in enumerate(documents):
            if not doc:
                continue
            metadata = metadatas[idx] if idx < len(metadatas) and isinstance(metadatas[idx], dict) else {}
            ts = str(metadata.get("updated_at") or metadata.get("ts") or "")
            candidates.append((ts, metadata, doc))

        if not candidates:
            return {}

        candidates.sort(key=lambda item: item[0], reverse=True)
        latest_doc = candidates[0][2]
        try:
            return json.loads(latest_doc)
        except Exception:
            return {}
