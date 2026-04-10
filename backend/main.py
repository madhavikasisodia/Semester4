import html
import logging
import os
import random
import re
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from itertools import count
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, quote_plus, unquote, urljoin, urlparse
from uuid import uuid4
import json
import asyncio
import xml.etree.ElementTree as ET

import httpx
from bs4 import BeautifulSoup
from fastapi import Depends, File, FastAPI, Form, HTTPException, Header, Query, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator
from supabase import Client, create_client
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

LEETCODE_GRAPHQL_URL = "https://leetcode.com/graphql"
LEETCODE_HEADERS = {
        "Referer": "https://leetcode.com",
        "Origin": "https://leetcode.com",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
}
LEETCODE_PROFILE_QUERY = """
query userProfile($username: String!) {
    matchedUser(username: $username) {
        username
        profile {
            ranking
            reputation
        }
        submitStats: submitStatsGlobal {
            acSubmissionNum {
                difficulty
                count
                submissions
            }
            totalSubmissionNum {
                difficulty
                submissions
            }
        }
    }
}
"""
LEETCODE_TIMEOUT = httpx.Timeout(10.0, connect=5.0)

GITHUB_USER_URL = "https://api.github.com/users/{username}"
GITHUB_TIMEOUT = httpx.Timeout(10.0, connect=5.0)

SCRAPE_TIMEOUT = httpx.Timeout(15.0, connect=5.0)
SCRAPE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

QUIZ_SCRAPE_SOURCES: List[Dict[str, str]] = [
    {
        "name": "Google Interview Warmup",
        "domain": "grow.google",
        "seed_url": "https://grow.google/certificates/interview-warmup/",
    },
    {
        "name": "Exponent",
        "domain": "tryexponent.com",
        "seed_url": "https://www.tryexponent.com/questions",
    },
    {
        "name": "Tech Interview Handbook",
        "domain": "techinterviewhandbook.org",
        "seed_url": "https://www.techinterviewhandbook.org/",
    },
]
QUIZ_SEARCH_RESULTS_PER_SOURCE = 5
QUIZ_SCRAPE_DOC_LIMIT = 10

CODECHEF_PROFILE_URL = "https://www.codechef.com/users/{username}"
CODECHEF_TIMEOUT = httpx.Timeout(10.0, connect=5.0)
CODECHEF_HEADERS = SCRAPE_HEADERS
SCRAPE_ITEM_LIMIT = 10

TOPIC_SCRAPE_CONFIG: Dict[str, Dict[str, Any]] = {
    "dsa": {
        "search_query": "data structures algorithms",
        "devto_tags": ["dsa", "algorithms"],
        "display_name": "DSA",
    },
    "data analytics": {
        "search_query": "data analytics",
        "devto_tags": ["data-analytics", "data"],
        "display_name": "Data Analytics",
    },
    "system design": {
        "search_query": "system design",
        "devto_tags": ["system-design", "architecture"],
        "display_name": "System Design",
    },
    "machine learning": {
        "search_query": "machine learning",
        "devto_tags": ["machine-learning", "ml"],
        "display_name": "Machine Learning",
    },
    "ai": {
        "search_query": "artificial intelligence",
        "devto_tags": ["ai", "artificial-intelligence"],
        "display_name": "AI",
    },
    "devops": {
        "search_query": "devops",
        "devto_tags": ["devops", "sre"],
        "display_name": "DevOps",
    },
    "cloud computing": {
        "search_query": "cloud computing",
        "devto_tags": ["cloud", "aws"],
        "display_name": "Cloud Computing",
    },
    "interview prep": {
        "search_query": "coding interview preparation",
        "devto_tags": ["interview", "career"],
        "display_name": "Interview Prep",
    },
}


def _safe_int(value: Any) -> int:
        try:
                return int(value)
        except (TypeError, ValueError):
                return 0


def _find_difficulty_entry(entries: List[Dict[str, Any]], difficulty: str) -> Dict[str, Any]:
        target = difficulty.lower()
        for entry in entries:
                current = str(entry.get("difficulty", "")).lower()
                if current == target:
                        return entry
        return {}


def _validate_email(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("Email must be a string.")
    normalized = value.strip().lower()
    if not EMAIL_PATTERN.match(normalized):
        raise ValueError("Invalid email format.")
    return normalized


class SignUpRequest(BaseModel):
    email: str
    password: str = Field(..., min_length=6, max_length=64)
    github_username: str = Field(..., min_length=1, max_length=100)
    leetcode_username: str = Field(..., min_length=1, max_length=100)
    metadata: Optional[Dict[str, Any]] = None

    @field_validator("email")
    @classmethod
    def enforce_email(cls, value: str) -> str:
        return _validate_email(value)

    @field_validator("github_username")
    @classmethod
    def normalize_github(cls, value: str) -> str:
        try:
            return _normalize_github_username(value)
        except HTTPException as exc:
            raise ValueError(exc.detail) from exc

    @field_validator("leetcode_username")
    @classmethod
    def normalize_leetcode(cls, value: str) -> str:
        cleaned = (value or "").strip()
        if not cleaned:
            raise ValueError("LeetCode username is required.")
        return cleaned


class LoginRequest(BaseModel):
    email: str
    password: str = Field(..., min_length=6, max_length=64)

    @field_validator("email")
    @classmethod
    def enforce_email(cls, value: str) -> str:
        return _validate_email(value)


class RefreshRequest(BaseModel):
    refresh_token: str = Field(..., min_length=10, description="Supabase refresh token")


class AuthResponse(BaseModel):
    user_id: str
    email: str
    message: str
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None

    @field_validator("email")
    @classmethod
    def enforce_email(cls, value: str) -> str:
        return _validate_email(value)


class HealthResponse(BaseModel):
    status: str


class TopicResourceItem(BaseModel):
    title: str
    url: str
    source: str
    content_type: str
    summary: Optional[str] = None


class TopicResourceResponse(BaseModel):
    topic: str
    items: List[TopicResourceItem]
    fetched_at: str


class Settings(BaseModel):
    supabase_url: str
    supabase_key: str
    cors_origins: List[str]


class InterviewStartRequest(BaseModel):
    persona: str
    candidate_name: str
    target_role: str
    interview_type: str = "technical"
    difficulty: str = "medium"
    duration_minutes: int = Field(30, ge=15, le=120)
    company_context: Optional[str] = None


class AgentRunRequest(BaseModel):
    agent_id: str = Field(..., description="Identifier of the automation agent to execute")
    inputs: Dict[str, Any] = Field(default_factory=dict, description="Optional input payload for the agent")


class QuizGenerateRequest(BaseModel):
    subject: str = Field(..., min_length=1, max_length=100)
    topic: Optional[str] = Field(None, max_length=100)
    difficulty: str = Field("medium")
    num_questions: int = Field(10, ge=1, le=20)
    quiz_type: str = Field("mixed")


class QuizAttemptStartRequest(BaseModel):
    quiz_id: int


class QuizSubmissionAnswer(BaseModel):
    question_id: int
    user_answer: List[str] = Field(default_factory=list)
    time_taken_seconds: Optional[float] = None


class QuizAttemptSubmitRequest(BaseModel):
    attempt_id: int
    answers: List[QuizSubmissionAnswer] = Field(default_factory=list)


def _parse_origins(raw_origins: Optional[str]) -> List[str]:
    if not raw_origins:
        return [
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "http://localhost:8000",
            "http://127.0.0.1:8000",
        ]
    return [origin.strip() for origin in raw_origins.split(",") if origin.strip()]


def _env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@lru_cache
def get_settings() -> Settings:
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_ANON_KEY")
    if not url or not key:
        raise RuntimeError("Supabase credentials missing. Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY.")
    return Settings(supabase_url=url, supabase_key=key, cors_origins=_parse_origins(os.getenv("ALLOWED_ORIGINS")))


supabase_client: Optional[Client] = None


def get_supabase_client() -> Client:
    global supabase_client
    if supabase_client is None:
        settings = get_settings()
        try:
            # Try with basic client options first
            from supabase.lib.client_options import ClientOptions
            from gotrue import SyncMemoryStorage
            
            client_options = ClientOptions(
                storage=SyncMemoryStorage(),
                auto_refresh_token=True,
                persist_session=True
            )
            supabase_client = create_client(
                settings.supabase_url, 
                settings.supabase_key,
                options=client_options
            )
        except Exception as e:
            logger.warning(f"Failed to create client with options, trying basic client: {e}")
            # Fallback to basic client creation
            supabase_client = create_client(settings.supabase_url, settings.supabase_key)
        
        logger.info("Supabase client initialized")
    return supabase_client


def _extract_bearer_token(authorization: Optional[str]) -> str:
    if not authorization:
        raise HTTPException(status_code=401, detail="Authorization header missing.")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status_code=401, detail="Authorization header malformed.")
    return token


async def get_current_user(authorization: Optional[str] = Header(None)) -> Dict[str, Any]:
    if _env_flag("ENABLE_MOCK_AUTH", default=False):
        logger.warning("ENABLE_MOCK_AUTH=true: returning mock user for authenticated endpoints")
        return {"id": "test-user", "email": "test@example.com"}

    token = _extract_bearer_token(authorization)
    client = get_supabase_client()
    try:
        response = await run_in_threadpool(client.auth.get_user, token)
    except Exception as exc:
        logger.warning("Token verification failed", exc_info=True)
        raise HTTPException(status_code=401, detail="Invalid or expired token.") from exc

    user = getattr(response, "user", None)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token.")

    return {"id": user.id, "email": user.email or ""}


def _build_user_profile_record(user_id: str, email: str, metadata: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    meta = metadata or {}
    record = {
        "id": user_id,
        "email": _validate_email(email),
        "full_name": meta.get("full_name"),
        "username": meta.get("username"),
        "job_preference": meta.get("job_preference"),
        "github_username": meta.get("github_username"),
        "leetcode_username": meta.get("leetcode_username"),
    }
    return {key: value for key, value in record.items() if value is not None}


async def _persist_user_profile(client: Client, user_id: str, email: str, metadata: Optional[Dict[str, Any]]) -> None:
    record = _build_user_profile_record(user_id, email, metadata)
    if not record:
        return

    def _upsert() -> None:
        client.table("users").upsert(record).execute()

    await run_in_threadpool(_upsert)


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _isoformat(value: datetime, *, timespec: str = "seconds") -> str:
    return value.isoformat(timespec=timespec).replace("+00:00", "Z")


def _current_timestamp() -> str:
    return _isoformat(_utcnow())


def _github_headers() -> Dict[str, str]:
    headers = {"Accept": "application/vnd.github+json"}
    token = os.getenv("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _normalize_github_username(raw: str) -> str:
    if not isinstance(raw, str):
        raise HTTPException(status_code=400, detail="GitHub username is required.")

    username = raw.strip()
    if username.startswith("@"):
        username = username[1:]

    if not username:
        raise HTTPException(status_code=400, detail="GitHub username is required.")

    if "github.com" in username.lower():
        candidate = username
        if not candidate.startswith("http://") and not candidate.startswith("https://"):
            candidate = "https://" + candidate
        parsed = urlparse(candidate)
        path = parsed.path.strip("/")
        username = path.split("/")[0] if path else ""

    username = username.split("?")[0].split("#")[0].strip().rstrip("/")

    if not username:
        raise HTTPException(status_code=400, detail="GitHub username is required.")

    return username


def _normalize_codechef_username(raw: str) -> str:
    if not isinstance(raw, str):
        raise HTTPException(status_code=400, detail="CodeChef username is required.")

    username = raw.strip()
    if username.startswith("@"):  # allow @handle inputs
        username = username[1:]

    if "codechef.com" in username.lower():
        candidate = username
        if not candidate.startswith("http://") and not candidate.startswith("https://"):
            candidate = "https://" + candidate
        parsed = urlparse(candidate)
        path = parsed.path.strip("/")
        username = path.split("/")[0] if path else ""

    username = username.split("?")[0].split("#")[0].strip().rstrip("/")

    if not username:
        raise HTTPException(status_code=400, detail="CodeChef username is required.")

    return username


def _normalize_topic_key(raw_topic: str) -> str:
    return re.sub(r"\s+", " ", (raw_topic or "").strip().lower())


def _strip_html_tags(value: Optional[str]) -> str:
    if not value:
        return ""
    cleaned = re.sub(r"<[^>]+>", " ", value)
    cleaned = html.unescape(cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def _extract_duckduckgo_target(raw_href: str) -> Optional[str]:
    if not raw_href:
        return None
    href = raw_href.strip()
    if href.startswith("//"):
        href = "https:" + href
    if href.startswith("/"):
        parsed = urlparse(href)
        query_params = parse_qs(parsed.query)
        encoded_target = query_params.get("uddg", [None])[0]
        if encoded_target:
            return unquote(encoded_target)
        return None
    return href


def _extract_keywords_from_text(text: str, *, limit: int = 4) -> List[str]:
    stop_words = {
        "about", "after", "again", "against", "between", "could", "doing", "during", "first", "from",
        "have", "into", "just", "more", "most", "other", "over", "same", "some", "such", "than",
        "that", "their", "there", "these", "they", "this", "those", "through", "under", "very",
        "what", "when", "where", "which", "while", "with", "your", "interview", "practice", "guide",
        "question", "questions", "answer", "answers", "google", "exponent", "tech", "handbook",
    }

    words = re.findall(r"[a-zA-Z][a-zA-Z0-9\-]{3,}", text.lower())
    frequencies: Dict[str, int] = {}
    for word in words:
        if word in stop_words:
            continue
        frequencies[word] = frequencies.get(word, 0) + 1

    ranked = sorted(frequencies.items(), key=lambda item: item[1], reverse=True)
    return [word for word, _ in ranked[:limit]]


async def _search_source_links(source: Dict[str, str], query: str, limit: int = QUIZ_SEARCH_RESULTS_PER_SOURCE) -> List[Dict[str, str]]:
    domain = source["domain"]
    search_query = f"site:{domain} {query}".strip()
    url = f"https://duckduckgo.com/html/?q={quote_plus(search_query)}"
    try:
        async with httpx.AsyncClient(timeout=SCRAPE_TIMEOUT) as client:
            response = await client.get(url, headers=SCRAPE_HEADERS)
            response.raise_for_status()
    except Exception as exc:
        logger.warning("Quiz search failed for %s: %s", domain, exc)
        seed_url = source.get("seed_url")
        return [{"title": f"{source['name']} resource", "url": seed_url}] if seed_url else []

    soup = BeautifulSoup(response.text, "html.parser")
    links: List[Dict[str, str]] = []
    seen: set[str] = set()
    for anchor in soup.select("a.result__a"):
        href = anchor.get("href") or ""
        target = _extract_duckduckgo_target(href)
        if not target:
            continue
        parsed_target = urlparse(target)
        if domain not in parsed_target.netloc:
            continue
        if target in seen:
            continue
        seen.add(target)
        links.append({"title": anchor.get_text(" ", strip=True), "url": target})
        if len(links) >= limit:
            break

    if not links and source.get("seed_url"):
        links.append({"title": f"{source['name']} resource", "url": source["seed_url"]})
    return links


async def _scrape_quiz_resource(link: Dict[str, str], source_name: str, user_query: str) -> Optional[Dict[str, Any]]:
    url = link.get("url")
    if not url:
        return None

    try:
        async with httpx.AsyncClient(timeout=SCRAPE_TIMEOUT, follow_redirects=True) as client:
            response = await client.get(url, headers=SCRAPE_HEADERS)
            response.raise_for_status()
    except Exception as exc:
        logger.warning("Quiz scrape failed for %s: %s", url, exc)
        return None

    soup = BeautifulSoup(response.text, "html.parser")
    for tag_name in ("script", "style", "noscript"):
        for element in soup.find_all(tag_name):
            element.decompose()

    title = (soup.title.string or "").strip() if soup.title and soup.title.string else ""
    if not title:
        title = link.get("title") or source_name

    paragraph_texts: List[str] = []
    for paragraph in soup.find_all("p")[:25]:
        text = paragraph.get_text(" ", strip=True)
        if len(text) >= 60:
            paragraph_texts.append(text)
    combined_text = " ".join(paragraph_texts)

    if not combined_text:
        headers = [h.get_text(" ", strip=True) for h in soup.find_all(["h1", "h2", "h3"])[:8]]
        combined_text = " ".join(item for item in headers if item)

    if not combined_text:
        return None

    summary = combined_text[:450].strip()
    keywords = _extract_keywords_from_text(f"{title} {summary} {user_query}", limit=4)
    if not keywords:
        keywords = [item for item in re.findall(r"[a-zA-Z]{4,}", user_query.lower())[:3]] or ["interview", "problem-solving"]

    return {
        "id": f"scrape-{uuid4().hex[:10]}",
        "title": title,
        "description": summary,
        "source": source_name,
        "difficulty": "medium",
        "tags": [keyword.replace("-", " ") for keyword in keywords],
        "url": url,
    }


async def _scrape_quiz_candidates_from_interview_sites(user_query: str, limit: int = QUIZ_SCRAPE_DOC_LIMIT) -> List[Dict[str, Any]]:
    query = (user_query or "").strip()
    if not query:
        return []

    search_tasks = [
        asyncio.create_task(_search_source_links(source, query, QUIZ_SEARCH_RESULTS_PER_SOURCE))
        for source in QUIZ_SCRAPE_SOURCES
    ]
    search_results = await asyncio.gather(*search_tasks, return_exceptions=True)

    scrape_tasks: List[asyncio.Task] = []
    for source, result in zip(QUIZ_SCRAPE_SOURCES, search_results):
        if isinstance(result, Exception):
            logger.warning("Quiz source search task failed for %s: %s", source["name"], result)
            continue
        for link in result[:QUIZ_SEARCH_RESULTS_PER_SOURCE]:
            scrape_tasks.append(asyncio.create_task(_scrape_quiz_resource(link, source["name"], query)))

    if not scrape_tasks:
        return []

    scraped = await asyncio.gather(*scrape_tasks, return_exceptions=True)
    candidates: List[Dict[str, Any]] = []
    seen_titles: set[str] = set()
    for item in scraped:
        if isinstance(item, Exception):
            logger.warning("Quiz scrape task failed: %s", item)
            continue
        if not item:
            continue
        title_key = _normalize_quiz_text(item.get("title"))
        if not title_key or title_key in seen_titles:
            continue
        seen_titles.add(title_key)
        candidates.append(item)
        if len(candidates) >= limit:
            break

    return candidates


def _resolve_topic_config(topic: str) -> Dict[str, Any]:
    key = _normalize_topic_key(topic)
    base = TOPIC_SCRAPE_CONFIG.get(key)
    if base:
        return {**base}
    normalized = key.replace("_", " ")
    if not normalized:
        normalized = "learning"
    slug = normalized.replace(" ", "-")
    return {
        "search_query": normalized,
        "devto_tags": [slug],
        "display_name": normalized.title(),
    }


async def _scrape_devto_articles(tags: List[str], limit: int = 12) -> List[Dict[str, Any]]:
    if not tags:
        return []
    normalized_tags = [tag.strip() for tag in tags if tag and tag.strip()]
    if not normalized_tags:
        return []

    per_tag_limit = min(15, max(limit, 8))
    articles: List[Dict[str, Any]] = []
    seen_urls: set[str] = set()
    async with httpx.AsyncClient(timeout=SCRAPE_TIMEOUT) as client:
        for tag in normalized_tags:
            params = {"tag": tag, "per_page": per_tag_limit}
            try:
                response = await client.get("https://dev.to/api/articles", params=params, headers=SCRAPE_HEADERS)
                response.raise_for_status()
                payload = response.json() or []
            except Exception as exc:  # broad to keep scraping resilient
                logger.warning("DEV.to scrape failed for tag %s: %s", tag, exc)
                continue

            for article in payload:
                url = (article.get("url") or article.get("canonical_url") or "").strip()
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)
                articles.append(article)
                if len(articles) >= max(limit * 2, 20):
                    break
            if len(articles) >= max(limit * 2, 20):
                break

    items: List[Dict[str, Any]] = []
    for article in articles:
        url = article.get("url") or article.get("canonical_url")
        title = article.get("title")
        if not url or not title:
            continue
        items.append(
            {
                "title": title.strip(),
                "url": url.strip(),
                "source": "DEV Community",
                "content_type": "tutorial",
                "summary": (article.get("description") or "").strip() or None,
            }
        )
        if len(items) >= limit:
            break
    return items[:limit]


async def _scrape_gfg_posts(query: str, limit: int = 15) -> List[Dict[str, Any]]:
    if not query:
        return []
    params = {
        "order": "desc",
        "sort": "relevance",
        "q": query,
        "site": "stackoverflow",
        "pagesize": min(25, max(limit, 10)),
    }
    try:
        async with httpx.AsyncClient(timeout=SCRAPE_TIMEOUT) as client:
            response = await client.get("https://api.stackexchange.com/2.3/search/advanced", params=params, headers=SCRAPE_HEADERS)
            response.raise_for_status()
    except Exception as exc:
        logger.warning("Stack Overflow scrape failed for query '%s': %s", query, exc)
        return []

    posts = response.json().get("items", [])
    items: List[Dict[str, Any]] = []
    for post in posts:
        link = (post.get("link") or "").strip()
        raw_title = post.get("title")
        if not link or not raw_title:
            continue
        items.append(
            {
                "title": _strip_html_tags(raw_title),
                "url": link,
                "source": "Stack Overflow",
                "content_type": "practice",
                "summary": None,
            }
        )
        if len(items) >= limit:
            break
    return items[:limit]


async def _scrape_hn_articles(query: str, limit: int = 12) -> List[Dict[str, Any]]:
    if not query:
        return []
    url = f"https://hnrss.org/newest?q={quote_plus(query)}"
    try:
        async with httpx.AsyncClient(timeout=SCRAPE_TIMEOUT) as client:
            response = await client.get(url, headers=SCRAPE_HEADERS)
            response.raise_for_status()
    except Exception as exc:
        logger.warning("HNRSS scrape failed for query '%s': %s", query, exc)
        return []

    try:
        root = ET.fromstring(response.text)
    except ET.ParseError as exc:
        logger.warning("HNRSS parse failed for query '%s': %s", query, exc)
        return []

    items: List[Dict[str, Any]] = []
    for entry in root.findall("./channel/item")[:limit]:
        title = (entry.findtext("title") or "").strip()
        link = (entry.findtext("link") or "").strip()
        if not title or not link:
            continue
        description = (entry.findtext("description") or "").strip() or None
        items.append(
            {
                "title": title,
                "url": link,
                "source": "Hacker News",
                "content_type": "article",
                "summary": description,
            }
        )
    return items


async def _scrape_topic_resources(topic: str) -> List[Dict[str, Any]]:
    config = _resolve_topic_config(topic)
    query = config.get("search_query") or topic
    tasks = [
        asyncio.create_task(_scrape_devto_articles(config.get("devto_tags", []), SCRAPE_ITEM_LIMIT)),
        asyncio.create_task(_scrape_gfg_posts(query, SCRAPE_ITEM_LIMIT)),
        asyncio.create_task(_scrape_hn_articles(query, SCRAPE_ITEM_LIMIT)),
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    combined: List[Dict[str, Any]] = []
    for result in results:
        if isinstance(result, Exception):
            logger.warning("Scrape task failed for topic %s: %s", topic, result)
            continue
        combined.extend(result)
    if not combined:
        return []
    random.shuffle(combined)
    return combined[:SCRAPE_ITEM_LIMIT]


async def _fetch_leetcode_profile(username: str) -> Dict[str, Any]:
    payload = {
        "operationName": "userProfile",
        "variables": {"username": username},
        "query": LEETCODE_PROFILE_QUERY,
    }

    try:
        async with httpx.AsyncClient(timeout=LEETCODE_TIMEOUT) as client:
            response = await client.post(
                LEETCODE_GRAPHQL_URL,
                json=payload,
                headers=LEETCODE_HEADERS,
            )
            response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        logger.warning("LeetCode API error %s for %s", exc.response.status_code, username)
        raise HTTPException(status_code=502, detail="LeetCode API responded with an error.") from exc
    except httpx.RequestError as exc:
        logger.error("Unable to reach LeetCode for %s: %s", username, exc)
        raise HTTPException(status_code=502, detail="Unable to reach LeetCode at the moment.") from exc

    payload_json = response.json()
    errors = payload_json.get("errors") or []
    if errors:
        message = errors[0].get("message", "")
        logger.warning("LeetCode GraphQL error for %s: %s", username, message)
        if "does not exist" in message.lower():
            raise HTTPException(status_code=404, detail="LeetCode user not found.")
        raise HTTPException(status_code=502, detail="LeetCode API error.")

    matched_user = payload_json.get("data", {}).get("matchedUser")
    if not matched_user:
        raise HTTPException(status_code=404, detail="LeetCode user not found.")

    profile = matched_user.get("profile") or {}
    stats = matched_user.get("submitStats") or {}
    ac_stats = stats.get("acSubmissionNum") or []
    total_stats = stats.get("totalSubmissionNum") or []

    easy = _safe_int(_find_difficulty_entry(ac_stats, "easy").get("count"))
    medium = _safe_int(_find_difficulty_entry(ac_stats, "medium").get("count"))
    hard = _safe_int(_find_difficulty_entry(ac_stats, "hard").get("count"))

    total_all = _safe_int(_find_difficulty_entry(ac_stats, "all").get("count"))
    total_solved = total_all if total_all else easy + medium + hard

    attempts_all = _safe_int(_find_difficulty_entry(total_stats, "all").get("submissions"))
    if attempts_all == 0:
        attempts_all = sum(_safe_int(entry.get("submissions")) for entry in total_stats)
    acceptance_rate = round((total_solved / attempts_all) * 100, 2) if attempts_all else None

    return {
        "username": matched_user.get("username") or username,
        "ranking": profile.get("ranking"),
        "total_solved": total_solved,
        "easy_solved": easy,
        "medium_solved": medium,
        "hard_solved": hard,
        "acceptance_rate": acceptance_rate,
        "reputation": profile.get("reputation"),
        "contribution_points": profile.get("contributionPoints"),
    }


async def _fetch_github_profile(username: str) -> Dict[str, Any]:
    normalized_username = _normalize_github_username(username)
    url = GITHUB_USER_URL.format(username=normalized_username)
    try:
        async with httpx.AsyncClient(timeout=GITHUB_TIMEOUT) as client:
            response = await client.get(url, headers=_github_headers())
            response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        if status == 404:
            raise HTTPException(status_code=404, detail="GitHub user not found.") from exc
        if status == 403:
            raise HTTPException(status_code=429, detail="GitHub API rate limit exceeded.") from exc
        logger.warning("GitHub API error %s for %s", status, normalized_username)
        raise HTTPException(status_code=502, detail="GitHub API responded with an error.") from exc
    except httpx.RequestError as exc:
        logger.error("Unable to reach GitHub for %s: %s", normalized_username, exc)
        raise HTTPException(status_code=502, detail="Unable to reach GitHub at the moment.") from exc

    payload = response.json()
    return {
        "username": payload.get("login") or normalized_username,
        "name": payload.get("name"),
        "bio": payload.get("bio"),
        "public_repos": payload.get("public_repos"),
        "followers": payload.get("followers"),
        "following": payload.get("following"),
        "avatar_url": payload.get("avatar_url"),
        "html_url": payload.get("html_url") or f"https://github.com/{normalized_username}",
        "created_at": payload.get("created_at"),
        "location": payload.get("location"),
        "blog": payload.get("blog"),
    }


async def _fetch_codechef_profile(username: str) -> Dict[str, Any]:
    normalized_username = _normalize_codechef_username(username)
    url = CODECHEF_PROFILE_URL.format(username=normalized_username)
    try:
        async with httpx.AsyncClient(timeout=CODECHEF_TIMEOUT) as client:
            response = await client.get(url, headers=CODECHEF_HEADERS)
            response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        if status == 404:
            raise HTTPException(status_code=404, detail="CodeChef user not found.") from exc
        logger.warning("CodeChef response error %s for %s", status, normalized_username)
        raise HTTPException(status_code=502, detail="CodeChef responded with an error.") from exc
    except httpx.RequestError as exc:
        logger.error("Unable to reach CodeChef for %s: %s", normalized_username, exc)
        raise HTTPException(status_code=502, detail="Unable to reach CodeChef at the moment.") from exc

    soup = BeautifulSoup(response.text, "html.parser")

    def _text(selector: str) -> Optional[str]:
        element = soup.select_one(selector)
        return element.get_text(strip=True) if element else None

    def _int_from_text(value: Optional[str]) -> Optional[int]:
        if not value:
            return None
        match = re.search(r"-?\d+", value.replace(",", ""))
        return int(match.group(0)) if match else None

    def _extract_rank(label: str) -> Optional[int]:
        for container in soup.select(".rating-ranks li, .rating-ranks div"):
            text = container.get_text(" ", strip=True)
            if label.lower() in text.lower():
                match = re.search(r"\d+", text.replace(",", ""))
                if match:
                    return int(match.group(0))
        return None

    rating_text = _text(".rating-number")
    highest_text = _text(".rating-header small") or ""
    highest_rating = _int_from_text(highest_text)
    highest_rating_time = None
    date_match = re.search(r"\d{2}/\d{2}/\d{4}", highest_text)
    if date_match:
        highest_rating_time = date_match.group(0)

    problems_section = soup.select_one("section.problems-solved")
    fully_solved = None
    partially_solved = None
    if problems_section:
        text = problems_section.get_text(" ", strip=True)
        full_match = re.search(r"Fully\s+Solved.*?:\s*(\d+)", text)
        partial_match = re.search(r"Partially\s+Solved.*?:\s*(\d+)", text)
        if full_match:
            fully_solved = int(full_match.group(1))
        if partial_match:
            partially_solved = int(partial_match.group(1))

    return {
        "username": normalized_username,
        "rating": _int_from_text(rating_text),
        "stars": _text(".rating-star"),
        "highest_rating": highest_rating,
        "highest_rating_time": highest_rating_time,
        "global_rank": _extract_rank("Global Rank"),
        "country_rank": _extract_rank("Country Rank"),
        "fully_solved": fully_solved,
        "partially_solved": partially_solved,
    }


QUESTION_BANK: Dict[str, List[Dict[str, Any]]] = {
    "algorithms": [
        {
            "id": "algo-1",
            "title": "Two Sum Variations",
            "difficulty": "easy",
            "description": "Design an algorithm that returns all index pairs summing to a target value.",
            "link": "https://leetcode.com/problems/two-sum/",
            "source": "leetcode",
            "tags": ["array", "hashmap"],
            "companies": ["Google", "Microsoft"],
        },
        {
            "id": "algo-2",
            "title": "LRU Cache Design",
            "difficulty": "medium",
            "description": "Implement an LRU cache with O(1) get and put operations.",
            "link": "https://leetcode.com/problems/lru-cache/",
            "source": "leetcode",
            "tags": ["design", "linked-list"],
            "companies": ["Amazon", "Meta"],
        },
        {
            "id": "algo-3",
            "title": "K Most Frequent Elements",
            "difficulty": "medium",
            "description": "Return the k most frequent integers from an array of size n.",
            "link": "https://leetcode.com/problems/top-k-frequent-elements/",
            "source": "leetcode",
            "tags": ["heap", "bucket-sort"],
            "companies": ["Google", "Uber"],
        },
        {
            "id": "algo-4",
            "title": "Serialize and Deserialize Binary Tree",
            "difficulty": "hard",
            "description": "Design an algorithm to serialize and deserialize a binary tree without losing structure.",
            "link": "https://leetcode.com/problems/serialize-and-deserialize-binary-tree/",
            "source": "leetcode",
            "tags": ["tree", "design"],
            "companies": ["Amazon", "Bloomberg"],
        },
    ],
    "system-design": [
        {
            "id": "sd-1",
            "title": "Design URL Shortener",
            "difficulty": "medium",
            "description": "Discuss storage, API design, analytics, and scalability considerations.",
            "link": "https://systemdesign.one/url-shortening-service/",
            "source": "system-design.one",
            "tags": ["databases", "caching"],
            "companies": ["Bitly"],
        },
        {
            "id": "sd-2",
            "title": "Design Real-time Chat",
            "difficulty": "hard",
            "description": "Support typing indicators, message ordering, presence, and attachments at scale.",
            "link": "https://systemexpert.ai/chat-system-design/",
            "source": "systemexpert.ai",
            "tags": ["websocket", "queues"],
            "companies": ["Slack", "Discord"],
        },
        {
            "id": "sd-3",
            "title": "Design News Feed",
            "difficulty": "medium",
            "description": "Balance fan-out-on-write vs fan-out-on-read strategies and ranking signals.",
            "link": "https://systemdesignprep.com/news-feed",
            "source": "systemdesignprep.com",
            "tags": ["ranking", "databases"],
            "companies": ["Meta"],
        },
    ],
    "behavioral": [
        {
            "id": "beh-1",
            "title": "Conflict Resolution",
            "difficulty": "easy",
            "description": "Describe a time you disagreed with a teammate and how you resolved it.",
            "link": "https://www.interviewbit.com",
            "source": "interviewbit",
            "tags": ["communication"],
            "companies": ["Google", "Dropbox"],
        },
        {
            "id": "beh-2",
            "title": "Leadership Moment",
            "difficulty": "medium",
            "description": "Share a situation where you led without formal authority.",
            "link": "https://www.themuse.com",
            "source": "themuse",
            "tags": ["leadership"],
            "companies": ["Amazon"],
        },
    ],
}


ANSWER_KEYS: Dict[str, Dict[str, Any]] = {
    "algo-1": {
        "concepts": [
            {"label": "Hash map to store complements", "keywords": ["hash map", "hashmap", "dictionary", "map"]},
            {"label": "Single pass iteration", "keywords": ["single pass", "one pass", "linear time", "o(n)"]},
            {"label": "Return indices instead of values", "keywords": ["index", "indices", "position"]},
            {"label": "Avoid reusing the same index twice", "keywords": ["duplicate", "reuse", "same index"]},
        ],
        "sample_answer": (
            "Scan the array once while storing each value's index in a hash map. "
            "For every number check whether target - num already exists in the map; if it does, "
            "return the stored index and the current index. This yields O(n) time and O(n) space and "
            "never reuses the same element twice."
        ),
        "complexity": {"time": "O(n)", "space": "O(n)"},
        "follow_ups": [
            "How would you solve Two Sum when the input is a stream?",
            "Can you do it if the array is already sorted?",
        ],
        "passing_threshold": 0.7,
    },
    "algo-2": {
        "concepts": [
            {"label": "Hash map from key to node", "keywords": ["hash map", "hashmap", "dictionary"]},
            {"label": "Doubly linked list for recency order", "keywords": ["doubly", "linked list", "dll"]},
            {"label": "O(1) get and put by moving nodes", "keywords": ["o(1)", "constant", "move to head"]},
            {"label": "Evict least recently used entry", "keywords": ["evict", "tail", "least recently"]},
        ],
        "sample_answer": (
            "Maintain a hash map that points to nodes inside a custom doubly linked list ordered by recency. "
            "Every get moves the node to the front; every put inserts a new node at the front and trims the tail when "
            "capacity is exceeded. Both structures keep operations O(1)."
        ),
        "complexity": {"time": "O(1) per op", "space": "O(capacity)"},
        "follow_ups": [
            "What changes if the cache must be thread-safe?",
            "How would you persist hot entries to disk?",
        ],
        "passing_threshold": 0.75,
    },
    "algo-3": {
        "concepts": [
            {"label": "Frequency map of numbers", "keywords": ["frequency", "count", "hash map", "dictionary"]},
            {"label": "Use heap or bucket sort to extract top k", "keywords": ["heap", "bucket", "priority queue"]},
            {"label": "Discuss complexity vs n and k", "keywords": ["o(n log k)", "o(n)", "linear"]},
        ],
        "sample_answer": (
            "Count how often every number appears using a hash map, then push the entries into a min-heap of size k "
            "(or buckets indexed by frequency) so we always keep the k most frequent values. That runs in O(n log k) time."
        ),
        "complexity": {"time": "O(n log k) or O(n)", "space": "O(n)"},
        "follow_ups": [
            "When would you prefer buckets over a heap?",
            "Can you solve it when k is close to n?",
        ],
        "passing_threshold": 0.66,
    },
    "algo-4": {
        "concepts": [
            {"label": "Mark null children while serializing", "keywords": ["null", "#", "None marker", "sentinel"]},
            {"label": "Deterministic traversal order", "keywords": ["preorder", "breadth", "dfs"]},
            {"label": "Symmetric deserialize routine", "keywords": ["pointer", "iterator", "rebuild"]},
            {"label": "Complexity discussion", "keywords": ["o(n)", "linear time", "linear space"]},
        ],
        "sample_answer": (
            "Use preorder traversal and append either the node value or a # sentinel for null children. "
            "During deserialize consume tokens from an iterator: whenever you see a sentinel return None; otherwise build a node "
            "recursively. Both directions touch each node once so the solution is O(n)."
        ),
        "complexity": {"time": "O(n)", "space": "O(n)"},
        "follow_ups": [
            "How would you handle very deep trees?",
            "Could you encode it iteratively?",
        ],
        "passing_threshold": 0.7,
    },
    "sd-1": {
        "concepts": [
            {"label": "Base62 short code generation", "keywords": ["base62", "base 62", "hashids", "short code"]},
            {"label": "Key-value store for mappings", "keywords": ["key-value", "redis", "dynamodb", "datastore"]},
            {"label": "Expiration or TTL handling", "keywords": ["ttl", "expiry", "expiration"]},
            {"label": "Analytics or rate limiting", "keywords": ["analytics", "metrics", "rate limit"]},
        ],
        "sample_answer": (
            "Accept a long URL, generate a collision-resistant base62 slug, and store the mapping in a replicated key-value store. "
            "Reads hit a CDN-friendly redirect service, while async workers record analytics and enforce TTL or custom domains."
        ),
        "follow_ups": [
            "How would you prevent hot-key issues?",
            "Explain how custom domains would work.",
        ],
        "passing_threshold": 0.6,
    },
    "sd-2": {
        "concepts": [
            {"label": "WebSocket or long-lived transport", "keywords": ["websocket", "socket", "long polling"]},
            {"label": "Fan-out tier with queue", "keywords": ["pubsub", "kafka", "queue", "fan-out"]},
            {"label": "Persistence for chat history", "keywords": ["database", "s3", "cold storage", "history"]},
            {"label": "Presence and typing indicators", "keywords": ["presence", "typing", "online state"]},
        ],
        "sample_answer": (
            "Clients connect through a gateway that terminates WebSockets. Messages go through a pub/sub bus so we can fan-out "
            "to all participants, while a write path persists them to storage. A cache keeps recent conversations, and a presence "
            "service tracks online users and typing indicators."
        ),
        "follow_ups": [
            "Where do you enforce ordering?",
            "How do you handle back-pressure when a client is slow?",
        ],
        "passing_threshold": 0.65,
    },
    "sd-3": {
        "concepts": [
            {"label": "Fan-out on write vs read", "keywords": ["fan-out", "write", "read"]},
            {"label": "Ranking signal pipeline", "keywords": ["ranking", "ml", "scoring", "signals"]},
            {"label": "Caching hot feeds", "keywords": ["cache", "redis", "memcache"]},
            {"label": "Batching background jobs", "keywords": ["worker", "async", "batch"]},
        ],
        "sample_answer": (
            "Writers push activities into a log, a fan-out service materializes personalized feeds for high-QPS users, "
            "and low-traffic users read on demand. A ranking pipeline blends social graph data with freshness signals and the "
            "top stories are cached per user."
        ),
        "follow_ups": [
            "How would you support topic-based feeds?",
            "Discuss eventual consistency issues.",
        ],
        "passing_threshold": 0.6,
    },
    "beh-1": {
        "concepts": [
            {"label": "Uses STAR structure", "keywords": ["situation", "task", "action", "result", "star"]},
            {"label": "Explains the disagreement", "keywords": ["disagree", "conflict", "misaligned"]},
            {"label": "Shares resolution and impact", "keywords": ["aligned", "compromise", "resolved", "impact"]},
        ],
        "sample_answer": (
            "Situation: a teammate and I disagreed on rolling back a release. Task: keep production stable without derailing "
            "the roadmap. Action: I gathered error data, created a quick spike to prove the fix, and facilitated a review. Result: "
            "we shipped the safer change within a day and both of us documented a playbook."
        ),
        "follow_ups": [
            "What would you repeat or avoid next time?",
            "How did the relationship evolve afterward?",
        ],
        "passing_threshold": 0.6,
    },
    "beh-2": {
        "concepts": [
            {"label": "Describes leadership without authority", "keywords": ["influence", "led", "without authority"]},
            {"label": "Mentions measurable outcome", "keywords": ["metric", "result", "impact", "kpi"]},
            {"label": "Reflects on lessons learned", "keywords": ["learned", "lesson", "retrospective"]},
        ],
        "sample_answer": (
            "I noticed our deploy pipeline failed 20% of the time, so I volunteered to coordinate a fix even though I was an IC. "
            "I aligned QA and DevOps on a shared goal, built a lightweight RFC, and tracked progress in public. Deployment failures "
            "dropped to 2% and the team later asked me to lead similar efforts."
        ),
        "follow_ups": [
            "How did you balance this with your core work?",
            "What feedback did you get from the team?",
        ],
        "passing_threshold": 0.6,
    },
}


INTERVIEW_TYPE_TOPIC_MAP: Dict[str, List[str]] = {
    "technical": ["algorithms", "system-design"],
    "coding": ["algorithms"],
    "system_design": ["system-design"],
    "system-design": ["system-design"],
    "behavioral": ["behavioral"],
    "hr_screening": ["behavioral"],
}


COMPANY_DATA: Dict[str, Dict[str, Any]] = {
    "google": {
        "name": "Google",
        "description": "Teams build products that organize the world's information.",
        "headquarters": "Mountain View, CA",
        "industry": "Technology",
        "founded": 1998,
        "employees": "180k+",
        "website": "https://careers.google.com",
        "requirements": {
            "company": "Google",
            "technical_skills": ["Data Structures", "Distributed Systems", "Go", "Java"],
            "soft_skills": ["Product mindset", "Collaboration"],
            "educational_requirements": ["BS in CS or equivalent experience"],
            "experience_levels": {
                "entry": "Internships or 1-2 years",
                "mid": "4-6 years shipping products",
                "senior": "8+ years with architectural ownership",
            },
            "certifications": ["GCP Professional Cloud Architect"],
        },
        "process": {
            "company": "Google",
            "stages": [
                {
                    "stage_number": 1,
                    "name": "Recruiter Screen",
                    "description": "Discuss background and preferred teams.",
                    "duration": "30 mins",
                    "tips": ["Highlight impact", "Show product passion"],
                },
                {
                    "stage_number": 2,
                    "name": "Technical Screens",
                    "description": "Two coding interviews covering DSA and problem solving.",
                    "duration": "45 mins x2",
                    "tips": ["Think aloud", "Cover trade-offs"],
                },
                {
                    "stage_number": 3,
                    "name": "Onsite Loop",
                    "description": "System design, coding, and behavioral interviews.",
                    "duration": "Half day",
                    "tips": ["Structure answers", "Use frameworks"],
                },
            ],
            "total_duration": "3-5 weeks",
            "preparation_tips": ["Practice whiteboarding", "Study distributed systems"],
        },
        "salary": {
            "company": "Google",
            "positions": [
                {
                    "role": "Software Engineer",
                    "level": "L4",
                    "salary_range": "$220k - $310k",
                    "stock_options": "$80k annualized",
                    "bonus": "15% target",
                    "benefits": ["401k", "Health", "Wellness budget"],
                },
                {
                    "role": "Senior Software Engineer",
                    "level": "L5",
                    "salary_range": "$300k - $420k",
                    "stock_options": "$150k annualized",
                    "bonus": "20% target",
                    "benefits": ["Sabbatical", "Hybrid flexibility"],
                },
            ],
            "location_factor": "Bay Area baseline",
            "negotiation_tips": ["Benchmark with levels.fyi", "Emphasize competing offers"],
        },
        "preparation": {
            "company": "Google",
            "technical_preparation": {
                "data_structures": ["Trees", "Graphs", "DP"],
                "algorithms": ["Greedy", "Backtracking"],
                "system_design_topics": ["GFS", "Spanner"],
                "coding_practice_sites": ["LeetCode", "AlgoExpert"],
            },
            "behavioral_preparation": {
                "common_questions": ["Tell me about a challenge", "Impact you are proud of"],
                "tips": ["Use STAR", "Align to Googleyness"],
            },
            "resources": {
                "books": ["Cracking the Coding Interview"],
                "online_courses": ["Udemy System Design"],
                "practice_platforms": ["Exponent", "Interviewing.io"],
            },
            "timeline": "Plan 4-6 weeks of prep",
        },
    },
    "microsoft": {
        "name": "Microsoft",
        "description": "Build cloud-first solutions that empower every person and organization.",
        "headquarters": "Redmond, WA",
        "industry": "Technology",
        "founded": 1975,
        "employees": "220k+",
        "website": "https://careers.microsoft.com",
        "requirements": {
            "company": "Microsoft",
            "technical_skills": ["C#", ".NET", "Azure", "Data Structures"],
            "soft_skills": ["Growth mindset", "Collaboration"],
            "educational_requirements": ["BS/MS in CS or related"],
            "experience_levels": {
                "entry": "Internships or 1-2 years",
                "mid": "3-5 years shipping enterprise software",
                "senior": "7+ years, cross-team leadership",
            },
            "certifications": ["Azure Developer Associate"],
        },
        "process": {
            "company": "Microsoft",
            "stages": [
                {
                    "stage_number": 1,
                    "name": "Online Assessment",
                    "description": "Coding OAs via Codility.",
                    "duration": "90 mins",
                    "tips": ["Practice array + string problems"],
                },
                {
                    "stage_number": 2,
                    "name": "Onsite Loop",
                    "description": "4 interviews covering coding, design, and culture.",
                    "duration": "Half day",
                    "tips": ["Demonstrate learn-it-all attitude"],
                },
            ],
            "total_duration": "2-4 weeks",
            "preparation_tips": ["Brush up on Azure", "Practice behavioral stories"],
        },
        "salary": {
            "company": "Microsoft",
            "positions": [
                {
                    "role": "Software Engineer",
                    "level": "63",
                    "salary_range": "$180k - $250k",
                    "stock_options": "$40k annualized",
                    "bonus": "10%",
                    "benefits": ["ESP", "Healthcare"],
                }
            ],
            "location_factor": "Redmond baseline",
            "negotiation_tips": ["Highlight cloud experience"],
        },
        "preparation": {
            "company": "Microsoft",
            "technical_preparation": {
                "data_structures": ["Linked Lists", "Graphs"],
                "algorithms": ["Dynamic Programming"],
                "system_design_topics": ["Event sourcing"],
                "coding_practice_sites": ["HackerRank"],
            },
            "behavioral_preparation": {
                "common_questions": ["Tell me about a time you failed"],
                "tips": ["Show growth mindset"],
            },
            "resources": {
                "books": ["Designing Data-Intensive Applications"],
                "online_courses": ["PluralSight Azure"],
                "practice_platforms": ["LeetCode"],
            },
            "timeline": "3-4 weeks",
        },
    },
    "openai": {
        "name": "OpenAI",
        "description": "Research and deploy safe AGI.",
        "headquarters": "San Francisco, CA",
        "industry": "AI Research",
        "founded": 2015,
        "employees": "1k+",
        "website": "https://openai.com/careers",
        "requirements": {
            "company": "OpenAI",
            "technical_skills": ["Python", "Distributed Training", "ML Ops"],
            "soft_skills": ["Research communication", "Product intuition"],
            "educational_requirements": ["Advanced degree preferred"],
            "experience_levels": {
                "entry": "Strong research internships",
                "mid": "3-5 years ML production",
                "senior": "7+ years with publications",
            },
            "certifications": ["TensorFlow Developer"],
        },
        "process": {
            "company": "OpenAI",
            "stages": [
                {
                    "stage_number": 1,
                    "name": "Research Conversation",
                    "description": "Discuss recent work and interests.",
                    "duration": "45 mins",
                    "tips": ["Highlight publications"],
                },
                {
                    "stage_number": 2,
                    "name": "Technical Deep Dive",
                    "description": "Whiteboard ML system design and debugging.",
                    "duration": "90 mins",
                    "tips": ["Connect to safety goals"],
                },
                {
                    "stage_number": 3,
                    "name": "Onsite",
                    "description": "Pair programming + culture interviews.",
                    "duration": "Full day",
                    "tips": ["Demonstrate ethics"],
                },
            ],
            "total_duration": "4-6 weeks",
            "preparation_tips": ["Review recent OpenAI papers", "Practice ML design"],
        },
        "salary": {
            "company": "OpenAI",
            "positions": [
                {
                    "role": "Applied Scientist",
                    "level": "Senior",
                    "salary_range": "$320k - $520k",
                    "stock_options": "Unit appreciation",
                    "bonus": "20%",
                    "benefits": ["Healthcare", "Wellness stipend"],
                }
            ],
            "location_factor": "SF baseline",
            "negotiation_tips": ["Showcase publications", "Discuss comp philosophy"],
        },
        "preparation": {
            "company": "OpenAI",
            "technical_preparation": {
                "data_structures": ["Vectors", "Matrices"],
                "algorithms": ["Optimization"],
                "system_design_topics": ["Inference serving"],
                "coding_practice_sites": ["Kaggle"],
            },
            "behavioral_preparation": {
                "common_questions": ["How do you ensure responsible AI?"],
                "tips": ["Tie answers to mission"],
            },
            "resources": {
                "books": ["Deep Learning"],
                "online_courses": ["fast.ai"],
                "practice_platforms": ["Papers with Code"],
            },
            "timeline": "6+ weeks",
        },
    },
}


RECOMMENDATIONS: List[Dict[str, Any]] = [
    {
        "id": 1,
        "user_id": 1,
        "title": "Master Binary Trees",
        "description": "Work through advanced tree traversals and segment trees.",
        "category": "Data Structures",
        "priority": "high",
        "source": "AI Coach",
        "resources": [
            {"title": "NeetCode Trees", "url": "https://neetcode.io/tree"},
            {"title": "Segment Tree Guide", "url": "https://cp-algorithms.com"},
        ],
        "estimated_time": "6 hours",
        "status": "in-progress",
        "created_at": _isoformat(_utcnow() - timedelta(days=4)),
        "completed_at": None,
    },
    {
        "id": 2,
        "user_id": 1,
        "title": "Refresh System Design",
        "description": "Focus on consistency models and capacity planning.",
        "category": "System Design",
        "priority": "medium",
        "source": "Mentor",
        "resources": [{"title": "ByteByteGo newsletter", "url": "https://bytebytego.com"}],
        "estimated_time": "8 hours",
        "status": "pending",
        "created_at": _isoformat(_utcnow() - timedelta(days=2)),
        "completed_at": None,
    },
]


TEST_SCORES = [
    {
        "id": 1,
        "user_id": 1,
        "test_type": "mock",
        "subject": "Data Structures",
        "score": 78,
        "max_score": 100,
        "percentage": 78,
        "date_taken": _isoformat(_utcnow() - timedelta(days=10)),
        "duration_minutes": 60,
        "topics_covered": ["Trees", "Graphs"],
        "weak_topics": ["Union Find"],
    },
    {
        "id": 2,
        "user_id": 1,
        "test_type": "mock",
        "subject": "System Design",
        "score": 84,
        "max_score": 100,
        "percentage": 84,
        "date_taken": _isoformat(_utcnow() - timedelta(days=3)),
        "duration_minutes": 75,
        "topics_covered": ["Caching", "Queues"],
        "weak_topics": ["CAP trade-offs"],
    },
]


def _build_progress_history() -> List[Dict[str, Any]]:
    history: List[Dict[str, Any]] = []
    today = _utcnow().date()
    for idx in range(14):
        day = today - timedelta(days=13 - idx)
        history.append(
            {
                "id": idx + 1,
                "user_id": 1,
                "date": day.isoformat(),
                "problems_solved": random.randint(1, 6),
                "tests_taken": random.randint(0, 1),
                "interviews_completed": random.randint(0, 1),
                "time_spent_minutes": random.randint(30, 150),
                "skills_practiced": random.sample(["Arrays", "Graphs", "System Design", "Behavioral"], k=2),
                "current_streak": random.randint(1, 10),
                "longest_streak": 14,
            }
        )
    return history


PROGRESS_HISTORY = _build_progress_history()


ACHIEVEMENTS = [
    {
        "id": 1,
        "user_id": 1,
        "title": "Consistency Champ",
        "description": "Practiced 7 days in a row",
        "badge_icon": "🔥",
        "earned_date": _isoformat(_utcnow() - timedelta(days=5)),
        "category": "Streak",
        "points": 50,
    },
    {
        "id": 2,
        "user_id": 1,
        "title": "System Design Ready",
        "description": "Completed three design mocks",
        "badge_icon": "🧠",
        "earned_date": _isoformat(_utcnow() - timedelta(days=1)),
        "category": "Milestone",
        "points": 80,
    },
]


RESUMES: List[Dict[str, Any]] = []
CERTIFICATIONS: List[Dict[str, Any]] = []
RESUME_ID_COUNTER = count(1)
CERTIFICATE_ID_COUNTER = count(1)


def _aggregate_skill_focus(history: List[Dict[str, Any]]) -> List[Tuple[str, int]]:
    counts: Dict[str, int] = {}
    for entry in history:
        for skill in entry.get("skills_practiced", []) or []:
            counts[skill] = counts.get(skill, 0) + 1
    return sorted(counts.items(), key=lambda item: item[1], reverse=True)


def _recent_history_window(days: int) -> List[Dict[str, Any]]:
    if not PROGRESS_HISTORY:
        return []
    window = max(1, days)
    return PROGRESS_HISTORY[-min(window, len(PROGRESS_HISTORY)) :]


def _compute_metric_delta(history: List[Dict[str, Any]], field: str) -> float:
    if len(history) < 2:
        return 0.0
    return float(history[-1].get(field, 0) - history[0].get(field, 0))


def _get_top_recommendations(limit: int = 3) -> List[Dict[str, Any]]:
    sorted_recs = sorted(RECOMMENDATIONS, key=lambda rec: rec.get("created_at", ""), reverse=True)
    return sorted_recs[:limit]


def _execute_progress_coach(inputs: Dict[str, Any]) -> Dict[str, Any]:
    requested_days = inputs.get("days")
    try:
        days = int(requested_days)
    except (TypeError, ValueError):
        days = 7
    days = max(3, min(30, days))
    window = _recent_history_window(days)
    if not window:
        return {
            "summary": "No practice activity recorded yet.",
            "insights": [],
            "recommended_actions": ["Log at least one study session so the coach can detect patterns."],
        }

    stats = _calculate_progress_stats()
    avg_problems = round(sum(item.get("problems_solved", 0) for item in window) / len(window), 2)
    avg_minutes = round(sum(item.get("time_spent_minutes", 0) for item in window) / len(window), 1)
    velocity = _compute_metric_delta(window, "problems_solved")
    best_day = max(window, key=lambda item: item.get("problems_solved", 0))
    slow_day = min(window, key=lambda item: item.get("problems_solved", 0))
    skills_ranked = _aggregate_skill_focus(window)
    global_skills = _aggregate_skill_focus(PROGRESS_HISTORY)
    focus_skill = skills_ranked[0][0] if skills_ranked else None
    neglected_skills = [skill for skill, _ in global_skills if skill not in {skill for skill, _ in skills_ranked[:2]}]

    insights = [
        {
            "label": "Daily Throughput",
            "detail": f"Averaging {avg_problems} problems and {avg_minutes} minutes per day over the last {len(window)} days.",
        },
        {
            "label": "Momentum",
            "detail": "Trending up" if velocity > 0 else "Holding steady" if velocity == 0 else "Slight dip—plan a catch-up session.",
            "delta": velocity,
        },
        {
            "label": "Peak Performance",
            "detail": f"Best output was {best_day.get('problems_solved', 0)} problems on {best_day.get('date')}.",
        },
    ]

    recommended_actions = []
    if focus_skill:
        recommended_actions.append(
            f"Double down on {focus_skill} with a timed mock this week to cement gains."
        )
    if neglected_skills:
        recommended_actions.append(
            f"Rotate in {neglected_skills[0]} to balance your skill exposure."
        )
    if slow_day.get("problems_solved", 0) <= max(1, best_day.get("problems_solved", 0) // 2):
        recommended_actions.append(
            "Schedule a lighter review block immediately after intense practice days to avoid burnout."
        )
    recommended_actions.append(
        f"Target {stats['current_streak'] + 1} days of streak to surpass your current {stats['longest_streak']}-day record."
    )

    preview_recs = [
        {
            "id": rec["id"],
            "title": rec["title"],
            "priority": rec["priority"],
            "status": rec["status"],
        }
        for rec in _get_top_recommendations()
    ]

    return {
        "summary": f"Consistent practice detected with {stats['total_problems_solved']} total problems solved.",
        "insights": insights,
        "recommended_actions": recommended_actions,
        "preview_recommendations": preview_recs,
        "inputs_used": {"days": len(window)},
    }


def _execute_career_strategy(inputs: Dict[str, Any]) -> Dict[str, Any]:
    company_input = inputs.get("company") or inputs.get("target_company") or "Google"
    company = _get_company_or_404(company_input)
    requirements = company.get("requirements", {})
    technical_targets = requirements.get("technical_skills", [])
    practiced_skills = [skill for skill, _ in _aggregate_skill_focus(PROGRESS_HISTORY)]
    matched = [skill for skill in technical_targets if skill in practiced_skills]
    gaps = [skill for skill in technical_targets if skill not in matched]
    credential_snapshot = {
        "resumes_uploaded": len(RESUMES),
        "certifications": len(CERTIFICATIONS),
        "latest_certification": CERTIFICATIONS[-1]["name"] if CERTIFICATIONS else None,
        "achievements": len(ACHIEVEMENTS),
    }

    recommended_focus = []
    if gaps:
        recommended_focus.append(f"Add focused practice for {gaps[0]} to match {company['name']} expectations.")
    if credential_snapshot["resumes_uploaded"] == 0:
        recommended_focus.append("Upload a resume to unlock AI-driven resume critiques.")
    if credential_snapshot["certifications"] == 0:
        recommended_focus.append("Earn at least one certification that aligns with your target cloud/provider stack.")

    highlighted_resources = [
        {
            "title": rec["title"],
            "category": rec["category"],
            "priority": rec["priority"],
        }
        for rec in _get_top_recommendations(2)
    ]

    return {
        "company": company["name"],
        "summary": f"Generated a readiness plan for {company['name']} using current practice signals.",
        "skill_alignment": {
            "matched": matched,
            "gaps": gaps,
            "practice_sample": practiced_skills[:5],
        },
        "credential_snapshot": credential_snapshot,
        "suggested_actions": recommended_focus or ["Keep shipping portfolio updates weekly."] ,
        "supporting_resources": highlighted_resources,
    }


AGENT_CATALOG: List[Dict[str, Any]] = [
    {
        "id": "progress-coach",
        "name": "Progress Coach",
        "description": "Analyzes recent learning telemetry and prescribes the next focus areas.",
        "inputs_schema": {
            "days": {
                "type": "integer",
                "minimum": 3,
                "maximum": 30,
                "default": 7,
                "description": "Number of recent days to inspect",
            }
        },
        "capabilities": ["progress", "learning-plan", "insights"],
    },
    {
        "id": "career-strategist",
        "name": "Career Strategist",
        "description": "Maps your current readiness to a target company and highlights gaps.",
        "inputs_schema": {
            "company": {
                "type": "string",
                "description": "Company name (Google, Microsoft, etc.)",
                "default": "Google",
            }
        },
        "capabilities": ["career-planning", "company-readiness"],
    },
]


AGENT_EXECUTORS = {
    "progress-coach": _execute_progress_coach,
    "career-strategist": _execute_career_strategy,
}


AGENT_RUNS: Dict[str, Dict[str, Any]] = {}
MAX_AGENT_RUNS = 50


def _get_agent_definition(agent_id: str) -> Dict[str, Any]:
    for agent in AGENT_CATALOG:
        if agent["id"] == agent_id:
            return agent
    raise HTTPException(status_code=404, detail="Agent not found")


def _store_agent_run(agent_id: str, inputs: Dict[str, Any], status: str, result: Dict[str, Any]) -> Dict[str, Any]:
    run_id = str(uuid4())
    entry = {
        "run_id": run_id,
        "agent_id": agent_id,
        "inputs": inputs,
        "status": status,
        "result": result,
        "created_at": _current_timestamp(),
    }
    AGENT_RUNS[run_id] = entry
    if len(AGENT_RUNS) > MAX_AGENT_RUNS:
        oldest_id = min(AGENT_RUNS, key=lambda key: AGENT_RUNS[key]["created_at"])
        AGENT_RUNS.pop(oldest_id, None)
    return entry


INTERVIEW_PERSONAS = [
    {
        "persona_id": "mentor",
        "name": "Supportive Mentor",
        "tone": "encouraging",
        "style": "Guided conversation with hints",
        "intro_message": "Let's work through problems step by step.",
    },
    {
        "persona_id": "hiring-manager",
        "name": "Hiring Manager",
        "tone": "professional",
        "style": "Focus on impact and communication",
        "intro_message": "I'm evaluating how you solve meaningful problems.",
    },
    {
        "persona_id": "bar-raiser",
        "name": "Bar Raiser",
        "tone": "challenging",
        "style": "High standards with deep dives",
        "intro_message": "Expect probing follow-ups and system questions.",
    },
]


INTERVIEW_SESSIONS: Dict[str, Dict[str, Any]] = {}

# WebSocket connection manager
class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, List[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, client_id: str):
        await websocket.accept()
        if client_id not in self.active_connections:
            self.active_connections[client_id] = []
        self.active_connections[client_id].append(websocket)

    def disconnect(self, websocket: WebSocket, client_id: str):
        if client_id in self.active_connections:
            self.active_connections[client_id] = [
                conn for conn in self.active_connections[client_id] if conn != websocket
            ]
            if not self.active_connections[client_id]:
                del self.active_connections[client_id]

    async def send_personal_message(self, message: dict, client_id: str):
        if client_id in self.active_connections:
            for connection in self.active_connections[client_id]:
                try:
                    await connection.send_text(json.dumps(message))
                except:
                    pass

    async def broadcast_message(self, message: dict):
        for client_connections in self.active_connections.values():
            for connection in client_connections:
                try:
                    await connection.send_text(json.dumps(message))
                except:
                    pass

manager = ConnectionManager()

# Mock data storage for learning management
USER_RECOMMENDATIONS: Dict[str, List[Dict[str, Any]]] = {}
USER_PROGRESS_STATS: Dict[str, Dict[str, Any]] = {}
USER_PROGRESS_HISTORY: Dict[str, List[Dict[str, Any]]] = {}
USER_ACHIEVEMENTS: Dict[str, List[Dict[str, Any]]] = {}
USER_RESUMES: Dict[str, List[Dict[str, Any]]] = {}
USER_CERTIFICATES: Dict[str, List[Dict[str, Any]]] = {}
USER_TEST_SCORES: Dict[str, List[Dict[str, Any]]] = {}
USER_QUIZZES: Dict[str, List[Dict[str, Any]]] = {}
QUIZ_QUESTIONS: Dict[int, List[Dict[str, Any]]] = {}
QUIZ_ATTEMPTS: Dict[int, Dict[str, Any]] = {}
QUIZ_ID_COUNTER = count(1)
QUIZ_QUESTION_ID_COUNTER = count(1)
QUIZ_ATTEMPT_ID_COUNTER = count(1)
FILLER_WORDS = {"um", "uh", "like", "you know", "so"}


def _flatten_questions() -> List[Dict[str, Any]]:

    items: List[Dict[str, Any]] = []
    for questions in QUESTION_BANK.values():
        items.extend(questions)
    return items


def _normalize_quiz_text(value: Optional[str]) -> str:
    return (value or "").strip().lower()


def _filter_quiz_candidates(subject: str, topic: Optional[str], difficulty: str) -> List[Dict[str, Any]]:
    all_questions = _flatten_questions()
    requested_difficulty = _normalize_quiz_text(difficulty)
    subject_key = _normalize_quiz_text(subject)
    topic_key = _normalize_quiz_text(topic)

    filtered = all_questions
    if requested_difficulty in {"easy", "medium", "hard"}:
        filtered = [q for q in filtered if _normalize_quiz_text(q.get("difficulty")) == requested_difficulty]

    if subject_key or topic_key:
        token = f"{subject_key} {topic_key}".strip()
        token_parts = [piece for piece in token.split() if piece]

        def _matches(question: Dict[str, Any]) -> bool:
            searchable = " ".join(
                [
                    _normalize_quiz_text(question.get("title")),
                    _normalize_quiz_text(question.get("description")),
                    _normalize_quiz_text(question.get("source")),
                    " ".join(_normalize_quiz_text(tag) for tag in question.get("tags", []) or []),
                    " ".join(_normalize_quiz_text(company) for company in question.get("companies", []) or []),
                ]
            )
            if subject_key and subject_key in searchable:
                return True
            if topic_key and topic_key in searchable:
                return True
            return any(part in searchable for part in token_parts)

        matched = [q for q in filtered if _matches(q)]
        if matched:
            return matched

    if filtered:
        return filtered
    return all_questions


def _build_mcq_from_question(raw_question: Dict[str, Any], quiz_id: int, question_order: int) -> Dict[str, Any]:
    tags = [str(tag).strip() for tag in raw_question.get("tags", []) if str(tag).strip()]
    source = str(raw_question.get("source") or "general").strip().title()
    title = str(raw_question.get("title") or "Interview Question").strip()

    if tags:
        correct_answer = tags[0].title()
        distractors = [
            tags[1].title() if len(tags) > 1 else "Time complexity",
            source,
            "Edge cases",
        ]
        prompt = f"Which concept is most central to this topic: {title}?"
    else:
        correct_answer = str(raw_question.get("difficulty") or "medium").title()
        distractors = ["Easy", "Medium", "Hard"]
        prompt = f"What is the difficulty level for this problem: {title}?"

    options = [correct_answer] + [item for item in distractors if item != correct_answer]
    deduped: List[str] = []
    for option in options:
        if option not in deduped:
            deduped.append(option)
    random.shuffle(deduped)

    return {
        "id": next(QUIZ_QUESTION_ID_COUNTER),
        "quiz_id": quiz_id,
        "question_text": prompt,
        "question_type": "mcq",
        "options": deduped,
        "points": 1,
        "topic_tags": tags,
        "question_order": question_order,
        "_correct_answer": correct_answer,
    }


def _get_user_quiz_or_404(user_id: str, quiz_id: int) -> Dict[str, Any]:
    quizzes = USER_QUIZZES.get(user_id, [])
    for quiz in quizzes:
        if quiz["id"] == quiz_id:
            return quiz
    raise HTTPException(status_code=404, detail="Quiz not found")


def _sanitize_quiz_questions(quiz_id: int) -> List[Dict[str, Any]]:
    questions = QUIZ_QUESTIONS.get(quiz_id, [])
    return [
        {
            "id": question["id"],
            "quiz_id": question["quiz_id"],
            "question_text": question["question_text"],
            "question_type": question["question_type"],
            "options": question.get("options"),
            "points": question.get("points", 1),
            "topic_tags": question.get("topic_tags"),
            "question_order": question.get("question_order", 1),
        }
        for question in questions
    ]


def _match_company_key(name: str) -> Optional[str]:
    key = name.lower()
    if key in COMPANY_DATA:
        return key
    for candidate in COMPANY_DATA:
        if candidate.replace(" ", "") == key.replace(" ", ""):
            return candidate
    return None


def _resolve_subject(subject: str) -> Optional[str]:
    key = subject.lower()
    for name in QUESTION_BANK:
        if name.lower() == key:
            return name
    return None


def _calculate_progress_stats() -> Dict[str, Any]:
    total_problems = sum(item["problems_solved"] for item in PROGRESS_HISTORY)
    total_tests = sum(item["tests_taken"] for item in PROGRESS_HISTORY)
    total_interviews = sum(item["interviews_completed"] for item in PROGRESS_HISTORY)
    total_minutes = sum(item["time_spent_minutes"] for item in PROGRESS_HISTORY)
    current_streak = PROGRESS_HISTORY[-1]["current_streak"] if PROGRESS_HISTORY else 0
    longest_streak = max((item["longest_streak"] for item in PROGRESS_HISTORY), default=0)
    avg_score = round(sum(score["percentage"] for score in TEST_SCORES) / len(TEST_SCORES), 2) if TEST_SCORES else 0
    return {
        "total_problems_solved": total_problems,
        "total_tests_taken": total_tests,
        "total_interviews": total_interviews,
        "current_streak": current_streak,
        "longest_streak": longest_streak,
        "total_time_spent_hours": round(total_minutes / 60, 2),
        "achievements_earned": len(ACHIEVEMENTS),
        "avg_test_score": avg_score,
    }


def _select_questions(
    interview_type: Optional[str],
    difficulty: Optional[str],
    count_questions: int,
) -> List[Dict[str, Any]]:
    normalized_type = (interview_type or "").lower()
    topic_keys = INTERVIEW_TYPE_TOPIC_MAP.get(normalized_type)
    if not topic_keys:
        topic_keys = list(QUESTION_BANK.keys())

    pool: List[Dict[str, Any]] = []
    for topic in topic_keys:
        pool.extend(QUESTION_BANK.get(topic, []))

    if not pool:
        pool = _flatten_questions()

    if difficulty:
        filtered = [q for q in pool if q["difficulty"].lower() == difficulty.lower()]
        pool = filtered or pool

    if len(pool) < count_questions:
        pool = _flatten_questions()

    rng = random.Random()
    return rng.sample(pool, k=min(count_questions, len(pool)))


def _evaluate_answer(question: Dict[str, Any], answer: str) -> Dict[str, Any]:
    tokens = answer.split()
    word_count = len(tokens)
    answer_lower = answer.lower()
    has_examples = any(keyword in answer_lower for keyword in ["for example", "for instance", "e.g."])
    structured = any(keyword in answer_lower for keyword in ["first", "second", "finally", "approach", "star"])
    default_follow_ups = [
        f"How would you handle edge cases for {question['title'].lower()}?",
        "What optimizations could improve your solution?",
    ]

    answer_key = ANSWER_KEYS.get(question.get("id"))
    if answer_key:
        concepts = answer_key.get("concepts", [])
        matched: List[str] = []
        missing: List[str] = []
        for concept in concepts:
            keywords = [kw.lower() for kw in concept.get("keywords", [])]
            if keywords and any(keyword in answer_lower for keyword in keywords):
                matched.append(concept["label"])
            else:
                missing.append(concept["label"])

        total = len(concepts)
        coverage_ratio = len(matched) / total if total else 0.0
        threshold = answer_key.get("passing_threshold", 0.6)
        is_correct = coverage_ratio >= threshold

        technical_accuracy = int(55 + coverage_ratio * 45)
        completeness = int(50 + coverage_ratio * 50)
        clarity = min(100, 60 + word_count // 2)

        feedback_parts = []
        if is_correct:
            feedback_parts.append("Great job covering the critical elements.")
        if missing:
            feedback_parts.append(f"Add detail on: {', '.join(missing[:2])}.")
        if not structured:
            feedback_parts.append("Consider announcing the structure before diving into details.")
        if not has_examples and question.get("id", "").startswith("beh"):
            feedback_parts.append("Ground the story with concrete metrics or impact.")
        feedback = " ".join(part for part in feedback_parts if part).strip() or "Keep iterating on your story."

        follow_ups = answer_key.get("follow_ups") or default_follow_ups

        return {
            "question": question["title"],
            "answer": answer,
            "technical_accuracy": min(100, technical_accuracy),
            "completeness": min(100, completeness),
            "clarity": clarity,
            "has_real_world_examples": has_examples,
            "has_structured_approach": structured,
            "feedback": feedback,
            "follow_up_questions": follow_ups,
            "matched_concepts": matched,
            "missing_concepts": missing,
            "coverage_ratio": coverage_ratio,
            "is_correct": is_correct,
            "reference_answer": answer_key.get("sample_answer"),
            "expected_complexity": answer_key.get("complexity"),
        }

    completeness = min(100, max(40, word_count))
    technical_accuracy = min(100, 60 + word_count // 2)
    clarity = min(100, 55 + word_count // 3)
    coverage_ratio = min(1.0, word_count / 120) if word_count else 0.0
    is_correct = technical_accuracy >= 70
    feedback = "Solid structure, expand on trade-offs." if structured else "Add more structure and concrete examples."

    return {
        "question": question["title"],
        "answer": answer,
        "technical_accuracy": technical_accuracy,
        "completeness": completeness,
        "clarity": clarity,
        "has_real_world_examples": has_examples,
        "has_structured_approach": structured,
        "feedback": feedback,
        "follow_up_questions": default_follow_ups,
        "matched_concepts": [],
        "missing_concepts": [],
        "coverage_ratio": coverage_ratio,
        "is_correct": is_correct,
        "reference_answer": None,
        "expected_complexity": None,
    }


def _compute_speech_analysis(answer: str, duration: Optional[float]) -> Dict[str, Any]:
    tokens = answer.split()
    estimated_seconds = duration if duration else max(len(tokens) / 2.0, 30.0)
    duration_minutes = estimated_seconds / 60
    speech_rate = int(len(tokens) / max(duration_minutes, 1e-3))
    filler_hits = [word for word in tokens if word.lower() in FILLER_WORDS]
    confidence = max(40, 95 - len(filler_hits) * 3)
    return {
        "word_count": len(tokens),
        "filler_word_count": len(filler_hits),
        "filler_words_found": filler_hits,
        "speech_rate_wpm": speech_rate,
        "pause_count": max(0, len(filler_hits) // 2),
        "confidence_score": confidence,
    }


def _build_interview_report(session: Dict[str, Any]) -> Dict[str, Any]:
    responses = session.get("responses", [])
    total_questions = len(session.get("questions", []))
    answered = len(responses)
    duration = session.get("duration_minutes", 30)
    overall_score = int(sum(r["technical_accuracy"] for r in responses) / max(1, answered))
    correct_answers = sum(1 for r in responses if r.get("is_correct"))
    confidence_trend = "increasing" if answered > 1 and responses[-1]["clarity"] >= responses[0]["clarity"] else "stable"
    coverage_ratio = correct_answers / max(1, answered)
    strengths = ["Strong coverage of key concepts"] if coverage_ratio >= 0.6 else ["Clear communication"]
    weaknesses = ["Mention missing concepts earlier"] if coverage_ratio < 0.6 else ["Add more real-world examples"]
    question_perf = []
    for idx, (question, resp) in enumerate(zip(session.get("questions", []), responses), start=1):
        question_perf.append(
            {
                "question_number": idx,
                "question": question["title"],
                "difficulty": question["difficulty"],
                "score": resp["technical_accuracy"],
                "feedback": resp["feedback"],
                "is_correct": resp.get("is_correct", False),
                "missing_concepts": resp.get("missing_concepts", []),
            }
        )
    return {
        "session_id": session["session_id"],
        "candidate_name": session["candidate_name"],
        "target_role": session["target_role"],
        "interview_type": session["interview_type"],
        "persona_used": session["persona"],
        "duration_minutes": duration,
        "overall_score": overall_score,
        "technical_score": overall_score,
        "communication_score": int(overall_score * 0.9),
        "confidence_score": int(overall_score * 0.85),
        "body_language_score": 75,
        "total_questions": total_questions,
        "questions_answered": answered,
        "correct_answers": correct_answers,
        "average_response_time": round((duration * 60) / max(1, answered), 2),
        "total_filler_words": sum(len(_compute_speech_analysis(resp["answer"], None)["filler_words_found"]) for resp in responses),
        "speech_clarity": int(overall_score * 0.88),
        "average_speech_rate": 130,
        "strengths": strengths,
        "weaknesses": weaknesses,
        "improvement_areas": ["Provide more metrics", "Highlight impact"],
        "question_performance": question_perf,
        "recommended_topics": ["System design", "Dynamic programming"],
        "recommended_practice": ["Mock interview", "Whiteboard drills"],
        "detailed_feedback": "Great progression. Continue polishing trade-off discussions.",
        "confidence_trend": confidence_trend,
        "final_verdict": "Likely hire" if overall_score > 75 else "Needs work",
    }


@asynccontextmanager
async def lifespan(_: FastAPI):
    try:
        if _env_flag("ENABLE_MOCK_AUTH", default=False):
            logger.warning("Starting with ENABLE_MOCK_AUTH=true. Not recommended for production.")
        else:
            get_supabase_client()
            logger.info("Supabase client initialized during startup")
        yield
    except RuntimeError as exc:
        logger.error("Startup aborted: %s", exc)
        raise


app = FastAPI(
    title="Supabase Auth API",
    description="Login and sign-up endpoints backed by Supabase Auth",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_parse_origins(os.getenv("ALLOWED_ORIGINS")),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

@app.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    return HealthResponse(status="ok")


@app.post("/auth/signup", response_model=AuthResponse, tags=["auth"])
async def sign_up(request: SignUpRequest) -> AuthResponse:
    client = get_supabase_client()
    profile_metadata = dict(request.metadata or {})
    profile_metadata.update(
        {
            "github_username": request.github_username,
            "leetcode_username": request.leetcode_username,
        }
    )
    payload = {
        "email": request.email,
        "password": request.password,
        "options": {"data": profile_metadata},
    }
    try:
        result = await run_in_threadpool(client.auth.sign_up, payload)
    except Exception as exc:
        logger.exception("Supabase sign_up failed")
        raise HTTPException(status_code=400, detail="Unable to create account. Please try again.") from exc

    user = result.user
    session = result.session
    if user is None:
        raise HTTPException(status_code=502, detail="Supabase did not return a user record.")

    message = "Confirm your email to finish sign-up." if session is None else "Account created."
    try:
        await _persist_user_profile(client, user.id, request.email, profile_metadata)
    except Exception:
        logger.warning("Failed to upsert profile row for %s", request.email, exc_info=True)

    return AuthResponse(
        user_id=user.id,
        email=request.email,
        message=message,
        access_token=session.access_token if session else None,
        refresh_token=session.refresh_token if session else None,
    )


@app.post("/auth/login", response_model=AuthResponse, tags=["auth"])
async def login(request: LoginRequest) -> AuthResponse:
    client = get_supabase_client()
    payload = {"email": request.email, "password": request.password}
    try:
        result = await run_in_threadpool(client.auth.sign_in_with_password, payload)
    except Exception as exc:
        logger.warning("Login failed for %s", request.email)
        raise HTTPException(status_code=401, detail="Invalid email or password.") from exc

    session = result.session
    user = result.user
    if session is None or session.access_token is None or session.refresh_token is None:
        raise HTTPException(status_code=401, detail="Invalid email or password.")

    return AuthResponse(
        user_id=user.id if user else "unknown",
        email=request.email,
        message="Login successful.",
        access_token=session.access_token,
        refresh_token=session.refresh_token,
    )


@app.post("/auth/refresh", response_model=AuthResponse, tags=["auth"])
async def refresh_tokens(request: RefreshRequest) -> AuthResponse:
    client = get_supabase_client()
    try:
        session = await run_in_threadpool(client.auth.set_session, refresh_token=request.refresh_token)
    except Exception as exc:
        logger.warning("Refresh token exchange failed")
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token.") from exc

    if session is None or not session.access_token or not session.refresh_token:
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token.")

    try:
        user_response = await run_in_threadpool(client.auth.get_user, session.access_token)
    except Exception as exc:
        logger.error("Failed to fetch user during refresh", exc_info=True)
        raise HTTPException(status_code=502, detail="Unable to refresh session. Please log in again.") from exc

    user = getattr(user_response, "user", None)
    if user is None or not getattr(user, "email", None):
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token.")

    return AuthResponse(
        user_id=user.id,
        email=user.email,
        message="Token refreshed.",
        access_token=session.access_token,
        refresh_token=session.refresh_token,
    )


# ----------------------- Profile & Social APIs -----------------------


@app.get("/leetcode/{username}")
async def get_leetcode_profile(username: str) -> Dict[str, Any]:
    return await _fetch_leetcode_profile(username)


@app.get("/github/{username}")
async def get_github_profile(username: str) -> Dict[str, Any]:
    return await _fetch_github_profile(username)


@app.get("/codechef/{username}")
async def get_codechef_profile(username: str) -> Dict[str, Any]:
    return await _fetch_codechef_profile(username)


@app.get("/profile/{leetcode_username}/{github_username}")
async def get_combined_profile(leetcode_username: str, github_username: str) -> Dict[str, Any]:
    leetcode_profile = await _fetch_leetcode_profile(leetcode_username)
    github_profile = await _fetch_github_profile(github_username)
    return {
        "leetcode": leetcode_profile,
        "github": github_profile,
    }


# ----------------------- Questions APIs -----------------------


@app.get("/questions/subjects")
async def list_subjects() -> Dict[str, List[str]]:
    return {"subjects": list(QUESTION_BANK.keys())}


@app.get("/questions/search")
async def search_questions(
    query: str,
    subject: Optional[str] = None,
    difficulty: Optional[str] = None,
) -> Dict[str, List[Dict[str, Any]]]:
    text = query.lower()
    pool = _flatten_questions()
    if subject:
        resolved = _resolve_subject(subject)
        if resolved is None:
            raise HTTPException(status_code=404, detail="Subject not found")
        pool = QUESTION_BANK[resolved]
    if difficulty:
        pool = [q for q in pool if q["difficulty"].lower() == difficulty.lower()]
    matches = [q for q in pool if text in q["title"].lower() or text in q["description"].lower()]
    return {"questions": matches}


@app.get("/questions/random")
async def random_questions(count: int = Query(5, ge=1, le=10), difficulty: Optional[str] = None) -> Dict[str, List[Dict[str, Any]]]:
    pool = [q for q in _flatten_questions() if not difficulty or q["difficulty"].lower() == difficulty.lower()]
    rng = random.Random()
    selection = rng.sample(pool, k=min(count, len(pool))) if pool else []
    return {"questions": selection}


@app.get("/questions/{subject}")
async def get_questions_by_subject(
    subject: str,
    difficulty: Optional[str] = None,
    source: Optional[str] = None,
    limit: Optional[int] = Query(None, ge=1, le=50),
) -> Dict[str, List[Dict[str, Any]]]:
    resolved = _resolve_subject(subject)
    if resolved is None:
        raise HTTPException(status_code=404, detail="Subject not found")
    questions = QUESTION_BANK[resolved]
    if difficulty:
        questions = [q for q in questions if q["difficulty"].lower() == difficulty.lower()]
    if source:
        questions = [q for q in questions if q["source"].lower() == source.lower()]
    if limit is not None:
        questions = questions[:limit]
    return {"questions": questions}


# ----------------------- Companies APIs -----------------------


@app.get("/companies/list")
async def list_companies() -> Dict[str, List[Dict[str, Any]]]:
    companies = [
        {
            "name": data["name"],
            "description": data["description"],
            "headquarters": data["headquarters"],
            "industry": data["industry"],
            "founded": data["founded"],
            "employees": data["employees"],
            "website": data["website"],
        }
        for data in COMPANY_DATA.values()
    ]
    return {"companies": companies}


@app.get("/companies/search")
async def search_companies(query: str) -> Dict[str, List[Dict[str, Any]]]:
    text = query.lower()
    matches = [
        data
        for data in COMPANY_DATA.values()
        if text in data["name"].lower() or text in data["description"].lower()
    ]
    return {"companies": matches}


def _get_company_or_404(company_name: str) -> Dict[str, Any]:
    key = _match_company_key(company_name)
    if key is None:
        raise HTTPException(status_code=404, detail="Company not found")
    return COMPANY_DATA[key]


@app.get("/companies/{company_name}")
async def company_details(company_name: str) -> Dict[str, Any]:
    return _get_company_or_404(company_name)


@app.get("/companies/{company_name}/requirements")
async def company_requirements(company_name: str) -> Dict[str, Any]:
    company = _get_company_or_404(company_name)
    return company["requirements"]


@app.get("/companies/{company_name}/process")
async def company_process(company_name: str) -> Dict[str, Any]:
    company = _get_company_or_404(company_name)
    return company["process"]


@app.get("/companies/{company_name}/salary")
async def company_salary(company_name: str) -> Dict[str, Any]:
    company = _get_company_or_404(company_name)
    return company["salary"]


@app.get("/companies/{company_name}/preparation")
async def company_preparation(company_name: str) -> Dict[str, Any]:
    company = _get_company_or_404(company_name)
    return company["preparation"]


# ----------------------- Agent Automation APIs -----------------------


@app.get("/agents")
async def list_agents(current_user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    _ = current_user
    return {"agents": AGENT_CATALOG}


@app.get("/agents/runs")
async def list_agent_runs(
    limit: int = Query(10, ge=1, le=50),
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    _ = current_user
    runs = sorted(AGENT_RUNS.values(), key=lambda entry: entry["created_at"], reverse=True)
    return {"runs": runs[:limit]}


@app.get("/agents/runs/{run_id}")
async def get_agent_run(run_id: str, current_user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    _ = current_user
    entry = AGENT_RUNS.get(run_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Agent run not found")
    return entry


@app.post("/agents/run")
async def run_agent(request: AgentRunRequest, current_user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    _ = current_user
    definition = _get_agent_definition(request.agent_id)
    executor = AGENT_EXECUTORS.get(request.agent_id)
    if executor is None:
        raise HTTPException(status_code=501, detail="Agent executor not implemented")

    try:
        result = executor(request.inputs or {})
        status = "completed"
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Agent %s failed", request.agent_id)
        status = "failed"
        result = {"error": str(exc)}

    record = _store_agent_run(request.agent_id, request.inputs or {}, status, result)
    response = {"run_id": record["run_id"], "status": record["status"], "result": record["result"]}
    response["agent"] = {"id": definition["id"], "name": definition.get("name")}
    return response


# ----------------------- Resume & Certification APIs -----------------------


@app.post("/resume/upload")
async def upload_resume(
    file: UploadFile = File(...),
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    _ = current_user
    content = await file.read()
    resume_id = next(RESUME_ID_COUNTER)
    entry = {
        "id": resume_id,
        "filename": file.filename,
        "upload_date": _current_timestamp(),
        "size_kb": round(len(content) / 1024, 2),
    }
    RESUMES.append(entry)
    return {**entry, "message": "Resume uploaded successfully"}


@app.post("/resume/{resume_id}/analyze")
async def analyze_resume(
    resume_id: int,
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    _ = current_user
    resume = next((item for item in RESUMES if item["id"] == resume_id), None)
    if resume is None:
        raise HTTPException(status_code=404, detail="Resume not found")
    summary = {
        "id": resume_id,
        "filename": resume["filename"],
        "message": "Resume analyzed successfully",
        "keywords_detected": ["Python", "System Design", "Leadership"],
        "score": 82,
        "recommendations": [
            "Add quantifiable metrics to recent roles",
            "Highlight impact of cross-team projects",
        ],
    }
    resume["analysis"] = summary
    return summary


@app.get("/resume/list")
async def list_resumes(current_user: Dict[str, Any] = Depends(get_current_user)) -> List[Dict[str, Any]]:
    _ = current_user
    return RESUMES


@app.post("/certifications")
async def upload_certificate(
    file: UploadFile = File(...),
    name: str = Form(...),
    issuing_organization: str = Form(...),
    issue_date: str = Form(...),
    credential_id: Optional[str] = Form(None),
    credential_url: Optional[str] = Form(None),
    expiry_date: Optional[str] = Form(None),
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    _ = current_user
    await file.read()
    cert_id = next(CERTIFICATE_ID_COUNTER)
    entry = {
        "id": cert_id,
        "name": name,
        "issuing_organization": issuing_organization,
        "issue_date": issue_date,
        "credential_id": credential_id,
        "credential_url": credential_url,
        "expiry_date": expiry_date,
        "message": "Certificate stored",
    }
    CERTIFICATIONS.append(entry)
    return entry


@app.get("/certifications")
async def list_certificates(current_user: Dict[str, Any] = Depends(get_current_user)) -> List[Dict[str, Any]]:
    _ = current_user
    return CERTIFICATIONS


# ----------------------- Interview APIs -----------------------


def _get_session_or_404(session_id: str) -> Dict[str, Any]:
    session = INTERVIEW_SESSIONS.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Interview session not found")
    return session


@app.get("/interview/personas")
async def list_personas() -> Dict[str, Any]:
    return {"personas": INTERVIEW_PERSONAS}


@app.post("/interview/start")
async def start_interview(
    request: InterviewStartRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    _ = current_user
    persona = next((p for p in INTERVIEW_PERSONAS if p["persona_id"] == request.persona), None)
    if persona is None:
        raise HTTPException(status_code=404, detail="Persona not found")
    session_id = str(uuid4())
    questions = _select_questions(request.interview_type, request.difficulty, count_questions=5)
    if not questions:
        raise HTTPException(status_code=500, detail="No questions available")
    start_time = _current_timestamp()
    session_data = {
        "session_id": session_id,
        "persona": request.persona,
        "candidate_name": request.candidate_name,
        "target_role": request.target_role,
        "interview_type": request.interview_type,
        "difficulty": request.difficulty,
        "duration_minutes": request.duration_minutes,
        "questions": questions,
        "current_index": 0,
        "responses": [],
        "status": "active",
        "start_time": start_time,
        "end_time": None,
        "questions_answered": 0,
        "company_context": request.company_context,
        "interviewer": persona,
    }
    INTERVIEW_SESSIONS[session_id] = session_data
    current_question = questions[0]
    return {
        "session_id": session_id,
        "persona": request.persona,
        "question_count": len(questions),
        "current_question_number": 1,
        "current_question": current_question["title"],
        "current_question_text": current_question.get("description"),
        "current_question_id": current_question.get("id"),
        "current_question_difficulty": current_question.get("difficulty"),
        "total_questions": len(questions),
        "difficulty": request.difficulty,
        "start_time": start_time,
        "interviewer": {
            "id": persona["persona_id"],
            "name": persona["name"],
            "tone": persona.get("tone"),
            "style": persona.get("style"),
            "intro_message": persona.get("intro_message"),
        },
    }


@app.post("/interview/{session_id}/answer")
async def submit_answer(
    session_id: str,
    answer: str = Query(..., min_length=1),
    audio_duration: Optional[float] = Query(None, ge=0),
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    _ = current_user
    session = _get_session_or_404(session_id)
    if session["status"] == "completed":
        raise HTTPException(status_code=400, detail="Interview session already completed")
    question = session["questions"][session["current_index"]]
    evaluation = _evaluate_answer(question, answer)
    speech = _compute_speech_analysis(answer, audio_duration)
    session["responses"].append(evaluation)
    session["current_index"] += 1
    session["questions_answered"] = len(session["responses"])
    done = session["current_index"] >= len(session["questions"])
    if done:
        session["status"] = "completed"
        session["end_time"] = _current_timestamp()
    next_question = None
    if not done:
        nxt = session["questions"][session["current_index"]]
        next_question = {
            "question_id": nxt["id"],
            "question": nxt["title"],
            "difficulty": nxt["difficulty"],
            "question_text": nxt.get("description"),
        }
    return {
        "evaluation": evaluation,
        "question_number": session["questions_answered"],
        "total_questions_asked": len(session["questions"]),
        "speech_analysis": {
            "filler_word_count": speech["filler_word_count"],
            "filler_words": speech["filler_words_found"],
            "word_count": speech["word_count"],
            "speech_rate_wpm": speech["speech_rate_wpm"],
            "confidence_score": speech["confidence_score"],
            "feedback": "Great pacing" if speech["filler_word_count"] < 3 else "Reduce filler words for clarity",
        },
        "next_question": next_question,
        "status": session["status"],
        "message": "Session completed" if done else "Answer recorded",
    }


@app.get("/interview/{session_id}/status")
async def interview_status(
    session_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    _ = current_user
    session = _get_session_or_404(session_id)
    return {
        "session_id": session_id,
        "status": session["status"],
        "candidate_name": session["candidate_name"],
        "target_role": session["target_role"],
        "interview_type": session["interview_type"],
        "persona": session["persona"],
        "questions_asked": session["questions_answered"],
        "questions_answered": session["questions_answered"],
        "current_question_index": min(session["current_index"], len(session["questions"])),
        "start_time": session["start_time"],
        "end_time": session.get("end_time"),
    }


@app.get("/interview/{session_id}/report")
async def interview_report(
    session_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    _ = current_user
    session = _get_session_or_404(session_id)
    return _build_interview_report(session)


@app.delete("/interview/{session_id}")
async def delete_interview(
    session_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, str]:
    _ = current_user
    _get_session_or_404(session_id)
    INTERVIEW_SESSIONS.pop(session_id, None)
    return {"message": "Interview session deleted"}


@app.get("/interview/sessions/active")
async def active_sessions(current_user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    _ = current_user
    sessions = [
        {
            "session_id": session_id,
            "candidate_name": data["candidate_name"],
            "target_role": data["target_role"],
            "status": data["status"],
            "questions_answered": data["questions_answered"],
            "start_time": data["start_time"],
        }
        for session_id, data in INTERVIEW_SESSIONS.items()
        if data["status"] != "completed"
    ]
    return {"total_sessions": len(sessions), "sessions": sessions}


@app.post("/interview/analyze-speech")
async def analyze_speech(
    text: str = Query(..., min_length=10),
    duration_seconds: float = Query(60.0, gt=0),
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    _ = current_user
    analysis = _compute_speech_analysis(text, duration_seconds)
    rating = "excellent" if analysis["confidence_score"] >= 85 else "good" if analysis["confidence_score"] >= 70 else "average"
    recommendations = [
        "Pause briefly between sections",
        "Swap filler words with intentional silence",
        "Summarize key points before concluding",
    ]
    return {
        "speech_analysis": analysis,
        "recommendations": recommendations,
        "overall_rating": rating,
    }


# ----------------------- Quiz APIs -----------------------

@app.get("/quiz/list")
async def list_quizzes(
    limit: int = Query(50, ge=1, le=100),
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> List[Dict[str, Any]]:
    user_id = current_user["id"]
    quizzes = USER_QUIZZES.get(user_id, [])
    ordered = sorted(quizzes, key=lambda quiz: quiz.get("created_at", ""), reverse=True)
    return ordered[:limit]


@app.post("/quiz/generate")
async def generate_quiz(
    request: QuizGenerateRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    user_id = current_user["id"]
    subject = request.subject.strip()
    if not subject:
        raise HTTPException(status_code=400, detail="Subject is required")

    search_query = " ".join(part for part in [subject, request.topic or ""] if part).strip()
    scraped_candidates = await _scrape_quiz_candidates_from_interview_sites(search_query)
    for candidate in scraped_candidates:
        candidate["difficulty"] = request.difficulty.lower()

    candidates = scraped_candidates or _filter_quiz_candidates(subject, request.topic, request.difficulty)
    if not candidates:
        raise HTTPException(status_code=404, detail="No questions available to generate a quiz")

    selected: List[Dict[str, Any]] = []
    while len(selected) < request.num_questions:
        selected.append(random.choice(candidates))

    quiz_id = next(QUIZ_ID_COUNTER)
    quiz_title = f"{subject.title()} Quiz"
    quiz_description = (
        f"AI-generated quiz for {subject}" if not request.topic else f"AI-generated quiz for {subject} ({request.topic})"
    )
    created_at = _current_timestamp()
    quiz_record = {
        "id": quiz_id,
        "title": quiz_title,
        "description": quiz_description,
        "subject": subject,
        "difficulty_level": request.difficulty.lower(),
        "total_questions": request.num_questions,
        "time_limit_minutes": max(5, request.num_questions * 2),
        "quiz_type": request.quiz_type,
        "content_source": "web_scraped" if scraped_candidates else "internal_bank",
        "created_at": created_at,
    }

    if user_id not in USER_QUIZZES:
        USER_QUIZZES[user_id] = []
    USER_QUIZZES[user_id].append(quiz_record)

    QUIZ_QUESTIONS[quiz_id] = [
        _build_mcq_from_question(raw_question, quiz_id=quiz_id, question_order=index)
        for index, raw_question in enumerate(selected, start=1)
    ]

    return quiz_record


@app.get("/quiz/{quiz_id}")
async def get_quiz(
    quiz_id: int,
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    user_id = current_user["id"]
    quiz = _get_user_quiz_or_404(user_id, quiz_id)
    return {
        **quiz,
        "questions": _sanitize_quiz_questions(quiz_id),
    }


@app.post("/quiz/attempt/start")
async def start_quiz_attempt(
    request: QuizAttemptStartRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    user_id = current_user["id"]
    _get_user_quiz_or_404(user_id, request.quiz_id)

    attempt_id = next(QUIZ_ATTEMPT_ID_COUNTER)
    started_at = _utcnow()
    QUIZ_ATTEMPTS[attempt_id] = {
        "id": attempt_id,
        "quiz_id": request.quiz_id,
        "user_id": user_id,
        "started_at": started_at,
        "submitted_at": None,
        "status": "in_progress",
    }

    return {
        "id": attempt_id,
        "quiz_id": request.quiz_id,
        "status": "in_progress",
        "started_at": _isoformat(started_at),
    }


@app.post("/quiz/attempt/submit")
async def submit_quiz_attempt(
    request: QuizAttemptSubmitRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    user_id = current_user["id"]
    attempt = QUIZ_ATTEMPTS.get(request.attempt_id)
    if not attempt or attempt.get("user_id") != user_id:
        raise HTTPException(status_code=404, detail="Quiz attempt not found")
    if attempt.get("status") == "submitted":
        raise HTTPException(status_code=400, detail="Quiz attempt already submitted")

    quiz = _get_user_quiz_or_404(user_id, int(attempt["quiz_id"]))
    questions = QUIZ_QUESTIONS.get(int(attempt["quiz_id"]), [])
    if not questions:
        raise HTTPException(status_code=400, detail="Quiz has no questions")

    answer_map: Dict[int, List[str]] = {entry.question_id: entry.user_answer for entry in request.answers}
    total_questions = len(questions)
    max_score = sum(int(question.get("points", 1)) for question in questions)
    score = 0
    attempted = 0
    correct = 0
    wrong = 0
    skipped = 0
    weak_topics: List[str] = []
    strong_topics: List[str] = []

    for question in questions:
        selected_options = answer_map.get(int(question["id"]), [])
        selected_answer = selected_options[0] if selected_options else None
        if not selected_answer:
            skipped += 1
            continue

        attempted += 1
        if selected_answer == question.get("_correct_answer"):
            correct += 1
            score += int(question.get("points", 1))
            for tag in question.get("topic_tags", []) or []:
                if tag not in strong_topics:
                    strong_topics.append(tag)
        else:
            wrong += 1
            for tag in question.get("topic_tags", []) or []:
                if tag not in weak_topics:
                    weak_topics.append(tag)

    percentage = (float(score) / float(max_score) * 100.0) if max_score else 0.0
    passed = percentage >= 60.0
    submitted_at = _utcnow()
    started_at = attempt.get("started_at")
    duration_minutes = 0.0
    if isinstance(started_at, datetime):
        duration_minutes = max((submitted_at - started_at).total_seconds() / 60.0, 0.1)

    attempt["status"] = "submitted"
    attempt["submitted_at"] = submitted_at

    feedback = (
        "Great work. Your fundamentals look solid."
        if passed
        else "Keep practicing and review the recommended topics before your next attempt."
    )

    return {
        "attempt_id": request.attempt_id,
        "quiz_title": quiz["title"],
        "total_questions": total_questions,
        "questions_attempted": attempted,
        "correct_answers": correct,
        "wrong_answers": wrong,
        "skipped_questions": skipped,
        "total_score": score,
        "max_score": max_score,
        "percentage": round(percentage, 2),
        "passed": passed,
        "time_taken_minutes": round(duration_minutes, 2),
        "ai_feedback": feedback,
        "strengths": strong_topics[:5],
        "weaknesses": weak_topics[:5],
        "recommended_topics": weak_topics[:5],
    }


# ----------------------- WebSocket Endpoint -----------------------

@app.websocket("/ws/{client_id}")
async def websocket_endpoint(websocket: WebSocket, client_id: str):
    logger.info(f"WebSocket connection attempt for client: {client_id}")
    try:
        await manager.connect(websocket, client_id)
        logger.info(f"WebSocket connected successfully for client: {client_id}")
        
        # Send a welcome message
        await manager.send_personal_message({
            "type": "connection_established",
            "message": "WebSocket connection established",
            "client_id": client_id
        }, client_id)
        
        while True:
            try:
                data = await websocket.receive_text()
                message = json.loads(data)
                logger.info(f"Received WebSocket message from {client_id}: {message}")
                # Echo back for now, can be extended for different message types
                await manager.send_personal_message({"message": f"Echo: {message}"}, client_id)
            except json.JSONDecodeError:
                logger.warning(f"Invalid JSON received from client {client_id}")
                await manager.send_personal_message({"error": "Invalid JSON format"}, client_id)
                
    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected for client: {client_id}")
        manager.disconnect(websocket, client_id)
    except Exception as e:
        logger.error(f"WebSocket error for client {client_id}: {e}")
        manager.disconnect(websocket, client_id)


# ----------------------- Learning Management APIs -----------------------

def _get_or_init_user_data(user_id: str, storage_dict: Dict[str, Any], default_factory):
    if user_id not in storage_dict:
        storage_dict[user_id] = default_factory()
    return storage_dict[user_id]


def _generate_sample_recommendations(user_id: str) -> List[Dict[str, Any]]:
    sample_recommendations = [
        {
            "id": 1,
            "user_id": user_id,
            "title": "Master Dynamic Programming",
            "description": "Focus on dynamic programming patterns to improve problem-solving skills",
            "category": "skill",
            "priority": "high",
            "source": "ai_analysis",
            "resources": [
                {"title": "DP Patterns Guide", "url": "https://leetcode.com/discuss/study-guide/458695"},
                {"title": "Dynamic Programming Course", "url": "https://www.coursera.org/learn/dynamic-programming"}
            ],
            "estimated_time": "2-3 weeks",
            "status": "pending",
            "created_at": _current_timestamp(),
        },
        {
            "id": 2,
            "user_id": user_id,
            "title": "System Design Fundamentals",
            "description": "Learn scalable system design concepts for senior-level interviews",
            "category": "course",
            "priority": "medium",
            "source": "ai_analysis",
            "resources": [
                {"title": "System Design Primer", "url": "https://github.com/donnemartin/system-design-primer"},
                {"title": "Designing Data-Intensive Applications", "url": "https://dataintensive.net/"}
            ],
            "estimated_time": "4-6 weeks",
            "status": "pending",
            "created_at": _current_timestamp(),
        },
        {
            "id": 3,
            "user_id": user_id,
            "title": "Mock Interview Practice",
            "description": "Practice behavioral and technical interviews with AI feedback",
            "category": "practice",
            "priority": "high",
            "source": "ai_analysis",
            "resources": [
                {"title": "Behavioral Interview Guide", "url": "https://www.pramp.com/behavioral"},
                {"title": "Technical Interview Prep", "url": "https://interviewing.io/"}
            ],
            "estimated_time": "1-2 weeks",
            "status": "pending",
            "created_at": _current_timestamp(),
        }
    ]
    return sample_recommendations


async def _simulate_ai_generation(user_id: str):
    """Simulate AI recommendation generation with real-time updates"""
    steps = [
        "Analyzing your profile...",
        "Gathering learning data...", 
        "Processing skill gaps...",
        "Generating recommendations...",
        "Finalizing suggestions..."
    ]
    
    for i, step in enumerate(steps):
        await manager.send_personal_message({
            "type": "generation_progress",
            "step": step,
            "progress": int((i + 1) / len(steps) * 100)
        }, user_id)
        await asyncio.sleep(2)  # Simulate processing time
    
    # Generate recommendations
    recommendations = _generate_sample_recommendations(user_id)
    USER_RECOMMENDATIONS[user_id] = recommendations
    
    await manager.send_personal_message({
        "type": "generation_complete",
        "recommendations": recommendations
    }, user_id)


@app.get("/topics/{topic}/resources", response_model=TopicResourceResponse)
async def get_topic_resources_for_dropdown(
    topic: str,
    current_user: Dict[str, Any] = Depends(get_current_user)
) -> TopicResourceResponse:
    _ = current_user  # Ensure route remains authenticated for future personalization
    normalized_topic = _normalize_topic_key(topic)
    if not normalized_topic:
        raise HTTPException(status_code=400, detail="Topic is required.")

    resources = await _scrape_topic_resources(normalized_topic)
    if not resources:
        raise HTTPException(status_code=502, detail="Unable to fetch resources right now. Please try again.")

    return TopicResourceResponse(topic=normalized_topic, items=resources, fetched_at=_current_timestamp())


@app.get("/recommendations")
async def get_recommendations(
    status: Optional[str] = None,
    priority: Optional[str] = None,
    current_user: Dict[str, Any] = Depends(get_current_user)
) -> List[Dict[str, Any]]:
    user_id = current_user["id"]
    user_recs = _get_or_init_user_data(user_id, USER_RECOMMENDATIONS, list)
    
    # Filter by status and priority if provided
    filtered_recs = user_recs
    if status:
        filtered_recs = [r for r in filtered_recs if r.get("status") == status]
    if priority:
        filtered_recs = [r for r in filtered_recs if r.get("priority") == priority]
    
    return filtered_recs


@app.post("/recommendations/generate")
async def generate_recommendations(current_user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, str]:
    user_id = current_user["id"]
    
    # Start generation in background
    asyncio.create_task(_simulate_ai_generation(user_id))
    
    return {"message": "AI recommendation generation started. Check WebSocket for real-time updates."}


@app.put("/recommendations/{rec_id}/status")
async def update_recommendation_status(
    rec_id: int,
    status: str = Query(..., regex="^(pending|in_progress|completed|dismissed)$"),
    current_user: Dict[str, Any] = Depends(get_current_user)
) -> Dict[str, str]:
    user_id = current_user["id"]
    user_recs = _get_or_init_user_data(user_id, USER_RECOMMENDATIONS, list)
    
    for rec in user_recs:
        if rec["id"] == rec_id:
            rec["status"] = status
            if status == "completed":
                rec["completed_at"] = _current_timestamp()
            
            # Send real-time update
            await manager.send_personal_message({
                "type": "recommendation_updated",
                "recommendation": rec
            }, user_id)
            
            return {"message": f"Recommendation {rec_id} status updated to {status}"}
    
    raise HTTPException(status_code=404, detail="Recommendation not found")


@app.get("/progress/stats")
async def get_progress_stats(current_user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    user_id = current_user["id"]
    
    # Generate sample stats if not exists
    if user_id not in USER_PROGRESS_STATS:
        USER_PROGRESS_STATS[user_id] = {
            "total_problems_solved": random.randint(50, 200),
            "total_tests_taken": random.randint(10, 50),
            "total_interviews": random.randint(5, 25),
            "current_streak": random.randint(0, 15),
            "longest_streak": random.randint(5, 30),
            "total_time_spent_hours": random.randint(50, 500),
            "achievements_earned": random.randint(3, 15),
            "avg_test_score": round(random.uniform(60.0, 95.0), 1),
        }
    
    return USER_PROGRESS_STATS[user_id]


@app.get("/progress/history")
async def get_progress_history(
    days: int = Query(30, ge=1, le=365),
    current_user: Dict[str, Any] = Depends(get_current_user)
) -> List[Dict[str, Any]]:
    user_id = current_user["id"]
    
    # Generate sample history if not exists
    if user_id not in USER_PROGRESS_HISTORY:
        history = []
        base_date = datetime.now(UTC) - timedelta(days=days)
        
        for i in range(days):
            date = base_date + timedelta(days=i)
            history.append({
                "id": i + 1,
                "user_id": user_id,
                "date": date.isoformat(),
                "problems_solved": random.randint(0, 8),
                "tests_taken": random.randint(0, 3),
                "interviews_completed": random.randint(0, 2),
                "time_spent_minutes": random.randint(0, 180),
                "skills_practiced": random.sample(["algorithms", "data_structures", "system_design", "behavioral"], k=random.randint(1, 3)),
                "current_streak": random.randint(0, 10),
                "longest_streak": random.randint(5, 20),
            })
        
        USER_PROGRESS_HISTORY[user_id] = history
    
    return USER_PROGRESS_HISTORY[user_id][-days:]


@app.get("/achievements")
async def get_achievements(current_user: Dict[str, Any] = Depends(get_current_user)) -> List[Dict[str, Any]]:
    user_id = current_user["id"]
    
    # Generate sample achievements if not exists
    if user_id not in USER_ACHIEVEMENTS:
        USER_ACHIEVEMENTS[user_id] = [
            {
                "id": 1,
                "user_id": user_id,
                "title": "Problem Solver",
                "description": "Solved 50 coding problems",
                "badge_icon": "🏆",
                "earned_date": _current_timestamp(),
                "category": "coding",
                "points": 100,
            },
            {
                "id": 2,
                "user_id": user_id,
                "title": "Interview Ready",
                "description": "Completed 10 mock interviews",
                "badge_icon": "🎯",
                "earned_date": _current_timestamp(),
                "category": "interview",
                "points": 150,
            },
            {
                "id": 3,
                "user_id": user_id,
                "title": "Consistent Learner",
                "description": "Maintained 7-day learning streak",
                "badge_icon": "🔥",
                "earned_date": _current_timestamp(),
                "category": "consistency",
                "points": 75,
            }
        ]
    
    return USER_ACHIEVEMENTS[user_id]


@app.get("/dashboard/overview")
async def get_dashboard_overview(current_user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    user_id = current_user["id"]
    
    # Get data from other endpoints
    progress_stats = await get_progress_stats(current_user)
    recommendations = await get_recommendations(current_user=current_user)
    
    # Get or generate sample data for other sections
    resumes = _get_or_init_user_data(user_id, USER_RESUMES, list)
    certificates = _get_or_init_user_data(user_id, USER_CERTIFICATES, list)
    test_scores = _get_or_init_user_data(user_id, USER_TEST_SCORES, list)
    
    return {
        "resumes": resumes,
        "test_scores": test_scores,
        "certifications": certificates,
        "recommendations": recommendations[:3],  
        "progress_stats": progress_stats,
    }
