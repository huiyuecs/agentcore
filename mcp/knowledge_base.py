"""
RAG Knowledge Base ——  Real retrieval implementation based on ChromaDB.

 Function:
  1.  Document import: Slice the text and store it in ChromaDB ( Automatically generate Embedding)
  2.  Semantic retrieval: Retrieve the most relevant document fragments from the knowledge base based on query
  3.  Integration with MCP tool framework: Actual handler as knowledge_search tool

ChromaDB  Role here:
  - memory/  is used to store dialogue memories ( Situational memory + user portrait)
  -  This is used to store knowledge base documents (RAG  Search)
  The two are different collections,Do not interfere with each other.
"""
import asyncio
import hashlib
import logging
from typing import Any, Dict, List, Optional

import chromadb

logger = logging.getLogger(__name__)


class KnowledgeBase:
    """
     RAG knowledge base based on ChromaDB.

    ChromaDB  Built-in Embedding model (all-MiniLM-L6-v2),
     Call add
Vector is automatically generated when () ,query()  automatically performs semantic matching.
     No additional calls to the Anthropic Embeddings API are required.
    """

    COLLECTION_NAME = "knowledge_base"

    def __init__(
        self,
        chroma_host: str = "localhost",
        chroma_port: int = 8000,
        chroma_path: str = "./data/chroma",
    ):
        #  Prioritize connections to standalone ChromaDB services ( The server has built-in embedding model, Client does not need to be downloaded)
        self._use_server = False
        try:
            # HttpClient  ChromaDB telemetry is also initialized by default; Explicitly turning off avoids posthog compatibility error logging.
            self._client = chromadb.HttpClient(
                host=chroma_host,
                port=chroma_port,
                settings=chromadb.Settings(anonymized_telemetry=False),
            )
            self._client.heartbeat()
            self._use_server = True
            logger.info(f" Knowledge base ChromaDB is connected: {chroma_host}:{chroma_port}")
        except Exception:
            logger.info(f" The knowledge base ChromaDB service is unavailable, Use local mode: {chroma_path}")
            self._client = chromadb.PersistentClient(
                path=chroma_path,
                settings=chromadb.Settings(anonymized_telemetry=False),
            )

        #  Embedding_function is not passed when using the server. Let the server handle it
        #  It is not transmitted even in local mode. Use ChromaDB default ( will trigger model download)
        self._collection = self._client.get_or_create_collection(
            name=self.COLLECTION_NAME,
            metadata={"description": "AgentCore RAG Knowledge Base"},
        )

        #  If the knowledge base is empty,Import default document
        if self._collection.count() == 0:
            self._load_default_docs()

    # ── Document Management ──────────────────────────────────────────────────────────────

    def add_documents(self, documents: List[Dict[str, str]]) -> int:
        """
         Batch import documents into the knowledge base.

        documents Format: [{"title": "...", "content": "..."}, ...]
         Long documents will be automatically sliced (500 words per piece).
        """
        ids, docs, metas = [], [], []

        for doc in documents:
            title   = doc.get("title", "")
            content = doc.get("content", "")
            chunks  = self._chunk_text(content, chunk_size=500)

            for i, chunk in enumerate(chunks):
                doc_id = hashlib.md5(f"{title}_{i}_{chunk[:50]}".encode()).hexdigest()
                ids.append(doc_id)
                docs.append(chunk)
                metas.append({"title": title, "chunk_index": i, "total_chunks": len(chunks)})

        if ids:
            # ChromaDB  Embedding will be automatically generated
            self._collection.add(ids=ids, documents=docs, metadatas=metas)
            logger.info(f" Knowledge base import {len(ids)}  document fragments")

        return len(ids)

    async def add_documents_async(self, documents: List[Dict[str, str]]) -> int:
        """ Asynchronously import documents;ChromaDB  The client is implemented synchronously, Therefore put it into the thread pool for execution."""
        return await asyncio.to_thread(self.add_documents, documents)

    def search(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """
         Semantic retrieval: Return the most relevant document fragments based on query.

        ChromaDB  Automatically convert query into vector internally, Do cosine similarity matching with stored document vectors.
        """
        results = self._collection.query(
            query_texts=[query],
            n_results=top_k,
        )

        items = []
        if results["documents"] and results["documents"][0]:
            for doc, meta, dist in zip(
                results["documents"][0],
                results["metadatas"][0],
                results["distances"][0],
            ):
                items.append({
                    "title":    meta.get("title", ""),
                    "content":  doc,
                    "score":    round(1.0 - dist, 4),  # ChromaDB  Return distance,Convert to similarity
                    "chunk":    meta.get("chunk_index", 0),
                })

        return items

    async def search_async(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """ Asynchronous retrieval;ChromaDB  The client is implemented synchronously, Therefore put it into the thread pool for execution."""
        return await asyncio.to_thread(self.search, query, top_k)

    @property
    def doc_count(self) -> int:
        return self._collection.count()

    async def doc_count_async(self) -> int:
        """ Asynchronously obtain the number of document fragments."""
        return await asyncio.to_thread(self._collection.count)

    # ── MCP Tool handler ─────────────────────────────────────────────────────

    async def search_handler(self, params: Dict[str, Any], context: Any) -> List[Dict]:
        """
         Registered as handler for MCP tool.

        MCPToolManager.register(Tool(
            name="knowledge_search",
            handler=kb.search_handler,
            ...
        ))
        """
        query = params.get("query", "")
        top_k = params.get("top_k", 5)
        return await self.search_async(query, top_k=top_k)

    # ──  Internal method ──────────────────────────────────────────────────────────────

    def _chunk_text(self, text: str, chunk_size: int = 500) -> List[str]:
        """ Slice long text by chunk_size, Preserve semantic integrity ( Split by period/line feed)."""
        if len(text) <= chunk_size:
            return [text] if text.strip() else []

        chunks = []
        current = ""
        #  Split by sentence
        sentences = text.replace("\n", ".").split(".")
        for sent in sentences:
            sent = sent.strip()
            if not sent:
                continue
            if len(current) + len(sent) + 1 > chunk_size:
                if current:
                    chunks.append(current)
                current = sent
            else:
                current = f"{current}.{sent}" if current else sent

        if current:
            chunks.append(current)

        return chunks

    def _load_default_docs(self) -> None:
        """ Import default knowledge base documents ( Frequently Asked Questions in Customer Service Scenarios)."""
        default_docs = [
            {
                "title": "Refund Policy",
                "content": (
                    " Refund policy description."
                    " Users can apply for a no-reason refund within 7 days of purchase."
                    " After the refund application is submitted, The system will review it within 1-3 business days."
                    "After passing the review, The money will be returned to the original payment account within 5-7 working days."
                    " If the item has been shipped, You need to complete the return process before you can get a refund."
                    " Return shipping costs are borne by the user. Unless it is a product quality problem."
                    " Orders older than 7 days but less than 30 days old, Evidence of product quality issues is required to obtain a refund."
                ),
            },
            {
                "title": "Order inquiry",
                "content": (
                    " Order Inquiry Guide."
                    " Users can check the order status through the order number."
                    " Order status includes:To be paid, Paid, Shipped, In transit, Signed for receipt, Completed."
                    " If the order shows shipped but has not been received for more than 7 days, You can contact customer service to apply for inspection."
                    " Logistics information is usually updated within 24 hours of shipment."
                    " If the order displays abnormally, Please provide the order number to contact customer service for processing."
                ),
            },
            {
                "title": "Account security",
                "content": (
                    " Account security instructions."
                    " It is recommended that users change their passwords regularly. Password must be at least 8 characters long, contains letters and numbers."
                    " If you forget your password, can be reset through the bound mobile phone number or email address."
                    " When it is found that the account is abnormally logged in, The system will automatically lock the account and send a notification."
                    " Users can turn on two-step verification in security settings. Improve account security."
                    "Do not share your password with others, Customer service personnel will not ask for user passwords."
                ),
            },
            {
                "title": " Technical troubleshooting",
                "content": (
                    " Troubleshooting common technical issues."
                    " App crashes: Please try clearing the cache and restarting the application. If the problem persists please update to the latest version."
                    " Login failed with 401 error: indicates authentication failure, Please check whether the username and password are correct. Or try resetting your password."
                    " Page loads slowly: Check network connection, Try switching WiFi or mobile data."
                    " Payment failed: Confirm that the bank card balance is sufficient, Check whether the online payment function is enabled."
                    "500  Server error:This is a server-side problem, Please try again later. If it persists please contact technical support."
                ),
            },
            {
                "title": "Members and Points",
                "content": (
                    "Member points rules."
                    "Earn 1 point for every 1 yuan spent."
                    " Points can be deducted from your next purchase.100  Points = 1 Yuan."
                    " Membership levels are divided into:Ordinary member, Silver Card Member ( Cumulative consumption 1,000 yuan),Gold Card Member ( Cumulative consumption 5,000 yuan)."
                    "Silver card members enjoy a 5% discount,Gold members enjoy 10% off."
                    " Points are valid for 1 year. Automatically cleared when expired."
                    " Earn double points for purchases in the month of your birthday."
                ),
            },
            {
                "title": " Shipping Instructions",
                "content": (
                    " Delivery service description."
                    "Standard delivery:3-5  working days for delivery, Free shipping ( Orders over 99 yuan)."
                    "Expedited shipping: delivery within 1-2 working days; shipping costs 15 yuan."
                    "Same city delivery: Delivery on the same day or the next day, Shipping fee is 10 yuan."
                    " Remote areas may require an additional 2-3 days."
                    " Delivery time is 9 every day:00-18:00, Holidays may be delayed."
                    " If you need to modify the delivery address, Please contact customer service before shipping."
                ),
            },
        ]
        self.add_documents(default_docs)
        logger.info(f"The default knowledge base has been imported: {len(default_docs)}  documents")
