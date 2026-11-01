# This file is part of Prometheus
# https://inl.gov/super-intelligence/prometheus/
#
# Copyright 2026 Battelle Energy Alliance, LLC
# All rights reserved, see NOTICE.txt for full restrictions
# https://github.com/idaholab/prometheus_core/blob/main/NOTICE.txt
#
# Licensed under the MIT License, please see LICENSE for details
# https://github.com/idaholab/prometheus_core/blob/main/LICENSE
#
# SPDX-License-Identifier: MIT

"""
OSTI Research Agent - Performs literature search on OSTI database.

This agent:
1. Takes research questions and searches the OSTI scientific database
2. Assesses paper relevance using LLM-based abstract analysis
3. Downloads relevant papers and extracts answers
4. Synthesizes findings from multiple sources with provenance
5. Builds a self-learning knowledge base in Redis
"""

import asyncio
import json
import os
import sys
import uuid
import logging
import re
import hashlib
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import redis
import requests
from prometheus_api.agent import PrometheusAgent, TaskState
from prometheus_api.llm_client import LLMConfig
from prometheus_api.redis_utils import create_redis_client
from a2a.server.agent_execution.context import RequestContext
from a2a.server.events import EventQueue

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Configuration
REDIS_URL = os.getenv("REDIS_URL")
TIMEOUT_SECONDS = 900  # 15 minutes maximum
PROMPTS_DIR = Path(__file__).with_name("prompts")

# Disable SSL warnings for OSTI (uses self-signed certs sometimes)
requests.packages.urllib3.disable_warnings()


def _load_prompt(name: str) -> str:
    return (PROMPTS_DIR / name).read_text(encoding="utf-8").strip()


SEARCH_QUERY_PROMPT_TEMPLATE = _load_prompt("search_query.txt")
ASSESS_ABSTRACT_PROMPT_TEMPLATE = _load_prompt("assess_abstract.txt")
EXTRACT_ANSWER_PROMPT_TEMPLATE = _load_prompt("extract_answer.txt")
SYNTHESIZE_ANSWER_PROMPT_TEMPLATE = _load_prompt("synthesize_answer.txt")
FOLLOWUP_QUERIES_PROMPT_TEMPLATE = _load_prompt("followup_queries.txt")
SELECT_FACTOIDS_PROMPT_TEMPLATE = _load_prompt("select_factoids.txt")
SYNTHESIZE_MEMORY_PROMPT_TEMPLATE = _load_prompt("synthesize_memory.txt")
EXTRACT_FACTS_PROMPT_TEMPLATE = _load_prompt("extract_facts.txt")


def is_memory_answer_sufficient(answer_text: str) -> bool:
    """Heuristic fallback for deciding if a KB-only answer is sufficient."""
    if not isinstance(answer_text, str):
        return False

    text = answer_text.strip()
    if not text:
        return False

    lowered = text.lower()
    explicit_insufficient_markers = [
        "not enough information",
        "insufficient information",
        "insufficient data",
        "cannot answer",
        "can't answer",
        "unable to determine",
        "do not have enough",
        "don't have enough",
        "no relevant information",
        "not enough context",
    ]

    if any(marker in lowered for marker in explicit_insufficient_markers):
        return False

    # Very short responses are usually not actionable final answers.
    if len(text) < 60:
        return False

    return True


def deduplicate_provenance_simple(provenance: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Simple deduplication for cached/pre-built provenance lists (no mapping needed)."""
    seen_ids = set()
    deduplicated = []
    for source in provenance:
        osti_id = source.get("source", "").replace("OSTI #", "")
        if osti_id and osti_id not in seen_ids:
            seen_ids.add(osti_id)
            deduplicated.append(source)
        elif not osti_id:
            deduplicated.append(source)
    return deduplicated


def deduplicate_provenance_with_mapping(answers: List[Dict[str, Any]]) -> tuple[List[Dict[str, Any]], Dict[int, int]]:
    """
    Deduplicate answers by OSTI ID and build a mapping from original paper numbers
    to deduplicated provenance indices.

    Returns:
        - provenance: List of unique sources with 'original_papers' field showing
          which Paper N references map to this source
        - paper_to_provenance: Dict mapping original paper number (1-indexed) to
          provenance index (1-indexed) for linkification

    Example:
        If answers = [Paper A, Paper B, Paper A, Paper C, Paper A]
        Then provenance will have 3 entries:
          1. Paper A with original_papers=[1, 3, 5]
          2. Paper B with original_papers=[2]
          3. Paper C with original_papers=[4]
        And paper_to_provenance = {1: 1, 2: 2, 3: 1, 4: 3, 5: 1}
    """
    seen_ids: Dict[str, int] = {}  # osti_id -> provenance index (0-based)
    provenance = []
    paper_to_provenance: Dict[int, int] = {}  # original paper num -> provenance num (1-indexed)

    for i, ans in enumerate(answers):
        original_paper_num = i + 1  # 1-indexed
        osti_id = ans.get("osti_id", "")

        if osti_id and osti_id in seen_ids:
            # Duplicate - add to existing provenance entry's original_papers list
            prov_idx = seen_ids[osti_id]
            provenance[prov_idx]["original_papers"].append(original_paper_num)
            paper_to_provenance[original_paper_num] = prov_idx + 1  # 1-indexed
        else:
            # New unique paper
            prov_idx = len(provenance)
            if osti_id:
                seen_ids[osti_id] = prov_idx

            provenance.append(
                {
                    "source": f"OSTI #{osti_id}" if osti_id else "Unknown",
                    "title": ans["title"],
                    "url": ans["url"],
                    "excerpt": ans.get("excerpt", "")[:500],
                    "confidence": ans.get("confidence", 0.5),
                    "original_papers": [original_paper_num],
                }
            )
            paper_to_provenance[original_paper_num] = prov_idx + 1  # 1-indexed

    return provenance, paper_to_provenance


def linkify_paper_references(
    answer_text: str, provenance: List[Dict[str, Any]], paper_to_provenance: Dict[int, int] = None
) -> str:
    """
    Convert 'Paper X' citations to clickable [Paper N](url) links.

    If paper_to_provenance mapping is provided, maps original paper numbers
    to their deduplicated provenance indices. Otherwise falls back to direct
    1:1 mapping.

    Args:
        answer_text: The synthesized answer text with "Paper N" references
        provenance: List of deduplicated sources
        paper_to_provenance: Optional mapping from original paper number to
                            provenance index (both 1-indexed)
    """
    if not provenance:
        return answer_text

    # Build URL map: provenance_index -> url (1-indexed)
    url_map = {i: source.get("url", "") for i, source in enumerate(provenance, 1)}

    def replace_citation(match):
        original_paper_num = int(match.group(1))

        if paper_to_provenance:
            # Map original paper number to deduplicated provenance index
            prov_num = paper_to_provenance.get(original_paper_num)
            if prov_num and prov_num in url_map:
                url = url_map[prov_num]
                if url:
                    return f"[Paper {prov_num}]({url})"
        else:
            # Fallback: direct 1:1 mapping
            url = url_map.get(original_paper_num, "")
            if url:
                return f"[Paper {original_paper_num}]({url})"

        return match.group(0)  # Keep original if no mapping found

    # Match patterns like "Paper 1", "Paper 2", etc.
    result = re.sub(r"Paper\s*(\d+)", replace_citation, answer_text)
    return result


class OSTIResearchAgent(PrometheusAgent):
    """
    OSTI Research Agent - Searches scientific literature in OSTI database.

    Features:
    - Memory-first search (checks Redis before querying OSTI)
    - Multi-paper synthesis with conflict detection
    - Self-learning knowledge base
    - Progress updates throughout workflow
    - Provenance tracking for all findings
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._redis_client = None
        self._redis_binary_client = None

    @property
    def redis_client(self) -> redis.Redis:
        """Lazy initialization of Redis client for text data."""
        if self._redis_client is None:
            self._redis_client = create_redis_client(REDIS_URL, ping=False)
        return self._redis_client

    @property
    def redis_binary_client(self) -> redis.Redis:
        """Lazy initialization of Redis client for binary data (PDFs)."""
        if self._redis_binary_client is None:
            self._redis_binary_client = create_redis_client(REDIS_URL, decode_responses=False, ping=False)
        return self._redis_binary_client

    def extract_json_from_text(self, text: str) -> Optional[Any]:
        """Extract JSON from text that may contain markdown code blocks."""
        # Try to find JSON in code blocks first
        json_match = re.search(r"```json\s*(\[.*?\]|\{.*?\})\s*```", text, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except json.JSONDecodeError:
                pass

        # Try to find raw JSON object or array
        json_match = re.search(r"(\[.*\]|\{.*\})", text, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(0))
            except json.JSONDecodeError:
                pass

        return None

    async def check_memory(self, question: str, llm: Any) -> Optional[Dict[str, Any]]:
        """Check if we've already answered this question or have relevant facts."""
        # Hash question for lookup
        question_hash = hashlib.md5(question.lower().encode()).hexdigest()

        # Check for exact cached answer
        cached = await asyncio.to_thread(
            self.redis_client.get,
            f"osti:question:{question_hash}:answer",
        )
        if cached:
            logger.info(f"Found cached answer for question: {question}")
            cached_payload = json.loads(cached)
            cached_payload["sufficient"] = True
            cached_payload["memory_source"] = "cached_answer"
            return cached_payload

        # Check for relevant factoids
        factoids = await self.search_relevant_factoids(question, llm)

        if factoids and len(factoids) >= 2:  # Minimum 2 factoids to answer
            logger.info(f"Found {len(factoids)} relevant factoids in memory")
            synthesized = await self.synthesize_from_memory(question, factoids, llm)
            if not synthesized:
                return None

            sufficient = bool(synthesized.get("sufficient_for_answer", False))
            if not sufficient:
                logger.info(
                    "Knowledge-base synthesis found insufficient information; will fall back to live OSTI search."
                )

            synthesized["sufficient"] = sufficient
            synthesized["memory_source"] = "factoid_synthesis"
            return synthesized

        return None

    async def search_relevant_factoids(
        self,
        question: str,
        llm: Any,
    ) -> List[Dict[str, Any]]:
        """Find factoids relevant to the question."""
        # Get all OSTI factoids
        all_factoid_keys = await asyncio.to_thread(
            self.redis_client.keys,
            "osti:factoid:*",
        )

        if not all_factoid_keys:
            return []

        factoids = []
        for key in all_factoid_keys[:100]:  # Limit for performance
            data = await asyncio.to_thread(self.redis_client.get, key)
            if data:
                factoids.append(json.loads(data))

        if not factoids:
            return []

        # Use the configured model to select relevant ones
        selection_prompt = SELECT_FACTOIDS_PROMPT_TEMPLATE.format(
            question=question,
            factoids_json=json.dumps(
                [{"id": f["factoid_id"], "content": f["content"]} for f in factoids],
                indent=2,
            ),
        )

        try:
            response = await llm.medium(selection_prompt, max_tokens=1024)

            selected_ids = self.extract_json_from_text(response.text) or []
            return [f for f in factoids if f["factoid_id"] in selected_ids]
        except Exception as e:
            logger.error(f"Error selecting relevant factoids: {e}")
            return []

    async def synthesize_from_memory(
        self,
        question: str,
        factoids: List[Dict],
        llm: Any,
    ) -> Dict[str, Any]:
        """Synthesize answer from stored factoids."""
        factoids_text = "\n\n".join(
            [
                f"Fact {i}: {f['content']}\n"
                f"Source: {f['source_paper'].get('title', 'Unknown')} (OSTI #{f['source_paper'].get('osti_id', 'N/A')})\n"
                f"Confidence: {f.get('confidence', 0.5)}"
                for i, f in enumerate(factoids, 1)
            ]
        )

        prompt = SYNTHESIZE_MEMORY_PROMPT_TEMPLATE.format(
            question=question,
            factoids_text=factoids_text,
        )

        try:
            response = await llm.medium(prompt, max_tokens=2048)

            raw_text = response.text
            parsed = self.extract_json_from_text(raw_text)
            if isinstance(parsed, dict):
                answer_text = str(parsed.get("answer", "")).strip() or raw_text.strip()
                confidence_raw = parsed.get("confidence", 0.0)
                try:
                    confidence = float(confidence_raw)
                except (TypeError, ValueError):
                    confidence = 0.0
                confidence = max(0.0, min(1.0, confidence))
                sufficient_raw = parsed.get("sufficient_for_answer")
                if isinstance(sufficient_raw, bool):
                    sufficient = sufficient_raw
                else:
                    sufficient = is_memory_answer_sufficient(answer_text)
                missing_information = str(parsed.get("missing_information", "") or "").strip()
            else:
                answer_text = raw_text.strip()
                confidence = 0.0
                sufficient = is_memory_answer_sufficient(answer_text)
                missing_information = ""

            return {
                "answer": answer_text,
                "sources": [
                    {
                        "source": f"OSTI #{f['source_paper'].get('osti_id', 'N/A')}",
                        "osti_id": f["source_paper"].get("osti_id", ""),
                        "title": f["source_paper"].get("title", "Unknown"),
                        "url": f["source_paper"].get("url", ""),
                        "excerpt": f["content"][:500],
                        "confidence": f.get("confidence", 0.5),
                    }
                    for f in factoids
                ],
                "sufficient_for_answer": sufficient,
                "confidence": confidence,
                "missing_information": missing_information,
            }
        except Exception as e:
            logger.error(f"Error synthesizing from memory: {e}")
            return None

    def cache_answer(self, question: str, answer: str, sources: List[Dict]) -> None:
        """Cache question-answer pair for instant retrieval."""
        question_hash = hashlib.md5(question.lower().encode()).hexdigest()

        cache_data = {"answer": answer, "sources": sources, "cached_at": datetime.now(timezone.utc).isoformat()}

        # Store with 30-day TTL
        self.redis_client.set(
            f"osti:question:{question_hash}:answer",
            json.dumps(cache_data),
            ex=30 * 24 * 3600,  # 30 days
        )

    def store_factoid(self, content: str, source_paper: Dict, topics: List[str], question: str) -> str:
        """Store a research finding in memory."""
        factoid_id = str(uuid.uuid4())

        factoid = {
            "factoid_id": factoid_id,
            "content": content,
            "source_paper": source_paper,
            "topics": topics,
            "confidence": 0.85,
            "extracted_at": datetime.now(timezone.utc).isoformat(),
            "question_answered": question,
        }

        # Store factoid
        self.redis_client.set(f"osti:factoid:{factoid_id}", json.dumps(factoid))

        # Index by paper
        if source_paper.get("osti_id"):
            self.redis_client.sadd(f"osti:paper:{source_paper['osti_id']}:facts", factoid_id)

        # Index by topics
        for topic in topics:
            self.redis_client.sadd(f"osti:topic:{topic}:factoids", factoid_id)

        return factoid_id

    async def formulate_search_queries(self, question: str, llm: Any) -> str:
        """Use the configured LLM to generate an OSTI search query."""
        prompt = SEARCH_QUERY_PROMPT_TEMPLATE.format(question=question)

        try:
            response = await llm.medium(prompt, max_tokens=256)

            return response.text.strip().strip("\"'")
        except Exception as e:
            logger.error(f"Error formulating search query: {e}")
            # Fallback: extract key terms from question
            return " ".join(question.split()[:7])

    def search_osti(self, search_query: str, max_results: int = 15) -> List[Dict[str, Any]]:
        """Search OSTI API and retrieve abstracts.

        OSTI ranks q= matches loosely (recent, off-topic records come first),
        while title= matches stay on topic. So title= is tried first, then
        again without words that contain digits ("800K" makes title= match
        nothing), and q= only tops up what the title searches didn't fill.
        """
        base_url = "https://www.osti.gov/api/v1/records"
        # Without it OSTI sometimes answers in XML
        headers = {"Accept": "application/json"}

        plain_query = " ".join(w for w in search_query.split() if not any(c.isdigit() for c in w))
        attempts = [("title", search_query)]
        if plain_query and plain_query != search_query:
            attempts.append(("title", plain_query))
        attempts.append(("q", search_query))

        results = []
        seen_ids = set()

        for field, text in attempts:
            encoded_query = urllib.parse.quote_plus(text)
            page = 0  # OSTI uses 0-based pagination

            while len(results) < max_results:
                try:
                    full_url = f"{base_url}?{field}={encoded_query}&page={page}"
                    logger.info(f"[OSTI API] Requesting: {full_url}")

                    response = requests.get(full_url, headers=headers, timeout=60, verify=False)
                    logger.info(f"[OSTI API] Response status: {response.status_code}")

                    if response.status_code != 200:
                        logger.warning(f"[OSTI API] Non-200 status: {response.status_code}")
                        logger.warning(f"[OSTI API] Response body: {response.text[:500]}")
                        break

                    # Log raw response for debugging
                    logger.info(f"[OSTI API] Response length: {len(response.text)} chars")

                    try:
                        data = json.loads(response.text.replace("\\'", "'"))
                    except json.JSONDecodeError as e:
                        logger.error(f"[OSTI API] JSON decode error: {e}")
                        logger.error(f"[OSTI API] Raw response: {response.text[:1000]}")
                        break

                    if not data:
                        logger.info(f"[OSTI API] No more {field}= results on page {page}")
                        break

                    logger.info(f"[OSTI API] {field}= page {page}: Got {len(data)} records")

                    for result in data:
                        if "description" in result and "osti_id" in result and result["osti_id"] not in seen_ids:
                            seen_ids.add(result["osti_id"])
                            results.append(
                                {
                                    "osti_id": result["osti_id"],
                                    "title": result.get("title", ""),
                                    "description": result.get("description", ""),
                                    "journal_name": result.get("journal_name", ""),
                                    "url": f"https://www.osti.gov/biblio/{result['osti_id']}",
                                }
                            )
                            logger.info(f"[OSTI API] Added: {result.get('title', 'No title')[:60]}...")

                            if len(results) >= max_results:
                                break

                    page += 1

                    # Safety limit to prevent infinite loops
                    if page > 5:
                        logger.info("[OSTI API] Reached page limit, stopping")
                        break

                except Exception as e:
                    logger.error(f"[OSTI API] Error searching OSTI: {e}", exc_info=True)
                    break

            if len(results) >= max_results:
                break

        logger.info(f"[OSTI API] Total results found: {len(results)}")

        return results

    async def assess_abstract(
        self,
        question: str,
        title: str,
        abstract: str,
        llm: Any,
    ) -> Dict[str, Any]:
        """Use the configured LLM to assess if a paper is relevant."""
        prompt = ASSESS_ABSTRACT_PROMPT_TEMPLATE.format(
            question=question,
            title=title,
            abstract=abstract,
        )

        try:
            response = await llm.medium(prompt, max_tokens=256)

            result = self.extract_json_from_text(response.text)
            return result or {"relevant": False, "confidence": 0.0, "reason": "Parse failed"}
        except Exception as e:
            logger.error(f"Error assessing abstract: {e}")
            return {"relevant": False, "confidence": 0.0, "reason": f"Error: {str(e)}"}

    def download_paper(self, osti_id: str) -> Optional[str]:
        """Download paper from OSTI with Redis caching to avoid repeat downloads."""
        filepath = f"/tmp/osti_{osti_id}.pdf"

        # Check if file exists locally first
        if os.path.exists(filepath):
            logger.info(f"Paper {osti_id} found in local cache")
            return filepath

        # Check Redis cache (use binary client for PDF data)
        try:
            pdf_bytes = self.redis_binary_client.get(f"osti:paper:pdf_bytes:{osti_id}")
            if pdf_bytes:
                logger.info(f"Paper {osti_id} found in Redis cache ({len(pdf_bytes)} bytes)")
                with open(filepath, "wb") as f:
                    f.write(pdf_bytes)
                return filepath
        except Exception as e:
            logger.warning(f"Redis cache check failed: {e}")

        # Download from OSTI
        url = f"https://www.osti.gov/servlets/purl/{osti_id}"
        logger.info(f"Downloading paper {osti_id} from OSTI...")

        try:
            session = requests.Session()
            response = session.get(url, verify=False, timeout=120)

            if response.status_code == 200 and "application/pdf" in response.headers.get("Content-Type", ""):
                # Save to local file
                with open(filepath, "wb") as f:
                    f.write(response.content)

                # Cache in Redis (30 day TTL) - use binary client for PDF data
                try:
                    self.redis_binary_client.set(
                        f"osti:paper:pdf_bytes:{osti_id}",
                        response.content,
                        ex=30 * 24 * 3600,  # 30 days
                    )
                    logger.info(f"Paper {osti_id} cached in Redis ({len(response.content)} bytes)")
                except Exception as e:
                    logger.warning(f"Failed to cache paper in Redis: {e}")

                return filepath

            logger.warning(f"Paper {osti_id} not available (status={response.status_code})")
            return None
        except Exception as e:
            logger.error(f"Error downloading paper {osti_id}: {e}")
            return None

    def _convert_pdf_with_pymupdf(self, pdf_path: str) -> str:
        """Fast PDF text extraction using PyMuPDF (fitz)."""
        try:
            import fitz  # PyMuPDF

            logger.info(f"[pymupdf] Opening PDF: {pdf_path}")
            logger.info(f"[pymupdf] PyMuPDF version: {fitz.version}")

            # Use context manager for proper resource handling
            with fitz.open(pdf_path) as doc:
                page_count = doc.page_count
                logger.info(f"[pymupdf] PDF opened, {page_count} pages")

                text_parts = []
                total_chars = 0
                for page_num in range(page_count):
                    try:
                        page = doc.load_page(page_num)
                        page_text = page.get_text()
                        char_count = len(page_text) if page_text else 0
                        total_chars += char_count
                        text_parts.append(page_text if page_text else "")

                        if page_num % 10 == 0:
                            logger.info(
                                f"[pymupdf] Page {page_num + 1}/{page_count}: {char_count} chars (total: {total_chars})"
                            )
                    except Exception as page_error:
                        logger.error(f"[pymupdf] Error on page {page_num + 1}: {page_error}")
                        text_parts.append("")

                full_text = "\n\n".join(text_parts)
                logger.info(f"[pymupdf] Extraction complete: {len(full_text)} chars from {page_count} pages")
                return full_text

        except Exception as e:
            logger.error(f"[pymupdf] Error: {e}", exc_info=True)
            return ""

    def _convert_pdf_with_marker_subprocess(self, pdf_path: str, timeout: int = 180) -> str:
        """Run marker conversion in a subprocess with hard timeout."""
        import subprocess

        # Create a small Python script to run marker
        script = f'''
import sys
import os
os.environ["CUDA_VISIBLE_DEVICES"] = ""
os.environ["TORCH_NUM_THREADS"] = "1"
os.environ["OMP_NUM_THREADS"] = "1"

try:
    from marker.converters.pdf import PdfConverter
    from marker.models import create_model_dict
    from marker.output import text_from_rendered

    converter = PdfConverter(artifact_dict=create_model_dict())
    rendered = converter("{pdf_path}")
    text, _, _ = text_from_rendered(rendered)
    print(text or "")
except Exception as e:
    print(f"ERROR: {{e}}", file=sys.stderr)
    sys.exit(1)
'''

        try:
            logger.info(f"[marker-subprocess] Starting marker in subprocess (timeout: {timeout}s)...")

            result = subprocess.run(
                [sys.executable, "-c", script],
                capture_output=True,
                text=True,
                timeout=timeout,
                env={**os.environ, "CUDA_VISIBLE_DEVICES": "", "TORCH_NUM_THREADS": "1"},
            )

            if result.returncode == 0:
                text = result.stdout
                logger.info(f"[marker-subprocess] Success: {len(text)} chars")
                return text
            else:
                logger.error(f"[marker-subprocess] Failed: {result.stderr}")
                return ""

        except subprocess.TimeoutExpired:
            logger.error(f"[marker-subprocess] Timed out after {timeout}s")
            return ""
        except Exception as e:
            logger.error(f"[marker-subprocess] Error: {e}")
            return ""

    def _convert_pdf_with_marker(self, pdf_path: str) -> str:
        """PDF conversion using marker library (ML-based, better for complex layouts)."""
        import traceback

        try:
            # Force CPU mode and single-threaded to avoid hanging
            os.environ["CUDA_VISIBLE_DEVICES"] = ""
            os.environ["TORCH_NUM_THREADS"] = "1"
            os.environ["OMP_NUM_THREADS"] = "1"
            os.environ["MKL_NUM_THREADS"] = "1"

            logger.info("[marker] Importing marker modules (CPU mode)...")
            from marker.converters.pdf import PdfConverter
            from marker.models import create_model_dict
            from marker.output import text_from_rendered

            logger.info("[marker] Imports complete")

            logger.info("[marker] Creating model dict...")
            model_dict = create_model_dict()
            logger.info("[marker] Model dict created")

            logger.info("[marker] Creating PdfConverter...")
            converter = PdfConverter(artifact_dict=model_dict)
            logger.info("[marker] PdfConverter created")

            logger.info(f"[marker] Calling converter({pdf_path})...")
            logger.info("[marker] This may take several minutes for large PDFs...")

            # Call converter - this is where it hangs
            rendered = converter(pdf_path)

            logger.info("[marker] Conversion returned, extracting text...")
            text, _, images = text_from_rendered(rendered)
            logger.info(f"[marker] Text extracted: {len(text) if text else 0} chars")
            return text or ""
        except Exception as e:
            logger.error(f"[marker] Error converting PDF: {e}")
            logger.error(f"[marker] Traceback: {traceback.format_exc()}")
            return ""

    def _convert_pdf_sync(self, pdf_path: str) -> str:
        """Synchronous PDF conversion - tries PyMuPDF first, falls back to marker."""
        # Check if file exists and log details
        logger.info(f"[pdf] PDF path: {pdf_path}")
        if os.path.exists(pdf_path):
            file_size = os.path.getsize(pdf_path)
            logger.info(f"[pdf] PDF exists, size: {file_size} bytes ({file_size / 1024 / 1024:.2f} MB)")
        else:
            logger.error(f"[pdf] PDF file does not exist: {pdf_path}")
            return ""

        # Try PyMuPDF first - it's fast and reliable
        logger.info("[pdf] Trying PyMuPDF extraction...")
        text = self._convert_pdf_with_pymupdf(pdf_path)

        if text and len(text.strip()) > 100:
            logger.info("[pdf] PyMuPDF extraction successful")
            return text

        # PyMuPDF got no/little text - try marker as fallback
        logger.warning(f"[pdf] PyMuPDF got insufficient text ({len(text) if text else 0} chars)")
        logger.info("[pdf] Trying marker library as fallback...")

        marker_text = self._convert_pdf_with_marker_subprocess(pdf_path, timeout=180)

        if marker_text and len(marker_text.strip()) > 100:
            logger.info(f"[pdf] Marker extraction successful: {len(marker_text)} chars")
            return marker_text

        logger.warning("[pdf] Both PyMuPDF and marker failed to extract text")
        return text or ""

    async def convert_pdf_to_text_async(self, pdf_path: str, timeout: int = 300) -> str:
        """Convert PDF to plain text using marker library with Redis caching.

        Runs the CPU-intensive conversion in a thread pool with timeout.
        """
        # Extract OSTI ID from path for caching
        osti_id = os.path.basename(pdf_path).replace("osti_", "").replace(".pdf", "")
        cache_key = f"osti:paper:text:{osti_id}"

        # Check Redis cache for converted text
        try:
            cached_text = self.redis_client.get(cache_key)
            if cached_text:
                logger.info(f"Paper {osti_id} text found in cache")
                return cached_text
        except Exception as e:
            logger.warning(f"Redis text cache check failed: {e}")

        # Convert PDF in thread pool with timeout
        logger.info(f"Converting PDF {osti_id} to text (timeout: {timeout}s)...")
        try:
            loop = asyncio.get_running_loop()
            with ThreadPoolExecutor(max_workers=1) as executor:
                text = await asyncio.wait_for(
                    loop.run_in_executor(executor, self._convert_pdf_sync, pdf_path), timeout=timeout
                )

            # Cache the converted text (30 day TTL)
            if text:
                try:
                    self.redis_client.set(cache_key, text, ex=30 * 24 * 3600)
                    logger.info(f"Paper {osti_id} text cached ({len(text)} chars)")
                except Exception as e:
                    logger.warning(f"Failed to cache text: {e}")

            return text
        except asyncio.TimeoutError:
            logger.error(f"PDF conversion timed out after {timeout}s for {osti_id}")
            return ""
        except Exception as e:
            logger.error(f"Error converting PDF: {e}", exc_info=True)
            return ""

    def convert_pdf_to_text(self, pdf_path: str) -> str:
        """Synchronous wrapper for backward compatibility."""
        return asyncio.get_event_loop().run_until_complete(self.convert_pdf_to_text_async(pdf_path))

    async def extract_answer_from_paper(
        self,
        question: str,
        paper_text: str,
        title: str,
        llm: Any,
    ) -> Dict[str, Any]:
        """Use the configured LLM to extract an answer from paper text."""
        # Limit paper text to avoid token limits
        paper_text = paper_text[:50000]

        prompt = EXTRACT_ANSWER_PROMPT_TEMPLATE.format(
            question=question,
            title=title,
            paper_text=paper_text,
        )

        try:
            response = await llm.medium(prompt, max_tokens=2048)

            result = self.extract_json_from_text(response.text)
            return result or {"answered": False, "confidence": 0.0}
        except Exception as e:
            logger.error(f"Error extracting answer: {e}")
            return {"answered": False, "confidence": 0.0, "error": str(e)}

    async def synthesize_final_answer(
        self,
        question: str,
        answers: List[Dict],
        llm: Any,
    ) -> str:
        """Synthesize a comprehensive answer from multiple papers."""
        answers_text = "\n\n".join(
            [
                f"Paper {i}: {ans['title']}\n"
                f"Answer: {ans['answer']}\n"
                f"Evidence: {ans.get('evidence', '')}\n"
                f"Confidence: {ans.get('confidence', 0.5)}"
                for i, ans in enumerate(answers, 1)
            ]
        )

        prompt = SYNTHESIZE_ANSWER_PROMPT_TEMPLATE.format(
            question=question,
            answers_count=len(answers),
            answers_text=answers_text,
        )

        try:
            response = await llm.medium(prompt, max_tokens=2048)

            return response.text
        except Exception as e:
            logger.error(f"Error synthesizing answer: {e}")
            # Fallback: concatenate answers
            return "\n\n".join([f"From {ans['title']}: {ans['answer']}" for ans in answers])

    async def suggest_followup_queries(
        self,
        question: str,
        answer: str,
        llm: Any,
        provenance: Optional[List[Dict[str, Any]]] = None,
        limit: int = 3,
    ) -> List[Dict[str, str]]:
        """Generate 1-3 actionable follow-up literature queries for the UI."""
        prompt = FOLLOWUP_QUERIES_PROMPT_TEMPLATE.format(
            question=question,
            answer_summary=answer[:2000],
            source_titles_json=json.dumps(
                [p.get("title", "") for p in (provenance or [])][:10],
                indent=2,
            ),
            limit=limit,
        )

        suggestions: List[Dict[str, str]] = []
        seen = set()

        try:
            response = await llm.medium(prompt, max_tokens=512)
            parsed = self.extract_json_from_text(response.text)
            if isinstance(parsed, list):
                for item in parsed:
                    if isinstance(item, dict):
                        candidate = str(item.get("suggested_query") or item.get("query") or "").strip()
                    else:
                        candidate = str(item or "").strip()
                    if not candidate:
                        continue
                    key = candidate.lower()
                    if key in seen:
                        continue
                    seen.add(key)
                    suggestions.append({"suggested_query": candidate})
                    if len(suggestions) >= limit:
                        break
        except Exception as exc:
            logger.warning(f"Failed to generate follow-up suggestions via model: {exc}")

        return suggestions

    def _store_status_in_redis(self, conversation_id: str, status_message: str, final: bool = False) -> None:
        """Store status update in Redis for polling by frontend."""
        if not conversation_id:
            return

        try:
            status_data = {
                "message": status_message,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "final": final,
            }
            # Store latest status with 10-minute TTL
            self.redis_client.set(
                f"agent:status:{conversation_id}",
                json.dumps(status_data),
                ex=600,
            )
            # Append to bounded status history so frontend can render full progress logs.
            history_key = f"agent:status_history:{conversation_id}"
            self.redis_client.rpush(history_key, json.dumps(status_data))
            self.redis_client.ltrim(history_key, -200, -1)
            self.redis_client.expire(history_key, 600)
            logger.debug(f"[STATUS] Stored in Redis: agent:status:{conversation_id}")
        except Exception as e:
            logger.warning(f"Failed to store status in Redis: {e}")

    async def _send_status(
        self,
        context: RequestContext,
        event_queue: EventQueue,
        status_message: str,
        final: bool = False,
        conversation_id: str = None,
    ) -> None:
        """Helper to send status updates and log progress."""
        # Log the status message for visibility
        logger.info(f"[STATUS] {status_message}")

        # Store in Redis for frontend polling (use explicit conversation_id if provided)
        status_id = conversation_id or context.context_id
        self._store_status_in_redis(status_id, status_message, final)

        await self.send_status_update(
            context=context,
            event_queue=event_queue,
            state=(TaskState.TASK_STATE_COMPLETED if final else TaskState.TASK_STATE_WORKING),
            final=final,
            message=status_message,
        )

    async def extract_and_store_facts(
        self,
        question: str,
        answers: List[Dict],
        llm: Any,
    ) -> int:
        """Extract discrete facts from answers and store in memory."""
        answers_text = "\n\n".join(
            [
                f"Paper: {ans['title']} (OSTI #{ans['osti_id']})\n"
                f"Answer: {ans['answer']}\n"
                f"Evidence: {ans.get('evidence', '')}"
                for ans in answers
            ]
        )

        prompt = EXTRACT_FACTS_PROMPT_TEMPLATE.format(
            question=question,
            answers_text=answers_text,
        )

        try:
            response = await llm.medium(prompt, max_tokens=2048)

            facts = self.extract_json_from_text(response.text)

            if not isinstance(facts, list):
                return 0

            stored_count = 0
            for fact_data in facts:
                # Find source paper details
                source_paper = next(
                    (ans for ans in answers if ans["osti_id"] == fact_data.get("source_osti_id")),
                    answers[0] if answers else {},
                )

                await asyncio.to_thread(
                    self.store_factoid,
                    content=fact_data["content"],
                    source_paper=source_paper,
                    topics=fact_data.get("topics", []),
                    question=question,
                )
                stored_count += 1

            return stored_count
        except Exception as e:
            logger.error(f"Error extracting facts: {e}")
            return 0

    async def perform_literature_search(
        self,
        question: str,
        context: RequestContext,
        event_queue: EventQueue,
        llm: Any,
        conversation_id: str = None,
    ) -> Dict[str, Any]:
        """Execute the full literature search workflow with timeout protection."""
        start_time = time.time()

        # Helper to send status with conversation_id
        async def send_status(message: str, final: bool = False):
            await self._send_status(context, event_queue, message, final, conversation_id)

        def check_timeout() -> bool:
            """Check if we're approaching timeout."""
            elapsed = time.time() - start_time
            return elapsed > (TIMEOUT_SECONDS - 60)  # Stop 1 min before timeout

        # Initialize state with progress log for UI feedback
        progress_log = []

        def log_progress(msg: str):
            """Add timestamped message to progress log."""
            elapsed = time.time() - start_time
            progress_log.append(f"[{elapsed:.1f}s] {msg}")
            logger.info(f"[STATUS] {msg}")

        state = {
            "question": question,
            "search_results": [],
            "answers_found": [],
            "status": "generating_query",
            "timeout_occurred": False,
        }

        # Step 1: Generate search query
        log_progress("Formulating OSTI search query...")
        await send_status("Formulating OSTI search query...")

        search_query = await self.formulate_search_queries(question, llm)
        state["search_query"] = search_query
        log_progress(f"Search query: '{search_query}'")
        await send_status(f"OSTI search query: {search_query}")

        # Step 2: Search OSTI
        log_progress("Searching OSTI database...")
        await send_status(f"Searching OSTI database for: '{search_query}'...")

        search_results = await asyncio.to_thread(self.search_osti, search_query, max_results=15)
        state["search_results"] = search_results
        state["status"] = "assessing"

        log_progress(f"Found {len(search_results)} papers in OSTI database")
        await send_status(f"Found {len(search_results)} results, assessing relevance...")
        if search_results:
            titles_block = "\n".join(
                f"{idx}. {item.get('title', 'Untitled')} (OSTI #{item.get('osti_id', 'N/A')})"
                for idx, item in enumerate(search_results, 1)
            )
            await send_status(f"OSTI paper titles:\n{titles_block}")

        # Step 3: Assess and process each result
        relevant_count = 0
        papers_processed = 0

        for i, result in enumerate(search_results, 1):
            # Check timeout before processing each paper
            if check_timeout():
                log_progress("Approaching timeout, returning partial results...")
                await send_status("Approaching timeout, returning partial results...")
                state["timeout_occurred"] = True
                break

            await send_status(f"Assessing abstract {i}/{len(search_results)}...")

            assessment = await self.assess_abstract(
                question,
                result["title"],
                result["description"],
                llm,
            )

            result["assessment"] = assessment
            is_relevant = bool(assessment.get("relevant", False))
            confidence_raw = assessment.get("confidence", 0.0)
            try:
                confidence = float(confidence_raw or 0.0)
            except (TypeError, ValueError):
                confidence = 0.0
            reason = assessment.get("reason", "No reason provided")
            await send_status(
                f"Abstract assessment {i}/{len(search_results)}\n"
                f"Title: {result['title']}\n"
                f"Relevant: {'yes' if is_relevant else 'no'} (confidence {confidence:.0%})\n"
                f"Reason: {reason}"
            )

            if not is_relevant:
                continue

            relevant_count += 1
            short_title = result["title"][:50] + "..." if len(result["title"]) > 50 else result["title"]
            log_progress(f"Paper {relevant_count} relevant: {short_title}")
            await send_status(
                f"Relevant paper selected for download:\n"
                f"Title: {result['title']}\n"
                f"OSTI ID: {result['osti_id']}\n"
                f"Abstract:\n{result.get('description', '')}"
            )

            # Download paper
            await send_status(f"Downloading paper {relevant_count}: {short_title}")

            pdf_path = await asyncio.to_thread(self.download_paper, result["osti_id"])

            if not pdf_path:
                result["download_failed"] = True
                log_progress("  -> Download failed (PDF not available)")
                await send_status(f"Download failed for OSTI #{result['osti_id']} ({result['title']}).")
                continue

            log_progress("  -> Downloaded successfully")
            await send_status(f"Downloaded OSTI #{result['osti_id']} ({result['title']}).")

            # Convert to text (async with timeout)
            await send_status(f"Converting paper {relevant_count} to text (this may take a few minutes)...")

            paper_text = await self.convert_pdf_to_text_async(pdf_path, timeout=300)

            if not paper_text:
                result["conversion_failed"] = True
                log_progress("  -> Conversion failed or timed out")
                await send_status(f"Conversion failed or timed out for OSTI #{result['osti_id']}.")
                continue

            log_progress(f"  -> Converted ({len(paper_text)} chars)")
            await send_status(f"Converted OSTI #{result['osti_id']} to text ({len(paper_text)} chars).")

            # Extract answer
            await send_status(f"Extracting answer from paper {relevant_count}...")

            answer_data = await self.extract_answer_from_paper(
                question,
                paper_text,
                result["title"],
                llm,
            )

            if answer_data.get("answered", False):
                result["answer_data"] = answer_data
                state["answers_found"].append(
                    {
                        "osti_id": result["osti_id"],
                        "title": result["title"],
                        "url": result["url"],
                        "answer": answer_data["answer"],
                        "evidence": answer_data.get("evidence", ""),
                        "excerpt": answer_data.get("excerpt", ""),
                        "confidence": answer_data.get("confidence", 0.5),
                    }
                )
                papers_processed += 1
                log_progress(f"  -> Extracted answer (confidence: {answer_data.get('confidence', 0.5):.0%})")
                await send_status(
                    f"Useful information found in OSTI #{result['osti_id']} "
                    f"(confidence {answer_data.get('confidence', 0.5):.0%})."
                )
            else:
                log_progress("  -> No relevant answer found in paper")
                await send_status(f"No useful information found in OSTI #{result['osti_id']}.")

            # Limit to 5 papers max for performance
            if papers_processed >= 5:
                log_progress("Reached paper limit (5), stopping search")
                break

        # Step 4: Synthesize final answer
        if not state["answers_found"]:
            # Build informative message about what was tried
            if len(search_results) == 0:
                no_results_msg = (
                    f"No papers found in OSTI database for query: '{search_query}'. "
                    "Try rephrasing with different keywords or broader terms."
                )
            elif relevant_count == 0:
                no_results_msg = (
                    f"Found {len(search_results)} papers for '{search_query}', "
                    "but none were assessed as relevant to your specific question."
                )
            else:
                no_results_msg = (
                    f"Found {len(search_results)} papers, {relevant_count} seemed relevant, "
                    "but could not extract answers (PDFs may not be available or readable)."
                )

            log_progress(no_results_msg)
            suggested_queries = await self.suggest_followup_queries(
                question=question,
                answer=no_results_msg,
                llm=llm,
                provenance=[],
                limit=3,
            )
            return {
                "status": "completed",
                "question": question,
                "answer": no_results_msg,
                "search_query": search_query,
                "papers_assessed": len(search_results),
                "relevant_papers": relevant_count,
                "papers_analyzed": 0,
                "progress_log": progress_log,
                "suggested_queries": suggested_queries,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

        log_progress(f"Synthesizing answer from {len(state['answers_found'])} papers...")
        await send_status(f"Synthesizing answer from {len(state['answers_found'])} papers...")

        final_answer = await self.synthesize_final_answer(question, state["answers_found"], llm)

        # Step 5: Extract and store facts
        log_progress("Storing facts in knowledge base...")
        await send_status("Storing new facts in knowledge base...")

        factoids_stored = await self.extract_and_store_facts(
            question,
            state["answers_found"],
            llm,
        )

        # Step 6: Cache the answer
        await asyncio.to_thread(self.cache_answer, question, final_answer, state["answers_found"])

        elapsed = time.time() - start_time
        log_progress(f"Complete! ({elapsed:.1f}s total)")

        # Build deduplicated provenance with mapping from original paper numbers
        # This allows "Paper 5" in the text to be linked to the correct deduplicated source
        provenance, paper_to_provenance = deduplicate_provenance_with_mapping(state["answers_found"])

        log_progress(f"Deduplicated {len(state['answers_found'])} papers to {len(provenance)} unique sources")

        # Convert "Paper X" citations to clickable links using the mapping
        final_answer = linkify_paper_references(final_answer, provenance, paper_to_provenance)
        suggested_queries = await self.suggest_followup_queries(
            question=question,
            answer=final_answer,
            llm=llm,
            provenance=provenance,
            limit=3,
        )

        return {
            "status": "completed",
            "question": question,
            "answer": final_answer,
            "search_query": search_query,
            "papers_assessed": len(search_results),
            "relevant_papers": relevant_count,
            "papers_analyzed": len(state["answers_found"]),
            "provenance": provenance,
            "facts_stored": factoids_stored,
            "progress_log": progress_log,
            "suggested_queries": suggested_queries,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "agent": "OSTI Research Agent",
        }

    async def _send_final_result(
        self, context: RequestContext, event_queue: EventQueue, result: Dict[str, Any], conversation_id: str = None
    ) -> None:
        """Send the final result to the event queue so it appears in history."""
        logger.info("[RESULT] Sending final result to event queue")

        # Store final status in Redis
        status_id = conversation_id or context.context_id
        self._store_status_in_redis(status_id, "Research complete", final=True)

        # Send the final result as JSON text.
        result_text = json.dumps(result, indent=2, default=str)
        await self.send_status_update(
            context=context,
            event_queue=event_queue,
            state=TaskState.TASK_STATE_COMPLETED,
            final=True,
            message=result_text,
        )
        logger.info(f"[RESULT] Final result sent to event queue ({len(result_text)} chars)")

    async def _execute(
        self,
        params: Dict[str, Any],
        context: RequestContext,
        event_queue: EventQueue,
    ) -> Dict[str, Any]:
        """
        Main entry point for literature search.

        Steps:
        1. Check memory for cached answers
        2. Generate search queries
        3. Search OSTI API
        4. Assess abstracts for relevance
        5. Download relevant papers
        6. Extract answers from papers
        7. Synthesize final answer
        8. Store facts in memory
        9. Return answer with provenance
        """
        logger.info("=" * 60)
        logger.info("OSTI Research Agent - _execute called")
        logger.info("Parameter keys: %s", sorted(params))
        logger.info(f"Context task_id: {context.task_id}")
        logger.info("=" * 60)

        question = params.get("question")
        conversation_id = params.get("conversation_id") or context.context_id or str(uuid.uuid4())

        if not question:
            logger.error("No question provided in params")
            error_result = {
                "status": "error",
                "error": "Parameter 'question' is required",
                "conversation_id": conversation_id,
            }
            await self._send_final_result(context, event_queue, error_result, conversation_id)
            return error_result

        # Step 1: Check memory first
        await self._send_status(
            context, event_queue, "Checking knowledge base for existing answers...", False, conversation_id
        )

        llm_config = LLMConfig.from_env()
        async with self.llm_client(context, config=llm_config) as llm:
            cached_answer = await self.check_memory(question, llm)
        if cached_answer and cached_answer.get("sufficient", True):
            # Cached answers may reference original paper numbering; preserve that mapping
            # while deduplicating to keep links accurate.
            provenance, paper_to_provenance = deduplicate_provenance_with_mapping(cached_answer["sources"])
            answer = linkify_paper_references(cached_answer["answer"], provenance, paper_to_provenance)

            async with self.llm_client(context, config=llm_config) as llm:
                suggested_queries = await self.suggest_followup_queries(
                    question=question,
                    answer=answer,
                    llm=llm,
                    provenance=provenance,
                    limit=3,
                )

            result = {
                "status": "completed",
                "question": question,
                "answer": answer,
                "source": "knowledge_base",
                "provenance": provenance,
                "cached": True,
                "suggested_queries": suggested_queries,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            # Send the result to the event queue so it appears in history
            await self._send_final_result(context, event_queue, result, conversation_id)
            return result
        elif cached_answer and not cached_answer.get("sufficient", False):
            missing_information = cached_answer.get("missing_information")
            if missing_information:
                await self._send_status(
                    context,
                    event_queue,
                    f"Knowledge base has partial information but is insufficient ({missing_information}). Continuing with live OSTI search...",
                    False,
                    conversation_id,
                )
            else:
                await self._send_status(
                    context,
                    event_queue,
                    "Knowledge base has partial information but is insufficient. Continuing with live OSTI search...",
                    False,
                    conversation_id,
                )

        # Step 2-9: Full search workflow
        async with self.llm_client(context, config=llm_config) as llm:
            result = await self.perform_literature_search(
                question,
                context,
                event_queue,
                llm,
                conversation_id,
            )

        # Send the final result to the event queue so it appears in history
        await self._send_final_result(context, event_queue, result, conversation_id)

        return result


if __name__ == "__main__":
    # Create and run the agent
    agent = OSTIResearchAgent(agent_name="OSTI Research Agent")
    agent.run()
