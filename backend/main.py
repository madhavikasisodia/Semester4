import html
import logging
import os
import random
import re
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from itertools import count
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, quote_plus, unquote, urljoin, urlparse
from uuid import uuid4
import json
import asyncio
import tempfile
import xml.etree.ElementTree as ET

import httpx
from bs4 import BeautifulSoup
from fastapi import Body, Depends, File, FastAPI, Form, HTTPException, Header, Query, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator
from supabase import Client, create_client
from dotenv import load_dotenv
import pdfplumber

try:
    from rag_service import answer_with_rag
except Exception:
    answer_with_rag = None

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
        "id": "google-warmup",
        "name": "Google Interview Warmup",
        "domain": "grow.google",
        "seed_url": "https://grow.google/certificates/interview-warmup/",
    },
    {
        "id": "exponent",
        "name": "Exponent",
        "domain": "tryexponent.com",
        "seed_url": "https://www.tryexponent.com/questions",
    },
    {
        "id": "tech-interview-handbook",
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


class InterviewAnswerRequest(BaseModel):
    answer: str = Field(..., min_length=1)
    audio_duration: Optional[float] = Field(None, ge=0)


class AgentRunRequest(BaseModel):
    agent_id: str = Field(..., description="Identifier of the automation agent to execute")
    inputs: Dict[str, Any] = Field(default_factory=dict, description="Optional input payload for the agent")


class QuizGenerateRequest(BaseModel):
    subject: str = Field(..., min_length=1, max_length=100)
    topic: Optional[str] = Field(None, max_length=100)
    target_role: Optional[str] = Field(None, max_length=100)
    difficulty: str = Field("medium")
    num_questions: int = Field(10, ge=1, le=20)
    quiz_type: str = Field("mixed")
    source_mode: str = Field("auto")  # auto | web_only | internal_only
    scrape_source_ids: Optional[List[str]] = None


class QuizAttemptStartRequest(BaseModel):
    quiz_id: int


class QuizSubmissionAnswer(BaseModel):
    question_id: int
    user_answer: List[str] = Field(default_factory=list)
    time_taken_seconds: Optional[float] = None


class QuizAttemptSubmitRequest(BaseModel):
    attempt_id: int
    answers: List[QuizSubmissionAnswer] = Field(default_factory=list)


class SkillMatch(BaseModel):
    skill: str
    found_in_resume: bool
    importance: str = "medium"  # low, medium, high


class ResumeAnalysisResult(BaseModel):
    resume_id: int
    filename: str
    job_preference: Optional[str] = None
    overall_score: float
    match_percentage: float
    summary: str
    extracted_text_preview: str
    extracted_skills: List[str]
    matched_skills: List[SkillMatch]
    missing_skills: List[SkillMatch]
    experience_years: Optional[int] = None
    recommendations: List[str]
    strengths: List[str]
    analyzed_at: str


def _parse_origins(raw_origins: Optional[str]) -> List[str]:
    default_origins = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ]

    origins: List[str] = []

    for env_name in ("FRONTEND_URL", "BACKEND_URL"):
        value = os.getenv(env_name)
        if value:
            origins.extend(origin.strip() for origin in value.split(",") if origin.strip())

    if raw_origins:
        origins.extend(origin.strip() for origin in raw_origins.split(",") if origin.strip())
    else:
        origins.extend(default_origins)

    # Keep order stable while removing duplicates.
    return list(dict.fromkeys(origins))


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
USER_ACTIVITY_STATS_TABLE = "user_activity_stats"
USER_ACTIVITY_FIELDS = {
    "practice_interviews": "practice_interviews",
    "mock_tests": "mock_tests",
}
INTERVIEW_SESSIONS_TABLE = "interview_sessions"
USER_QUIZZES_TABLE = "user_quizzes"
QUIZ_ATTEMPTS_TABLE = "quiz_attempts"
LEARNING_ROADMAPS_TABLE = "user_learning_roadmaps"
USER_REMINDERS_TABLE = "user_reminders"


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


async def _increment_user_activity_count(user_id: str, metric: str) -> None:
    column = USER_ACTIVITY_FIELDS.get(metric)
    if not column:
        logger.warning("Unknown user activity metric requested: %s", metric)
        return

    client = get_supabase_client()
    now_iso = _current_timestamp()

    def _increment() -> None:
        # Read-then-write keeps implementation simple with Supabase table APIs.
        response = (
            client.table(USER_ACTIVITY_STATS_TABLE)
            .select("practice_interviews,mock_tests")
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
        rows = getattr(response, "data", None) or []

        if rows:
            existing = rows[0] or {}
            next_value = _safe_int(existing.get(column)) + 1
            (
                client.table(USER_ACTIVITY_STATS_TABLE)
                .update({column: next_value, "updated_at": now_iso})
                .eq("user_id", user_id)
                .execute()
            )
            return

        payload = {
            "user_id": user_id,
            "practice_interviews": 1 if column == "practice_interviews" else 0,
            "mock_tests": 1 if column == "mock_tests" else 0,
            "updated_at": now_iso,
        }
        client.table(USER_ACTIVITY_STATS_TABLE).insert(payload).execute()

    try:
        await run_in_threadpool(_increment)
    except Exception:
        logger.warning("Failed to persist user activity count for %s", user_id, exc_info=True)


async def _get_user_activity_stats(user_id: str) -> Dict[str, int]:
    client = get_supabase_client()

    def _fetch() -> Dict[str, int]:
        response = (
            client.table(USER_ACTIVITY_STATS_TABLE)
            .select("practice_interviews,mock_tests")
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
        rows = getattr(response, "data", None) or []
        if not rows:
            return {"practice_interviews": 0, "mock_tests": 0}
        row = rows[0] or {}
        return {
            "practice_interviews": _safe_int(row.get("practice_interviews")),
            "mock_tests": _safe_int(row.get("mock_tests")),
        }

    try:
        return await run_in_threadpool(_fetch)
    except Exception:
        logger.warning("Failed to fetch user activity stats for %s", user_id, exc_info=True)
        return {"practice_interviews": 0, "mock_tests": 0}


async def _persist_interview_session(user_id: str, session_data: Dict[str, Any]) -> None:
    client = get_supabase_client()
    payload = {
        "session_id": session_data["session_id"],
        "user_id": user_id,
        "status": session_data.get("status", "active"),
        "session_data": session_data,
        "start_time": session_data.get("start_time"),
        "end_time": session_data.get("end_time"),
        "updated_at": _current_timestamp(),
    }

    def _upsert() -> None:
        client.table(INTERVIEW_SESSIONS_TABLE).upsert(payload).execute()

    try:
        await run_in_threadpool(_upsert)
    except Exception:
        logger.warning("Failed to persist interview session %s", session_data.get("session_id"), exc_info=True)


async def _fetch_interview_session(user_id: str, session_id: str) -> Optional[Dict[str, Any]]:
    client = get_supabase_client()

    def _fetch() -> Optional[Dict[str, Any]]:
        response = (
            client.table(INTERVIEW_SESSIONS_TABLE)
            .select("session_data")
            .eq("session_id", session_id)
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
        rows = getattr(response, "data", None) or []
        if not rows:
            return None
        row = rows[0] or {}
        session_data = row.get("session_data")
        if isinstance(session_data, dict):
            return session_data
        return None

    try:
        return await run_in_threadpool(_fetch)
    except Exception:
        logger.warning("Failed to fetch interview session %s", session_id, exc_info=True)
        return None


async def _list_active_interview_sessions(user_id: str) -> List[Dict[str, Any]]:
    client = get_supabase_client()

    def _fetch() -> List[Dict[str, Any]]:
        response = (
            client.table(INTERVIEW_SESSIONS_TABLE)
            .select("session_data")
            .eq("user_id", user_id)
            .eq("status", "active")
            .execute()
        )
        rows = getattr(response, "data", None) or []
        sessions: List[Dict[str, Any]] = []
        for row in rows:
            payload = (row or {}).get("session_data")
            if isinstance(payload, dict):
                sessions.append(payload)
        return sessions

    try:
        return await run_in_threadpool(_fetch)
    except Exception:
        logger.warning("Failed to list active interview sessions for %s", user_id, exc_info=True)
        return []


async def _persist_quiz(user_id: str, quiz_record: Dict[str, Any], questions: List[Dict[str, Any]]) -> Optional[int]:
    client = get_supabase_client()
    payload = {
        "user_id": user_id,
        "quiz_data": {
            "quiz": quiz_record,
            "questions": questions,
        },
        "updated_at": _current_timestamp(),
    }

    def _insert() -> Optional[int]:
        response = (
            client.table(USER_QUIZZES_TABLE)
            .insert(payload)
            .execute()
        )
        rows = getattr(response, "data", None) or []
        if not rows:
            return None
        return _safe_int((rows[0] or {}).get("id"))

    try:
        return await run_in_threadpool(_insert)
    except Exception:
        logger.warning("Failed to persist quiz for %s", user_id, exc_info=True)
        return None


async def _fetch_user_quizzes(user_id: str, limit: int) -> List[Dict[str, Any]]:
    client = get_supabase_client()

    def _fetch() -> List[Dict[str, Any]]:
        response = (
            client.table(USER_QUIZZES_TABLE)
            .select("id,quiz_data,created_at")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        rows = getattr(response, "data", None) or []
        quizzes: List[Dict[str, Any]] = []
        for row in rows:
            record = row or {}
            quiz_data = record.get("quiz_data") or {}
            quiz = quiz_data.get("quiz") or {}
            if not isinstance(quiz, dict):
                continue
            quiz["id"] = _safe_int(record.get("id"))
            quiz["created_at"] = quiz.get("created_at") or record.get("created_at")
            quizzes.append(quiz)
        return quizzes

    try:
        return await run_in_threadpool(_fetch)
    except Exception:
        logger.warning("Failed to fetch quizzes for %s", user_id, exc_info=True)
        return []


async def _fetch_quiz_bundle(user_id: str, quiz_id: int) -> Optional[Dict[str, Any]]:
    client = get_supabase_client()

    def _fetch() -> Optional[Dict[str, Any]]:
        response = (
            client.table(USER_QUIZZES_TABLE)
            .select("id,quiz_data,created_at")
            .eq("id", quiz_id)
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
        rows = getattr(response, "data", None) or []
        if not rows:
            return None
        row = rows[0] or {}
        quiz_data = row.get("quiz_data") or {}
        if not isinstance(quiz_data, dict):
            return None
        return {
            "id": _safe_int(row.get("id")),
            "created_at": row.get("created_at"),
            "quiz": quiz_data.get("quiz") or {},
            "questions": quiz_data.get("questions") or [],
        }

    try:
        return await run_in_threadpool(_fetch)
    except Exception:
        logger.warning("Failed to fetch quiz bundle %s for %s", quiz_id, user_id, exc_info=True)
        return None


async def _create_quiz_attempt(user_id: str, quiz_id: int) -> Optional[Dict[str, Any]]:
    client = get_supabase_client()
    payload = {
        "user_id": user_id,
        "quiz_id": quiz_id,
        "status": "in_progress",
        "started_at": _current_timestamp(),
        "updated_at": _current_timestamp(),
    }

    def _insert() -> Optional[Dict[str, Any]]:
        response = client.table(QUIZ_ATTEMPTS_TABLE).insert(payload).execute()
        rows = getattr(response, "data", None) or []
        if not rows:
            return None
        row = rows[0] or {}
        return {
            "id": _safe_int(row.get("id")),
            "quiz_id": _safe_int(row.get("quiz_id")),
            "status": row.get("status") or "in_progress",
            "started_at": row.get("started_at") or payload["started_at"],
        }

    try:
        return await run_in_threadpool(_insert)
    except Exception:
        logger.warning("Failed to create quiz attempt for %s", user_id, exc_info=True)
        return None


async def _fetch_quiz_attempt(user_id: str, attempt_id: int) -> Optional[Dict[str, Any]]:
    client = get_supabase_client()

    def _fetch() -> Optional[Dict[str, Any]]:
        response = (
            client.table(QUIZ_ATTEMPTS_TABLE)
            .select("id,user_id,quiz_id,status,started_at,submitted_at,result_data")
            .eq("id", attempt_id)
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
        rows = getattr(response, "data", None) or []
        if not rows:
            return None
        return rows[0] or None

    try:
        return await run_in_threadpool(_fetch)
    except Exception:
        logger.warning("Failed to fetch quiz attempt %s", attempt_id, exc_info=True)
        return None


async def _submit_quiz_attempt_result(user_id: str, attempt_id: int, result: Dict[str, Any]) -> None:
    client = get_supabase_client()
    payload = {
        "status": "submitted",
        "submitted_at": _current_timestamp(),
        "result_data": result,
        "updated_at": _current_timestamp(),
    }

    def _update() -> None:
        (
            client.table(QUIZ_ATTEMPTS_TABLE)
            .update(payload)
            .eq("id", attempt_id)
            .eq("user_id", user_id)
            .execute()
        )

    try:
        await run_in_threadpool(_update)
    except Exception:
        logger.warning("Failed to persist quiz attempt result %s", attempt_id, exc_info=True)


async def _fetch_quiz_attempt_results(user_id: str, limit: int = 30) -> List[Dict[str, Any]]:
    client = get_supabase_client()

    def _fetch() -> List[Dict[str, Any]]:
        response = (
            client.table(QUIZ_ATTEMPTS_TABLE)
            .select("result_data,submitted_at")
            .eq("user_id", user_id)
            .eq("status", "submitted")
            .order("submitted_at", desc=True)
            .limit(limit)
            .execute()
        )
        rows = getattr(response, "data", None) or []
        values: List[Dict[str, Any]] = []
        for row in rows:
            payload = (row or {}).get("result_data")
            if isinstance(payload, dict):
                enriched_payload = dict(payload)
                submitted_at = (row or {}).get("submitted_at")
                if submitted_at:
                    enriched_payload["submitted_at"] = submitted_at
                values.append(enriched_payload)
        return values

    try:
        return await run_in_threadpool(_fetch)
    except Exception:
        logger.warning("Failed to fetch quiz attempt results for %s", user_id, exc_info=True)
        return []


def _build_user_learning_roadmap(user_id: str, quiz_results: List[Dict[str, Any]], activity: Dict[str, int]) -> Dict[str, Any]:
    weak_topic_counts: Dict[str, int] = {}
    for result in quiz_results:
        for topic in result.get("recommended_topics", []) or []:
            key = str(topic).strip().lower()
            if not key:
                continue
            weak_topic_counts[key] = weak_topic_counts.get(key, 0) + 1

    ranked_weak_topics = sorted(weak_topic_counts.items(), key=lambda item: item[1], reverse=True)
    focus_topics = [name for name, _ in ranked_weak_topics[:5]]
    if not focus_topics:
        focus_topics = ["data structures", "algorithms", "system design"]

    interview_target = max(2, 5 - min(activity.get("practice_interviews", 0), 3))
    test_target = max(2, 6 - min(activity.get("mock_tests", 0), 4))

    return {
        "user_id": user_id,
        "title": "4-Week Interview Roadmap",
        "weeks": [
            {
                "week": 1,
                "goal": "Rebuild fundamentals",
                "tasks": [
                    f"Practice {focus_topics[0]} questions (45 min/day)",
                    f"Attempt {test_target // 2} focused mock tests",
                ],
            },
            {
                "week": 2,
                "goal": "Sharpen weak areas",
                "tasks": [
                    f"Deep dive on {focus_topics[1] if len(focus_topics) > 1 else focus_topics[0]}",
                    "Review mistakes and create flash notes",
                ],
            },
            {
                "week": 3,
                "goal": "Interview simulation",
                "tasks": [
                    f"Complete {interview_target} mock interviews",
                    "Record and review communication clarity",
                ],
            },
            {
                "week": 4,
                "goal": "Final readiness sprint",
                "tasks": [
                    "Take full-length mock tests under time pressure",
                    "Polish resume stories and STAR examples",
                ],
            },
        ],
        "focus_topics": focus_topics,
        "generated_at": _current_timestamp(),
    }


async def _persist_learning_roadmap(user_id: str, roadmap: Dict[str, Any]) -> None:
    client = get_supabase_client()
    payload = {
        "user_id": user_id,
        "title": roadmap.get("title") or "Learning Roadmap",
        "status": "active",
        "roadmap_data": roadmap,
        "updated_at": _current_timestamp(),
    }

    def _insert() -> None:
        client.table(LEARNING_ROADMAPS_TABLE).insert(payload).execute()

    try:
        await run_in_threadpool(_insert)
    except Exception:
        logger.warning("Failed to persist learning roadmap for %s", user_id, exc_info=True)


async def _fetch_latest_learning_roadmap(user_id: str) -> Optional[Dict[str, Any]]:
    client = get_supabase_client()

    def _fetch() -> Optional[Dict[str, Any]]:
        response = (
            client.table(LEARNING_ROADMAPS_TABLE)
            .select("roadmap_data")
            .eq("user_id", user_id)
            .eq("status", "active")
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        rows = getattr(response, "data", None) or []
        if not rows:
            return None
        payload = (rows[0] or {}).get("roadmap_data")
        return payload if isinstance(payload, dict) else None

    try:
        return await run_in_threadpool(_fetch)
    except Exception:
        logger.warning("Failed to fetch roadmap for %s", user_id, exc_info=True)
        return None


def _build_default_reminders(activity: Dict[str, int]) -> List[Dict[str, Any]]:
    reminders: List[Dict[str, Any]] = []
    now = _utcnow()
    reminders.append(
        {
            "reminder_type": "practice",
            "title": "Daily Coding Warmup",
            "message": "Solve 2 timed questions today to maintain momentum.",
            "status": "pending",
            "due_at": _isoformat(now + timedelta(hours=8)),
            "metadata": {"target_questions": 2},
        }
    )
    if activity.get("practice_interviews", 0) < 3:
        reminders.append(
            {
                "reminder_type": "interview",
                "title": "Schedule Mock Interview",
                "message": "Book one mock interview session this week.",
                "status": "pending",
                "due_at": _isoformat(now + timedelta(days=2)),
                "metadata": {"target_sessions": 1},
            }
        )
    if activity.get("mock_tests", 0) < 4:
        reminders.append(
            {
                "reminder_type": "assessment",
                "title": "Take a Full Mock Test",
                "message": "Complete one full mock test and review weak topics.",
                "status": "pending",
                "due_at": _isoformat(now + timedelta(days=1)),
                "metadata": {"target_tests": 1},
            }
        )
    return reminders


async def _upsert_default_reminders(user_id: str, reminders: List[Dict[str, Any]]) -> None:
    client = get_supabase_client()

    def _insert_many() -> None:
        existing = (
            client.table(USER_REMINDERS_TABLE)
            .select("id")
            .eq("user_id", user_id)
            .eq("status", "pending")
            .limit(1)
            .execute()
        )
        if getattr(existing, "data", None):
            return
        payload = [{**item, "user_id": user_id, "updated_at": _current_timestamp()} for item in reminders]
        if payload:
            client.table(USER_REMINDERS_TABLE).insert(payload).execute()

    try:
        await run_in_threadpool(_insert_many)
    except Exception:
        logger.warning("Failed to upsert reminders for %s", user_id, exc_info=True)


async def _fetch_user_reminders(user_id: str, status: str = "pending") -> List[Dict[str, Any]]:
    client = get_supabase_client()

    def _fetch() -> List[Dict[str, Any]]:
        response = (
            client.table(USER_REMINDERS_TABLE)
            .select("id,reminder_type,title,message,status,due_at,metadata,created_at")
            .eq("user_id", user_id)
            .eq("status", status)
            .order("due_at", desc=False)
            .execute()
        )
        rows = getattr(response, "data", None) or []
        return [row or {} for row in rows]

    try:
        return await run_in_threadpool(_fetch)
    except Exception:
        logger.warning("Failed to fetch reminders for %s", user_id, exc_info=True)
        return []


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


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


async def _scrape_quiz_candidates_from_interview_sites(
    user_query: str,
    limit: int = QUIZ_SCRAPE_DOC_LIMIT,
    source_ids: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    query = (user_query or "").strip()
    if not query:
        return []

    allowed_source_ids = {
        (source_id or "").strip().lower()
        for source_id in (source_ids or [])
        if (source_id or "").strip()
    }
    selected_sources = [
        source for source in QUIZ_SCRAPE_SOURCES
        if not allowed_source_ids or source.get("id", "").lower() in allowed_source_ids
    ]
    if not selected_sources:
        return []

    search_tasks = [
        asyncio.create_task(_search_source_links(source, query, QUIZ_SEARCH_RESULTS_PER_SOURCE))
        for source in selected_sources
    ]
    search_results = await asyncio.gather(*search_tasks, return_exceptions=True)

    scrape_tasks: List[asyncio.Task] = []
    for source, result in zip(selected_sources, search_results):
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
WHISPER_MODEL_CACHE: Any = None


def _get_whisper_model() -> Any:
    global WHISPER_MODEL_CACHE
    if WHISPER_MODEL_CACHE is not None:
        return WHISPER_MODEL_CACHE

    model_name = os.getenv("WHISPER_MODEL", "small")
    try:
        from faster_whisper import WhisperModel  # type: ignore
        WHISPER_MODEL_CACHE = {
            "provider": "faster-whisper",
            "model": WhisperModel(model_name, device="cpu", compute_type="int8"),
            "name": model_name,
        }
        logger.info("Loaded faster-whisper model: %s", model_name)
        return WHISPER_MODEL_CACHE
    except ImportError as exc:
        logger.warning("faster-whisper not available, falling back to openai-whisper", exc_info=True)

    try:
        import whisper  # type: ignore
        WHISPER_MODEL_CACHE = {
            "provider": "openai-whisper",
            "model": whisper.load_model(model_name),
            "name": model_name,
        }
        logger.info("Loaded openai-whisper model: %s", model_name)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=500,
            detail="Whisper is not installed. Install dependency: faster-whisper",
        ) from exc

    return WHISPER_MODEL_CACHE


def _transcribe_with_whisper(temp_path: str) -> Tuple[str, str]:
    model_bundle = _get_whisper_model()
    provider = model_bundle.get("provider")
    model_name = model_bundle.get("name", os.getenv("WHISPER_MODEL", "small"))
    configured_language = (os.getenv("WHISPER_LANGUAGE", "en") or "").strip()
    whisper_language = configured_language or None

    if provider == "faster-whisper":
        model = model_bundle["model"]
        segments, _ = model.transcribe(
            temp_path,
            task="transcribe",
            language=whisper_language,
            beam_size=5,
            best_of=5,
            temperature=0.0,
            condition_on_previous_text=False,
            vad_filter=True,
        )
        text = " ".join(segment.text for segment in segments).strip()

        # Retry without VAD if the first pass filtered out short/quiet speech.
        if not text:
            segments, _ = model.transcribe(
                temp_path,
                task="transcribe",
                language=whisper_language,
                beam_size=5,
                best_of=5,
                temperature=0.0,
                condition_on_previous_text=False,
                vad_filter=False,
            )
            text = " ".join(segment.text for segment in segments).strip()

        # Final fallback: allow language auto-detection when forced language fails.
        if not text and whisper_language is not None:
            segments, _ = model.transcribe(
                temp_path,
                task="transcribe",
                language=None,
                beam_size=5,
                best_of=5,
                temperature=0.0,
                condition_on_previous_text=False,
                vad_filter=False,
            )
            text = " ".join(segment.text for segment in segments).strip()
        return text, model_name

    model = model_bundle["model"]
    result = model.transcribe(
        temp_path,
        task="transcribe",
        language=whisper_language,
        temperature=0.0,
        condition_on_previous_text=False,
        fp16=False,
    )
    text = str(result.get("text", "")).strip()

    if not text:
        result = model.transcribe(
            temp_path,
            task="transcribe",
            language=None,
            temperature=0.0,
            condition_on_previous_text=False,
            fp16=False,
        )
        text = str(result.get("text", "")).strip()

    return text, model_name

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


SOFTWARE_ENGINEER_MIXED_QUESTION_BANK: List[Dict[str, Any]] = [
    {
        "id": "se-1",
        "question_text": "What is the time complexity of binary search on a sorted array?",
        "options": ["O(n)", "O(log n)", "O(n log n)", "O(1)"],
        "correct_answer": "O(log n)",
        "difficulty": "easy",
        "tags": ["algorithms", "searching"],
    },
    {
        "id": "se-2",
        "question_text": "Which data structure follows First-In-First-Out (FIFO) order?",
        "options": ["Stack", "Queue", "Tree", "Graph"],
        "correct_answer": "Queue",
        "difficulty": "easy",
        "tags": ["data-structures", "queue"],
    },
    {
        "id": "se-3",
        "question_text": "What is the worst-case time complexity of quicksort?",
        "options": ["O(n log n)", "O(n^2)", "O(log n)", "O(n)"],
        "correct_answer": "O(n^2)",
        "difficulty": "medium",
        "tags": ["algorithms", "sorting"],
    },
    {
        "id": "se-4",
        "question_text": "Which traversal of a Binary Search Tree returns values in sorted order?",
        "options": ["Preorder", "Postorder", "Inorder", "Level order"],
        "correct_answer": "Inorder",
        "difficulty": "easy",
        "tags": ["trees", "bst"],
    },
    {
        "id": "se-5",
        "question_text": "Which principle does a stack follow?",
        "options": ["FIFO", "LIFO", "Both FIFO and LIFO", "Neither"],
        "correct_answer": "LIFO",
        "difficulty": "easy",
        "tags": ["data-structures", "stack"],
    },
    {
        "id": "se-6",
        "question_text": "Which data structure is typically used by Breadth-First Search (BFS)?",
        "options": ["Stack", "Queue", "Tree", "Array"],
        "correct_answer": "Queue",
        "difficulty": "easy",
        "tags": ["graphs", "bfs"],
    },
    {
        "id": "se-7",
        "question_text": "Which data structure is typically used by Depth-First Search (DFS)?",
        "options": ["Queue", "Stack", "Heap", "Tree"],
        "correct_answer": "Stack",
        "difficulty": "easy",
        "tags": ["graphs", "dfs"],
    },
    {
        "id": "se-8",
        "question_text": "What is the time complexity of merge sort?",
        "options": ["O(n log n)", "O(n^2)", "O(log n)", "O(n)"],
        "correct_answer": "O(n log n)",
        "difficulty": "easy",
        "tags": ["algorithms", "sorting"],
    },
    {
        "id": "se-9",
        "question_text": "What is the average time complexity of heap sort?",
        "options": ["O(n log n)", "O(n^2)", "O(n)", "O(log n)"],
        "correct_answer": "O(n log n)",
        "difficulty": "easy",
        "tags": ["algorithms", "sorting", "heap"],
    },
    {
        "id": "se-10",
        "question_text": "In sorting, what does it mean for an algorithm to be stable?",
        "options": ["It is always fast", "It preserves relative order of equal elements", "It uses less memory", "It must be recursive"],
        "correct_answer": "It preserves relative order of equal elements",
        "difficulty": "medium",
        "tags": ["algorithms", "sorting"],
    },
    {
        "id": "se-11",
        "question_text": "Which of the following is a linear data structure?",
        "options": ["Tree", "Graph", "Array", "Heap"],
        "correct_answer": "Array",
        "difficulty": "easy",
        "tags": ["data-structures"],
    },
    {
        "id": "se-12",
        "question_text": "Which of the following is a non-linear data structure?",
        "options": ["Stack", "Queue", "Tree", "Array"],
        "correct_answer": "Tree",
        "difficulty": "easy",
        "tags": ["data-structures"],
    },
    {
        "id": "se-13",
        "question_text": "Hashing is primarily used to optimize which operation?",
        "options": ["Sorting", "Searching", "Deleting files", "Traversal"],
        "correct_answer": "Searching",
        "difficulty": "easy",
        "tags": ["hashing", "data-structures"],
    },
    {
        "id": "se-14",
        "question_text": "In hash tables, a collision occurs when:",
        "options": ["A stack overflows", "A queue is full", "Two keys map to the same index", "A tree becomes unbalanced"],
        "correct_answer": "Two keys map to the same index",
        "difficulty": "medium",
        "tags": ["hashing"],
    },
    {
        "id": "se-15",
        "question_text": "An AVL tree is best described as:",
        "options": ["A generic binary tree", "A self-balanced Binary Search Tree", "A heap", "A graph"],
        "correct_answer": "A self-balanced Binary Search Tree",
        "difficulty": "medium",
        "tags": ["trees", "bst"],
    },
    {
        "id": "se-16",
        "question_text": "Which algorithm can be used for cycle detection in graphs?",
        "options": ["DFS", "Binary Search", "Heap Sort", "Queue Rotation"],
        "correct_answer": "DFS",
        "difficulty": "medium",
        "tags": ["graphs", "dfs"],
    },
    {
        "id": "se-17",
        "question_text": "Which underlying data structure is commonly used to implement a priority queue?",
        "options": ["Stack", "Heap", "Array only", "Graph"],
        "correct_answer": "Heap",
        "difficulty": "easy",
        "tags": ["heap", "priority-queue"],
    },
    {
        "id": "se-18",
        "question_text": "What is the time complexity of linear search in the worst case?",
        "options": ["O(log n)", "O(n)", "O(n log n)", "O(1)"],
        "correct_answer": "O(n)",
        "difficulty": "easy",
        "tags": ["algorithms", "searching"],
    },
    {
        "id": "se-19",
        "question_text": "Which representation is commonly used to store dense graphs?",
        "options": ["Adjacency matrix", "Binary tree", "Stack", "Queue"],
        "correct_answer": "Adjacency matrix",
        "difficulty": "medium",
        "tags": ["graphs"],
    },
    {
        "id": "se-20",
        "question_text": "Topological sort is defined for which type of graph?",
        "options": ["Undirected tree", "Directed Acyclic Graph (DAG)", "Any cyclic graph", "Heap"],
        "correct_answer": "Directed Acyclic Graph (DAG)",
        "difficulty": "medium",
        "tags": ["graphs", "dag"],
    },
    {
        "id": "se-21",
        "question_text": "Dijkstra's algorithm is guaranteed to work correctly when edge weights are:",
        "options": ["Negative", "Non-negative", "Both negative and positive", "Undefined"],
        "correct_answer": "Non-negative",
        "difficulty": "medium",
        "tags": ["graphs", "shortest-path"],
    },
    {
        "id": "se-22",
        "question_text": "What additional condition can Bellman-Ford detect compared to Dijkstra's algorithm?",
        "options": ["Cycles in trees", "Negative weight cycles", "Only connected graphs", "Graph coloring"],
        "correct_answer": "Negative weight cycles",
        "difficulty": "medium",
        "tags": ["graphs", "shortest-path"],
    },
    {
        "id": "se-23",
        "question_text": "Dynamic Programming mainly stores what to avoid recomputation?",
        "options": ["Future guesses", "Results of subproblems", "Stack frames only", "Queue states"],
        "correct_answer": "Results of subproblems",
        "difficulty": "easy",
        "tags": ["dynamic-programming"],
    },
    {
        "id": "se-24",
        "question_text": "In SQL, what is the purpose of a primary key?",
        "options": ["Allow duplicates", "Uniquely identify each row", "Store foreign table names", "Allow only NULL values"],
        "correct_answer": "Uniquely identify each row",
        "difficulty": "easy",
        "tags": ["sql", "database"],
    },
    {
        "id": "se-25",
        "question_text": "A foreign key in a relational database is used to:",
        "options": ["Force uniqueness in same table", "Reference a key in another table", "Create indexes automatically", "Delete parent rows"],
        "correct_answer": "Reference a key in another table",
        "difficulty": "easy",
        "tags": ["sql", "database"],
    },
    {
        "id": "se-26",
        "question_text": "Normalization in databases primarily helps reduce:",
        "options": ["Compute power", "Data redundancy", "Number of users", "Network traffic"],
        "correct_answer": "Data redundancy",
        "difficulty": "easy",
        "tags": ["sql", "database"],
    },
    {
        "id": "se-27",
        "question_text": "Which SQL command removes a table definition along with its data?",
        "options": ["DELETE", "DROP", "TRUNCATE only", "UPDATE"],
        "correct_answer": "DROP",
        "difficulty": "easy",
        "tags": ["sql", "database"],
    },
    {
        "id": "se-28",
        "question_text": "What does an INNER JOIN return?",
        "options": ["All rows from left table", "All rows from right table", "Only matching rows from both tables", "Cartesian product"],
        "correct_answer": "Only matching rows from both tables",
        "difficulty": "easy",
        "tags": ["sql", "joins"],
    },
    {
        "id": "se-29",
        "question_text": "Which JOIN returns all rows from the left table and matching rows from the right table?",
        "options": ["RIGHT JOIN", "LEFT JOIN", "INNER JOIN", "CROSS JOIN"],
        "correct_answer": "LEFT JOIN",
        "difficulty": "easy",
        "tags": ["sql", "joins"],
    },
    {
        "id": "se-30",
        "question_text": "What is the purpose of an index in databases?",
        "options": ["Improve search/query performance", "Increase redundancy", "Encrypt data", "Replace primary keys"],
        "correct_answer": "Improve search/query performance",
        "difficulty": "easy",
        "tags": ["sql", "database"],
    },
    {
        "id": "se-31",
        "question_text": "In transaction management, ROLLBACK is used to:",
        "options": ["Persist changes", "Undo uncommitted changes", "Delete database", "Create index"],
        "correct_answer": "Undo uncommitted changes",
        "difficulty": "easy",
        "tags": ["sql", "transactions"],
    },
    {
        "id": "se-32",
        "question_text": "In transaction management, COMMIT is used to:",
        "options": ["Save changes permanently", "Undo changes", "Drop table", "Start a deadlock"],
        "correct_answer": "Save changes permanently",
        "difficulty": "easy",
        "tags": ["sql", "transactions"],
    },
    {
        "id": "se-33",
        "question_text": "In operating systems, what is a deadlock?",
        "options": ["A process crash", "A situation where processes wait indefinitely for each other", "A memory leak", "A scheduling optimization"],
        "correct_answer": "A situation where processes wait indefinitely for each other",
        "difficulty": "medium",
        "tags": ["os", "concurrency"],
    },
    {
        "id": "se-34",
        "question_text": "Round Robin scheduling is:",
        "options": ["Preemptive", "Non-preemptive", "Both", "Neither"],
        "correct_answer": "Preemptive",
        "difficulty": "easy",
        "tags": ["os", "scheduling"],
    },
    {
        "id": "se-35",
        "question_text": "In memory management, paging divides memory into blocks of:",
        "options": ["Variable size", "Fixed size", "Random size", "Tree nodes"],
        "correct_answer": "Fixed size",
        "difficulty": "easy",
        "tags": ["os", "memory"],
    },
    {
        "id": "se-36",
        "question_text": "What does page fault mean?",
        "options": ["A page is missing in main memory and must be loaded", "A CPU crash", "A syntax error", "Heap overflow"],
        "correct_answer": "A page is missing in main memory and must be loaded",
        "difficulty": "medium",
        "tags": ["os", "memory"],
    },
    {
        "id": "se-37",
        "question_text": "A thread is best described as:",
        "options": ["A lightweight process", "A heavy process", "A database lock", "A disk block"],
        "correct_answer": "A lightweight process",
        "difficulty": "easy",
        "tags": ["os", "processes"],
    },
    {
        "id": "se-38",
        "question_text": "What does starvation mean in CPU scheduling?",
        "options": ["A process never gets CPU time", "CPU is always idle", "All processes are blocked by I/O", "Page replacement failure"],
        "correct_answer": "A process never gets CPU time",
        "difficulty": "medium",
        "tags": ["os", "scheduling"],
    },
    {
        "id": "se-39",
        "question_text": "Encapsulation in OOP is the concept of:",
        "options": ["Hiding internal data and implementation details", "Showing all class data publicly", "Multiple inheritance only", "Automatic garbage collection"],
        "correct_answer": "Hiding internal data and implementation details",
        "difficulty": "easy",
        "tags": ["oop"],
    },
    {
        "id": "se-40",
        "question_text": "Abstraction in OOP primarily means:",
        "options": ["Hiding implementation complexity", "Copying objects", "Deleting data", "Running code in parallel"],
        "correct_answer": "Hiding implementation complexity",
        "difficulty": "easy",
        "tags": ["oop"],
    },
    {
        "id": "se-41",
        "question_text": "Polymorphism in OOP refers to:",
        "options": ["One function taking many forms", "Only compile-time constants", "Using only interfaces", "Creating static classes"],
        "correct_answer": "One function taking many forms",
        "difficulty": "easy",
        "tags": ["oop"],
    },
    {
        "id": "se-42",
        "question_text": "Method overriding occurs when:",
        "options": ["A subclass redefines a parent class method", "Two methods have different names", "A method has optional params", "A class has no constructor"],
        "correct_answer": "A subclass redefines a parent class method",
        "difficulty": "medium",
        "tags": ["oop"],
    },
    {
        "id": "se-43",
        "question_text": "In software engineering, REST commonly refers to:",
        "options": ["A style for designing web APIs", "A SQL optimizer", "A Java compiler", "A cloud vendor"],
        "correct_answer": "A style for designing web APIs",
        "difficulty": "easy",
        "tags": ["backend", "api"],
    },
    {
        "id": "se-44",
        "question_text": "HTTPS is:",
        "options": ["HTTP over a secure encrypted connection", "A database schema", "A hashing algorithm", "A container runtime"],
        "correct_answer": "HTTP over a secure encrypted connection",
        "difficulty": "easy",
        "tags": ["web", "security"],
    },
    {
        "id": "se-45",
        "question_text": "JSON is primarily used as:",
        "options": ["A data interchange format", "A compiled language", "A database engine", "An OS scheduler"],
        "correct_answer": "A data interchange format",
        "difficulty": "easy",
        "tags": ["web", "data-format"],
    },
    {
        "id": "se-46",
        "question_text": "Docker is used for:",
        "options": ["Containerizing applications", "Managing SQL joins", "Running only virtual machines", "Writing CSS"],
        "correct_answer": "Containerizing applications",
        "difficulty": "easy",
        "tags": ["devops", "containers"],
    },
    {
        "id": "se-47",
        "question_text": "Kubernetes is primarily a:",
        "options": ["Container orchestration platform", "Version control system", "Programming language", "Unit testing framework"],
        "correct_answer": "Container orchestration platform",
        "difficulty": "medium",
        "tags": ["devops", "containers"],
    },
    {
        "id": "se-48",
        "question_text": "Git is mainly used for:",
        "options": ["Version control", "Database indexing", "Thread scheduling", "Memory paging"],
        "correct_answer": "Version control",
        "difficulty": "easy",
        "tags": ["tools", "git"],
    },
    {
        "id": "se-49",
        "question_text": "A Git branch is best described as:",
        "options": ["An independent line of development", "A deleted commit", "A permanent release tag", "A merge conflict file"],
        "correct_answer": "An independent line of development",
        "difficulty": "easy",
        "tags": ["tools", "git"],
    },
    {
        "id": "se-50",
        "question_text": "CI/CD is used to:",
        "options": ["Automate build, test, and deployment pipelines", "Create only UI mockups", "Replace version control", "Manage only databases"],
        "correct_answer": "Automate build, test, and deployment pipelines",
        "difficulty": "easy",
        "tags": ["devops", "ci-cd"],
    },
]


def _flatten_questions() -> List[Dict[str, Any]]:

    items: List[Dict[str, Any]] = []
    for questions in QUESTION_BANK.values():
        items.extend(questions)
    return items


def _normalize_quiz_text(value: Optional[str]) -> str:
    return (value or "").strip().lower()


def _normalize_role_text(value: Optional[str]) -> str:
    raw = _normalize_quiz_text(value)
    if not raw:
        return ""
    normalized = re.sub(r"[^a-z0-9]+", " ", raw).strip()
    aliases = {
        "software developer": "software engineer",
        "software engineering": "software engineer",
        "software-engineer": "software engineer",
        "software-developer": "software engineer",
        "sde": "software engineer",
    }
    return aliases.get(normalized, normalized)


QUIZ_RELEVANCE_STOP_WORDS = {
    "and", "the", "for", "with", "from", "that", "this", "what", "when", "where",
    "which", "into", "your", "about", "using", "used", "have", "will", "their", "topic",
    "subject", "question", "questions", "problem", "interview", "practice", "guide", "basic",
}


def _quiz_relevance_tokens(value: Optional[str]) -> List[str]:
    words = re.findall(r"[a-zA-Z][a-zA-Z0-9\-]{2,}", _normalize_quiz_text(value))
    return [word for word in words if word not in QUIZ_RELEVANCE_STOP_WORDS]


def _score_quiz_candidate(candidate: Dict[str, Any], subject: str, topic: Optional[str]) -> int:
    subject_text = _normalize_quiz_text(subject)
    topic_text = _normalize_quiz_text(topic)

    searchable = " ".join(
        [
            _normalize_quiz_text(candidate.get("title")),
            _normalize_quiz_text(candidate.get("description")),
            _normalize_quiz_text(candidate.get("source")),
            " ".join(_normalize_quiz_text(tag) for tag in candidate.get("tags", []) or []),
            " ".join(_normalize_quiz_text(company) for company in candidate.get("companies", []) or []),
        ]
    )

    score = 0
    if subject_text and subject_text in searchable:
        score += 8
    if topic_text and topic_text in searchable:
        score += 8

    query_tokens = set(_quiz_relevance_tokens(f"{subject_text} {topic_text}"))
    if query_tokens:
        overlap = sum(1 for token in query_tokens if token in searchable)
        score += overlap * 2

    tags = [
        _normalize_quiz_text(tag).replace("-", " ")
        for tag in (candidate.get("tags", []) or [])
        if _normalize_quiz_text(tag)
    ]
    for token in query_tokens:
        if any(token in tag for tag in tags):
            score += 1

    return score


def _rank_quiz_candidates(
    candidates: List[Dict[str, Any]],
    subject: str,
    topic: Optional[str],
    *,
    min_score: Optional[int] = None,
) -> List[Dict[str, Any]]:
    scored: List[Tuple[int, Dict[str, Any]]] = []
    for candidate in candidates:
        scored.append((_score_quiz_candidate(candidate, subject, topic), candidate))

    ranked = sorted(
        scored,
        key=lambda item: (item[0], _normalize_quiz_text(item[1].get("title"))),
        reverse=True,
    )

    if min_score is not None:
        ranked = [item for item in ranked if item[0] >= min_score]

    seen_titles: set[str] = set()
    unique_ranked: List[Dict[str, Any]] = []
    for _, candidate in ranked:
        title_key = _normalize_quiz_text(candidate.get("title"))
        if title_key and title_key in seen_titles:
            continue
        if title_key:
            seen_titles.add(title_key)
        unique_ranked.append(candidate)

    return unique_ranked


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
            return _rank_quiz_candidates(matched, subject, topic)

    if filtered:
        return _rank_quiz_candidates(filtered, subject, topic)
    return _rank_quiz_candidates(all_questions, subject, topic)


def _build_mcq_from_question(raw_question: Dict[str, Any], quiz_id: int, question_order: int) -> Dict[str, Any]:
    direct_question_text = str(raw_question.get("question_text") or "").strip()
    direct_options = raw_question.get("options")
    direct_correct = str(raw_question.get("correct_answer") or "").strip()
    if direct_question_text and isinstance(direct_options, list) and direct_correct:
        tags = [str(tag).strip() for tag in raw_question.get("tags", []) if str(tag).strip()]
        options = [str(option).strip() for option in direct_options if str(option).strip()]
        if direct_correct not in options:
            options.append(direct_correct)
        deduped_options: List[str] = []
        for option in options:
            if option not in deduped_options:
                deduped_options.append(option)
        random.shuffle(deduped_options)
        return {
            "id": next(QUIZ_QUESTION_ID_COUNTER),
            "quiz_id": quiz_id,
            "question_text": direct_question_text,
            "question_type": "mcq",
            "options": deduped_options,
            "points": 1,
            "topic_tags": tags,
            "question_order": question_order,
            "_correct_answer": direct_correct,
        }

    tags = [str(tag).strip() for tag in raw_question.get("tags", []) if str(tag).strip()]
    source = str(raw_question.get("source") or "general").strip().title()
    title = str(raw_question.get("title") or "Interview Question").strip()
    description = str(raw_question.get("description") or "").strip()
    concept_pool = [
        "Two pointers",
        "Sliding window",
        "Hash map",
        "Dynamic programming",
        "Greedy approach",
        "Binary search",
        "Stack",
        "Queue",
        "Graph traversal",
        "Recursion",
        "Time complexity",
        "Edge cases",
    ]

    if tags:
        correct_answer = tags[0].title()
        distractors = [tag.title() for tag in tags[1:3]]
        for concept in concept_pool:
            if concept.lower() != correct_answer.lower() and concept not in distractors:
                distractors.append(concept)
            if len(distractors) >= 3:
                break
        context_text = description if description else title
        prompt = f"Based on this question context, which concept is most relevant? {context_text}"
    else:
        correct_answer = str(raw_question.get("difficulty") or "medium").title()
        distractors = ["Easy", "Medium", "Hard"]
        prompt = f"What is the most likely difficulty level for this problem: {title}?"

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

# JOB PREFERENCE SKILL MAPPINGS
JOB_SKILLS_MAPPING: Dict[str, Dict[str, List[str]]] = {
    "backend": {
        "high": ["python", "java", "nodejs", "golang", "rust", "sql", "rest api", "microservices", "docker", "kubernetes"],
        "medium": ["linux", "git", "agile", "junit", "pytest", "fastapi", "spring", "django", "express", "design patterns"],
        "low": ["frontend", "css", "html", "react", "vue"],
    },
    "frontend": {
        "high": ["javascript", "react", "html", "css", "typescript", "responsive design", "ui/ux", "web development", "npm", "webpack"],
        "medium": ["redux", "vue", "angular", "nextjs", "tailwind", "sass", "design systems", "accessibility", "api integration"],
        "low": ["backend", "sql", "docker", "devops"],
    },
    "fullstack": {
        "high": ["javascript", "react", "nodejs", "sql", "html", "css", "typescript", "rest api", "database", "web development"],
        "medium": ["python", "java", "docker", "git", "agile", "design patterns", "nextjs", "express", "mongodb"],
        "low": ["devops", "kubernetes", "cloud architecture"],
    },
    "devops": {
        "high": ["docker", "kubernetes", "ci/cd", "jenkins", "linux", "terraform", "ansible", "aws", "azure", "gcp"],
        "medium": ["python", "bash", "git", "monitoring", "prometheus", "grafana", "infrastructure", "automation"],
        "low": ["java", "frontend", "ui/ux"],
    },
    "data science": {
        "high": ["python", "machine learning", "data analysis", "pandas", "numpy", "scikit-learn", "tensorflow", "sql", "statistics"],
        "medium": ["deep learning", "nlp", "computer vision", "jupyter", "matplotlib", "visualization", "spark", "hadoop"],
        "low": ["frontend", "backend", "devops"],
    },
    "cloud": {
        "high": ["aws", "azure", "gcp", "cloud architecture", "terraform", "docker", "kubernetes", "infrastructure", "networking"],
        "medium": ["python", "automation", "monitoring", "security", "ci/cd", "databases"],
        "low": ["frontend", "ui/ux"],
    },
}


async def _extract_text_from_pdf(content: bytes) -> str:
    """Extract text from PDF file content."""
    try:
        text_parts: List[str] = []
        
        def _extract() -> str:
            import io
            with pdfplumber.open(io.BytesIO(content)) as pdf:
                for page in pdf.pages[:10]:  # Limit to first 10 pages for performance
                    page_text = page.extract_text()
                    if page_text:
                        text_parts.append(page_text)
            return "\n".join(text_parts)
        
        extracted = await run_in_threadpool(_extract)
        return extracted
    except Exception as exc:
        logger.warning("PDF text extraction failed: %s", exc)
        return ""


def _extract_skills_from_text(text: str) -> List[str]:
    """Extract technical skills from resume text."""
    text_lower = text.lower()
    
    all_skills = {
        # Programming Languages
        "python", "java", "javascript", "typescript", "c++", "c#", "go", "golang", "rust", "php", "ruby", "kotlin", "scala",
        # Frontend
        "react", "vue", "angular", "nextjs", "html", "css", "sass", "webpack", "npm", "responsive design", "ui/ux", "tailwind", "bootstrap",
        # Backend
        "nodejs", "express", "django", "fastapi", "spring", "flask", "rails", "laravel", "rest api", "graphql", "grpc",
        # Databases
        "sql", "mongodb", "postgresql", "mysql", "firebase", "dynamodb", "redis", "elasticsearch", "cassandra", "oracle",
        # Cloud & DevOps
        "aws", "azure", "gcp", "docker", "kubernetes", "terraform", "ansible", "jenkins", "ci/cd", "github actions",
        # Data & AI
        "machine learning", "deep learning", "tensorflow", "pytorch", "scikit-learn", "pandas", "numpy", "data analysis", "nlp", "computer vision",
        # Tools & Practices
        "git", "linux", "agile", "scrum", "design patterns", "microservices", "testing", "pytest", "junit", "tdd",
        # Monitoring & Logging
        "prometheus", "grafana", "datadog", "elk", "newrelic", "monitoring", "logging",
        # Other
        "api design", "system design", "architecture", "performance optimization", "security",
    }
    
    extracted_skills = set()
    for skill in all_skills:
        if skill in text_lower:
            extracted_skills.add(skill)
    
    return sorted(list(extracted_skills))


def _estimate_experience_years(text: str) -> Optional[int]:
    """Estimate years of experience from resume text."""
    import re
    
    # Look for patterns like "5 years", "15+ years", etc.
    patterns = [
        r'(\d+)\s*\+?\s*years?\s+of\s+experience',
        r'(\d+)\s*\+?\s*years?\s+in',
        r'experience:\s*(\d+)\s*\+?\s*years?',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text.lower())
        if match:
            try:
                return int(match.group(1))
            except (ValueError, AttributeError):
                pass
    
    return None


def _calculate_resume_score(
    extracted_skills: List[str],
    job_preference: Optional[str],
    experience_years: Optional[int],
) -> Tuple[float, List[SkillMatch], List[SkillMatch]]:
    """Calculate resume score based on skills and job preference."""
    
    base_score = 50.0  # Start with 50% base
    matched_skills_list: List[SkillMatch] = []
    missing_skills_list: List[SkillMatch] = []
    
    if not job_preference or job_preference.lower() not in JOB_SKILLS_MAPPING:
        # No job preference specified
        skill_bonus = min(len(extracted_skills) * 2, 30)
        base_score += skill_bonus
        return base_score, matched_skills_list, missing_skills_list
    
    job_mapping = JOB_SKILLS_MAPPING[job_preference.lower()]
    all_required_skills = job_mapping.get("high", []) + job_mapping.get("medium", [])
    
    extracted_skills_lower = {skill.lower() for skill in extracted_skills}
    
    # Score matched skills
    for skill in job_mapping.get("high", []):
        if skill in extracted_skills_lower:
            matched_skills_list.append(SkillMatch(skill=skill, found_in_resume=True, importance="high"))
            base_score += 3
        else:
            missing_skills_list.append(SkillMatch(skill=skill, found_in_resume=False, importance="high"))
    
    for skill in job_mapping.get("medium", []):
        if skill in extracted_skills_lower:
            matched_skills_list.append(SkillMatch(skill=skill, found_in_resume=True, importance="medium"))
            base_score += 1.5
        else:
            missing_skills_list.append(SkillMatch(skill=skill, found_in_resume=False, importance="medium"))
    
    # Experience bonus
    if experience_years and experience_years >= 3:
        base_score += min((experience_years - 3) * 2, 15)
    
    # Cap score at 100
    final_score = min(base_score, 100.0)
    
    return round(final_score, 2), matched_skills_list, missing_skills_list


def _generate_resume_recommendations(
    matched_skills: List[SkillMatch],
    missing_skills: List[SkillMatch],
    extracted_skills: List[str],
    job_preference: Optional[str],
) -> Tuple[List[str], List[str]]:
    """Generate recommendations and strengths for resume."""
    
    recommendations: List[str] = []
    strengths: List[str] = []
    
    # Strengths - Always generate at least some
    if matched_skills:
        high_importance = [s for s in matched_skills if s.importance == "high"]
        if high_importance:
            job_target = job_preference.title() if job_preference else "target role"
            strengths.append(f"Strong alignment with {job_target}: {', '.join([s.skill.title() for s in high_importance[:3]])}")
    
    if extracted_skills:
        strengths.append(f"Demonstrates expertise in {extracted_skills[0].title()}")
        
    if len(extracted_skills) >= 8:
        strengths.append(f"Well-rounded technical skill set ({len(extracted_skills)} skills identified)")
    elif len(extracted_skills) >= 5:
        strengths.append(f"Good foundation with {len(extracted_skills)} key technical skills")
    
    if len(matched_skills) > 0:
        match_ratio = len([s for s in matched_skills if s.importance == "high"]) / max(len(matched_skills), 1)
        if match_ratio >= 0.5:
            strengths.append("Strong match with job requirements")
    
    # If no strengths generated, add a default one
    if not strengths:
        strengths.append("Resume demonstrates technical capability")
    
    # Recommendations - Always provide actionable feedback
    
    # High priority skills gap
    high_priority_missing = [s for s in missing_skills if s.importance == "high"][:3]
    if high_priority_missing:
        skills_str = ", ".join([s.skill.title() for s in high_priority_missing])
        recommendations.append(f"Add experience with critical skills: {skills_str}")
    
    # Skill breadth
    if len(extracted_skills) < 5:
        recommendations.append("Expand your technical skill set - include more tools and technologies you've worked with")
    
    if len(extracted_skills) < 3:
        recommendations.append("Include specific programming languages and frameworks used in your projects")
    
    # Content recommendations
    recommendations.append("Highlight quantifiable achievements with metrics (e.g., 'improved response time by 40%')")
    recommendations.append("Add links to GitHub repositories or portfolio projects showcasing your work")
    recommendations.append("Include examples of problem-solving and cross-functional collaboration")
    
    # Job-specific recommendations
    if job_preference:
        job_target = job_preference.title()
        if job_preference.lower() == "backend":
            recommendations.append("Emphasize database design and API development experience")
        elif job_preference.lower() == "frontend":
            recommendations.append("Showcase responsive design and user experience improvements")
        elif job_preference.lower() == "fullstack":
            recommendations.append("Demonstrate both backend and frontend project work")
        elif job_preference.lower() == "devops":
            recommendations.append("Highlight infrastructure automation and deployment pipeline improvements")
        elif job_preference.lower() == "data science":
            recommendations.append("Include specific ML models built and datasets analyzed")
    
    # Always add this final recommendation
    recommendations.append("Update your resume regularly with recent projects and achievements")
    
    return strengths, recommendations


@app.post("/resume/upload")
async def upload_resume(
    file: UploadFile = File(...),
    job_preference: Optional[str] = Form(None),
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """Upload a resume PDF and extract text."""
    if not file.filename or not file.filename.lower().endswith('.pdf'):
        raise HTTPException(status_code=400, detail="Only PDF files are supported")
    
    content = await file.read()
    if len(content) == 0:
        raise HTTPException(status_code=400, detail="File is empty")
    
    # Extract text from PDF
    extracted_text = await _extract_text_from_pdf(content)
    if not extracted_text.strip():
        raise HTTPException(status_code=400, detail="Could not extract text from PDF. Ensure it's a valid PDF.")
    
    resume_id = next(RESUME_ID_COUNTER)
    
    # Extract skills and experience
    extracted_skills = _extract_skills_from_text(extracted_text)
    experience_years = _estimate_experience_years(extracted_text)
    
    # Calculate score
    score, matched_skills, missing_skills = _calculate_resume_score(
        extracted_skills, job_preference, experience_years
    )
    
    # Generate recommendations
    strengths, recommendations = _generate_resume_recommendations(
        matched_skills, missing_skills, extracted_skills, job_preference
    )
    
    # Calculate match percentage
    match_percentage = score
    
    entry = {
        "id": resume_id,
        "filename": file.filename,
        "upload_date": _current_timestamp(),
        "size_kb": round(len(content) / 1024, 2),
        "extracted_text": extracted_text,
        "job_preference": job_preference,
        "extracted_skills": extracted_skills,
        "experience_years": experience_years,
        "overall_score": score,
        "match_percentage": match_percentage,
        "matched_skills": [s.dict() for s in matched_skills],
        "missing_skills": [s.dict() for s in missing_skills],
        "strengths": strengths,
        "recommendations": recommendations,
        "analysis": None,
    }
    RESUMES.append(entry)
    
    return {
        "id": resume_id,
        "filename": file.filename,
        "message": "Resume uploaded successfully",
        "extracted_skills": extracted_skills,
        "experience_years": experience_years,
        "overall_score": score,
        "match_percentage": match_percentage,
    }


@app.post("/resume/{resume_id}/analyze")
async def analyze_resume(
    resume_id: int,
    job_preference: Optional[str] = Query(None),
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> ResumeAnalysisResult:
    """Analyze an uploaded resume based on job preference."""
    _ = current_user
    resume = next((item for item in RESUMES if item["id"] == resume_id), None)
    if resume is None:
        raise HTTPException(status_code=404, detail="Resume not found")
    
    logger.info(f"Analyzing resume {resume_id}, job_preference: {job_preference}")
    
    # Use provided job_preference or resume's job_preference
    final_job_preference = job_preference or resume.get("job_preference")
    logger.info(f"Final job preference for resume {resume_id}: {final_job_preference}")
    
    # Extract text if not already extracted
    extracted_text = resume.get("extracted_text", "")
    extracted_skills = resume.get("extracted_skills", [])
    
    logger.info(f"Extracted text length: {len(extracted_text)}, extracted skills: {extracted_skills}")
    
    if not extracted_skills:
        extracted_skills = _extract_skills_from_text(extracted_text)
        logger.info(f"Re-extracted skills: {extracted_skills}")
    
    experience_years = resume.get("experience_years") or _estimate_experience_years(extracted_text)
    logger.info(f"Experience years: {experience_years}")
    
    # Recalculate score if job preference changed
    if final_job_preference != resume.get("job_preference"):
        score, matched_skills, missing_skills = _calculate_resume_score(
            extracted_skills, final_job_preference, experience_years
        )
        logger.info(f"Recalculated score: {score}, matched: {len(matched_skills)}, missing: {len(missing_skills)}")
    else:
        score = resume.get("overall_score", 50)
        matched_skills = [SkillMatch(**s) if isinstance(s, dict) else s for s in resume.get("matched_skills", [])]
        missing_skills = [SkillMatch(**s) if isinstance(s, dict) else s for s in resume.get("missing_skills", [])]
        logger.info(f"Using cached score: {score}, matched: {len(matched_skills)}, missing: {len(missing_skills)}")
    
    strengths, recommendations = _generate_resume_recommendations(
        matched_skills, missing_skills, extracted_skills, final_job_preference
    )
    logger.info(f"Generated strengths: {len(strengths)}, recommendations: {len(recommendations)}")
    
    # Create preview of extracted text (first 500 chars)
    text_preview = extracted_text[:500] + "..." if len(extracted_text) > 500 else extracted_text
    
    analysis_result = ResumeAnalysisResult(
        resume_id=resume_id,
        filename=resume["filename"],
        job_preference=final_job_preference,
        overall_score=score,
        match_percentage=score,
        summary=f"Resume analysis for {final_job_preference or 'general'} role. Overall match: {score}%",
        extracted_text_preview=text_preview,
        extracted_skills=extracted_skills,
        matched_skills=matched_skills,
        missing_skills=missing_skills,
        experience_years=experience_years,
        recommendations=recommendations,
        strengths=strengths,
        analyzed_at=_current_timestamp(),
    )
    
    logger.info(f"Analysis result created for resume {resume_id}: {analysis_result}")
    
    resume["analysis"] = analysis_result.dict()
    return analysis_result


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


async def _get_session_or_404(user_id: str, session_id: str) -> Dict[str, Any]:
    session = INTERVIEW_SESSIONS.get(session_id)
    if session is not None:
        return session

    persisted = await _fetch_interview_session(user_id, session_id)
    if persisted is not None:
        INTERVIEW_SESSIONS[session_id] = persisted
        return persisted

    raise HTTPException(status_code=404, detail="Interview session not found")


@app.get("/interview/personas")
async def list_personas() -> Dict[str, Any]:
    return {"personas": INTERVIEW_PERSONAS}


@app.post("/interview/transcribe")
async def transcribe_interview_audio(
    file: UploadFile = File(...),
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    _ = current_user["id"]
    content_type = (file.content_type or "").lower()
    # Some browsers upload blobs as application/octet-stream.
    if content_type and not (
        content_type.startswith("audio/")
        or content_type.startswith("video/")
        or content_type == "application/octet-stream"
    ):
        return {
            "text": "",
            "model": os.getenv("WHISPER_MODEL", "small"),
            "warning": f"Unsupported file type: {content_type}",
        }

    suffix = Path(file.filename or "recording.webm").suffix or ".webm"
    payload = await file.read()
    if not payload:
        return {
            "text": "",
            "model": os.getenv("WHISPER_MODEL", "small"),
            "warning": "Uploaded recording is empty",
        }

    temp_path = ""
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
            temp_file.write(payload)
            temp_path = temp_file.name

        text, model_name = await run_in_threadpool(_transcribe_with_whisper, temp_path)
        normalized_text = (text or "").strip()

        return {
            "text": normalized_text,
            "model": model_name,
            "warning": None if normalized_text else "Could not detect speech in recording",
        }
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception("Whisper transcription failed")
        raise HTTPException(status_code=500, detail="Whisper transcription failed") from exc
    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                logger.warning("Failed to delete temporary audio file: %s", temp_path)


@app.post("/interview/start")
async def start_interview(
    request: InterviewStartRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    user_id = current_user["id"]
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
    await _persist_interview_session(user_id, session_data)
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
    payload: Optional[InterviewAnswerRequest] = Body(None),
    answer: Optional[str] = Query(None, min_length=1),
    audio_duration: Optional[float] = Query(None, ge=0),
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    # Prefer JSON body, but keep query params for backward compatibility.
    final_answer = (payload.answer if payload else answer) or ""
    final_audio_duration = payload.audio_duration if payload and payload.audio_duration is not None else audio_duration
    if not final_answer.strip():
        raise HTTPException(status_code=422, detail="Answer cannot be empty")

    user_id = current_user["id"]
    session = await _get_session_or_404(user_id, session_id)
    if session["status"] == "completed":
        raise HTTPException(status_code=400, detail="Interview session already completed")
    question = session["questions"][session["current_index"]]
    evaluation = _evaluate_answer(question, final_answer)
    speech = _compute_speech_analysis(final_answer, final_audio_duration)
    session["responses"].append(evaluation)
    session["current_index"] += 1
    session["questions_answered"] = len(session["responses"])
    done = session["current_index"] >= len(session["questions"])
    if done:
        session["status"] = "completed"
        session["end_time"] = _current_timestamp()
        await _increment_user_activity_count(user_id, "practice_interviews")
    await _persist_interview_session(user_id, session)
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
    session = await _get_session_or_404(current_user["id"], session_id)
    current_question: Optional[Dict[str, Any]] = None
    if session["status"] == "active" and session.get("current_index", 0) < len(session.get("questions", [])):
        question = session["questions"][session["current_index"]]
        current_question = {
            "question_id": question.get("id"),
            "question": question.get("title"),
            "difficulty": question.get("difficulty"),
            "question_text": question.get("description"),
        }

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
        "question_count": len(session["questions"]),
        "current_question": current_question,
        "start_time": session["start_time"],
        "end_time": session.get("end_time"),
    }


@app.get("/interview/{session_id}/report")
async def interview_report(
    session_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    session = await _get_session_or_404(current_user["id"], session_id)
    return _build_interview_report(session)


@app.delete("/interview/{session_id}")
async def delete_interview(
    session_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, str]:
    user_id = current_user["id"]
    session = await _get_session_or_404(user_id, session_id)
    session["status"] = "deleted"
    INTERVIEW_SESSIONS.pop(session_id, None)
    await _persist_interview_session(user_id, session)
    return {"message": "Interview session deleted"}


@app.get("/interview/sessions/active")
async def active_sessions(current_user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    user_id = current_user["id"]
    persisted = await _list_active_interview_sessions(user_id)
    sessions = [
        {
            "session_id": data.get("session_id"),
            "candidate_name": data.get("candidate_name"),
            "target_role": data.get("target_role"),
            "status": data.get("status"),
            "questions_answered": _safe_int(data.get("questions_answered")),
            "start_time": data.get("start_time"),
        }
        for data in persisted
    ]
    if not sessions:
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
    persisted = await _fetch_user_quizzes(user_id, limit)
    if persisted:
        return persisted[:limit]
    quizzes = USER_QUIZZES.get(user_id, [])
    ordered = sorted(quizzes, key=lambda quiz: quiz.get("created_at", ""), reverse=True)
    return ordered[:limit]


@app.get("/quiz/scrape-sources")
async def list_quiz_scrape_sources(
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> List[Dict[str, str]]:
    _ = current_user
    return [
        {
            "id": source.get("id", ""),
            "name": source.get("name", ""),
            "domain": source.get("domain", ""),
            "seed_url": source.get("seed_url", ""),
        }
        for source in QUIZ_SCRAPE_SOURCES
    ]


@app.post("/quiz/generate")
async def generate_quiz(
    request: QuizGenerateRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    user_id = current_user["id"]
    subject = request.subject.strip()
    if not subject:
        raise HTTPException(status_code=400, detail="Subject is required")

    source_mode = (request.source_mode or "auto").strip().lower()
    if source_mode not in {"auto", "web_only", "internal_only"}:
        raise HTTPException(status_code=400, detail="source_mode must be one of: auto, web_only, internal_only")

    target_role = _normalize_role_text(request.target_role)
    if target_role == "software engineer":
        role_candidates = SOFTWARE_ENGINEER_MIXED_QUESTION_BANK
        requested_difficulty = _normalize_quiz_text(request.difficulty)
        if requested_difficulty in {"easy", "medium", "hard"}:
            role_candidates = [
                question
                for question in role_candidates
                if _normalize_quiz_text(question.get("difficulty")) == requested_difficulty
            ] or SOFTWARE_ENGINEER_MIXED_QUESTION_BANK

        if len(role_candidates) >= request.num_questions:
            selected = random.sample(role_candidates, request.num_questions)
        else:
            selected = role_candidates.copy()
            while len(selected) < request.num_questions:
                selected.append(random.choice(role_candidates))

        quiz_id = next(QUIZ_ID_COUNTER)
        created_at = _current_timestamp()
        quiz_record = {
            "id": quiz_id,
            "title": "Software Engineer Mixed Quiz",
            "description": "Mixed quiz covering DSA, DBMS, OS, OOP, and software fundamentals.",
            "subject": subject,
            "difficulty_level": request.difficulty.lower(),
            "total_questions": request.num_questions,
            "time_limit_minutes": max(5, request.num_questions * 2),
            "quiz_type": "mixed",
            "content_source": "software_engineer_role_bank",
            "created_at": created_at,
        }

        if user_id not in USER_QUIZZES:
            USER_QUIZZES[user_id] = []
        USER_QUIZZES[user_id].append(quiz_record)

        QUIZ_QUESTIONS[quiz_id] = [
            _build_mcq_from_question(raw_question, quiz_id=quiz_id, question_order=index)
            for index, raw_question in enumerate(selected, start=1)
        ]

        persisted_id = await _persist_quiz(user_id, quiz_record, QUIZ_QUESTIONS[quiz_id])
        if persisted_id:
            quiz_record["id"] = persisted_id
            QUIZ_QUESTIONS[persisted_id] = QUIZ_QUESTIONS.pop(quiz_id)
            for question in QUIZ_QUESTIONS[persisted_id]:
                question["quiz_id"] = persisted_id
            if USER_QUIZZES.get(user_id):
                USER_QUIZZES[user_id][-1]["id"] = persisted_id

        return quiz_record

    selected_source_ids = [
        source_id.strip().lower()
        for source_id in (request.scrape_source_ids or [])
        if source_id and source_id.strip()
    ]

    search_query = " ".join(part for part in [subject, request.topic or ""] if part).strip()
    scraped_candidates: List[Dict[str, Any]] = []
    if source_mode in {"auto", "web_only"}:
        scraped_candidates = await _scrape_quiz_candidates_from_interview_sites(
            search_query,
            source_ids=selected_source_ids,
        )
    for candidate in scraped_candidates:
        candidate["difficulty"] = request.difficulty.lower()

    ranked_scraped = _rank_quiz_candidates(scraped_candidates, subject, request.topic, min_score=3)

    internal_candidates: List[Dict[str, Any]] = []
    if source_mode in {"auto", "internal_only"}:
        internal_candidates = _filter_quiz_candidates(subject, request.topic, request.difficulty)
    ranked_internal = _rank_quiz_candidates(internal_candidates, subject, request.topic)

    if source_mode == "web_only":
        candidates = ranked_scraped
    elif source_mode == "internal_only":
        candidates = ranked_internal
    else:
        candidates = ranked_scraped or ranked_internal

    if source_mode == "web_only" and not candidates:
        raise HTTPException(
            status_code=404,
            detail="No web-scraped questions found for this query. Try auto mode or internal questions.",
        )

    if not candidates:
        raise HTTPException(status_code=404, detail="No questions available to generate a quiz")

    selected: List[Dict[str, Any]] = []
    if len(candidates) >= request.num_questions:
        selected = random.sample(candidates, request.num_questions)
    else:
        selected = candidates.copy()
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
        "content_source": "web_scraped" if (source_mode != "internal_only" and scraped_candidates) else "internal_bank",
        "created_at": created_at,
    }

    if user_id not in USER_QUIZZES:
        USER_QUIZZES[user_id] = []
    USER_QUIZZES[user_id].append(quiz_record)

    QUIZ_QUESTIONS[quiz_id] = [
        _build_mcq_from_question(raw_question, quiz_id=quiz_id, question_order=index)
        for index, raw_question in enumerate(selected, start=1)
    ]

    persisted_id = await _persist_quiz(user_id, quiz_record, QUIZ_QUESTIONS[quiz_id])
    if persisted_id:
        quiz_record["id"] = persisted_id
        QUIZ_QUESTIONS[persisted_id] = QUIZ_QUESTIONS.pop(quiz_id)
        for question in QUIZ_QUESTIONS[persisted_id]:
            question["quiz_id"] = persisted_id
        if USER_QUIZZES.get(user_id):
            USER_QUIZZES[user_id][-1]["id"] = persisted_id

    return quiz_record


@app.get("/quiz/{quiz_id}")
async def get_quiz(
    quiz_id: int,
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    user_id = current_user["id"]
    persisted = await _fetch_quiz_bundle(user_id, quiz_id)
    if persisted:
        quiz = persisted.get("quiz") or {}
        questions = persisted.get("questions") or []
        if isinstance(quiz, dict):
            quiz["id"] = quiz_id
            return {
                **quiz,
                "questions": [
                    {
                        key: value
                        for key, value in (question or {}).items()
                        if key != "_correct_answer"
                    }
                    for question in questions
                ],
            }

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

    persisted_quiz = await _fetch_quiz_bundle(user_id, request.quiz_id)
    if not persisted_quiz:
        _get_user_quiz_or_404(user_id, request.quiz_id)

    persisted_attempt = await _create_quiz_attempt(user_id, request.quiz_id)
    if persisted_attempt:
        return {
            "id": persisted_attempt["id"],
            "quiz_id": persisted_attempt["quiz_id"],
            "status": persisted_attempt["status"],
            "started_at": persisted_attempt["started_at"],
        }

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
    persisted_attempt = await _fetch_quiz_attempt(user_id, request.attempt_id)
    if persisted_attempt:
        attempt = {
            "id": _safe_int(persisted_attempt.get("id")),
            "quiz_id": _safe_int(persisted_attempt.get("quiz_id")),
            "user_id": user_id,
            "started_at": persisted_attempt.get("started_at"),
            "submitted_at": persisted_attempt.get("submitted_at"),
            "status": persisted_attempt.get("status"),
        }

    if not attempt or attempt.get("user_id") != user_id:
        raise HTTPException(status_code=404, detail="Quiz attempt not found")
    if attempt.get("status") == "submitted":
        raise HTTPException(status_code=400, detail="Quiz attempt already submitted")

    quiz_bundle = await _fetch_quiz_bundle(user_id, int(attempt["quiz_id"]))
    if quiz_bundle:
        quiz = quiz_bundle.get("quiz") or {}
        if isinstance(quiz, dict):
            quiz["id"] = _safe_int(attempt["quiz_id"])
        questions = quiz_bundle.get("questions") or []
    else:
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
    parsed_started_at: Optional[datetime] = None
    if isinstance(started_at, datetime):
        parsed_started_at = started_at
    elif isinstance(started_at, str):
        try:
            parsed_started_at = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        except ValueError:
            parsed_started_at = None
    if parsed_started_at:
        duration_minutes = max((submitted_at - parsed_started_at).total_seconds() / 60.0, 0.1)

    attempt["status"] = "submitted"
    attempt["submitted_at"] = submitted_at
    await _increment_user_activity_count(user_id, "mock_tests")

    feedback = (
        "Great work. Your fundamentals look solid."
        if passed
        else "Keep practicing and review the recommended topics before your next attempt."
    )

    result_payload = {
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
    await _submit_quiz_attempt_result(user_id, request.attempt_id, result_payload)

    user_test_scores = _get_or_init_user_data(user_id, USER_TEST_SCORES, list)
    user_test_scores.append(
        {
            "id": request.attempt_id,
            "user_id": user_id,
            "test_type": "quiz_attempt",
            "subject": quiz.get("subject") or "mixed",
            "score": score,
            "max_score": max_score,
            "percentage": round(percentage, 2),
            "date_taken": _isoformat(submitted_at),
            "duration_minutes": round(duration_minutes, 2),
            "topics_covered": [str(topic) for topic in (strong_topics[:5] + weak_topics[:5])],
            "weak_topics": weak_topics[:5],
        }
    )

    return result_payload


@app.get("/users/activity-stats")
async def get_user_activity_stats(
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    user_id = current_user["id"]
    stats = await _get_user_activity_stats(user_id)
    return {
        "user_id": user_id,
        "practice_interviews": stats["practice_interviews"],
        "mock_tests": stats["mock_tests"],
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


def _generate_sample_recommendations(
    user_id: str,
    quiz_results: Optional[List[Dict[str, Any]]] = None,
    activity: Optional[Dict[str, int]] = None,
) -> List[Dict[str, Any]]:
    quiz_results = quiz_results or []
    activity = activity or {"practice_interviews": 0, "mock_tests": 0}

    weak_topic_counts: Dict[str, int] = {}
    for result in quiz_results:
        for topic in result.get("recommended_topics", []) or []:
            key = str(topic).strip().lower()
            if not key:
                continue
            weak_topic_counts[key] = weak_topic_counts.get(key, 0) + 1

    ranked_topics = sorted(weak_topic_counts.items(), key=lambda item: item[1], reverse=True)
    top_topic = ranked_topics[0][0] if ranked_topics else "dynamic programming"
    second_topic = ranked_topics[1][0] if len(ranked_topics) > 1 else "system design"
    interview_gap = max(0, 5 - _safe_int(activity.get("practice_interviews")))
    test_gap = max(0, 6 - _safe_int(activity.get("mock_tests")))

    sample_recommendations = [
        {
            "id": 1,
            "user_id": user_id,
            "title": f"Improve {top_topic.title()} Accuracy",
            "description": f"Focus on {top_topic} patterns to lift your weak-topic performance.",
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
            "title": f"Strengthen {second_topic.title()} Fundamentals",
            "description": f"Build depth in {second_topic} with structured practice.",
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
            "title": "Execution Sprint Plan",
            "description": f"Complete {interview_gap or 1} interviews and {test_gap or 1} tests this cycle.",
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
    
    quiz_results = await _fetch_quiz_attempt_results(user_id, limit=25)
    activity = await _get_user_activity_stats(user_id)
    recommendations = _generate_sample_recommendations(user_id, quiz_results, activity)
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
    if not user_recs:
        quiz_results = await _fetch_quiz_attempt_results(user_id, limit=25)
        activity = await _get_user_activity_stats(user_id)
        user_recs = _generate_sample_recommendations(user_id, quiz_results, activity)
        USER_RECOMMENDATIONS[user_id] = user_recs
    
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
    quiz_results = await _fetch_quiz_attempt_results(user_id, limit=120)
    activity = await _get_user_activity_stats(user_id)

    total_tests = len(quiz_results)
    avg_test_score = 0.0
    if total_tests:
        avg_test_score = round(
            sum(float(result.get("percentage", 0.0)) for result in quiz_results) / total_tests,
            1,
        )

    total_problems = sum(_safe_int(result.get("total_questions")) for result in quiz_results)
    total_minutes = sum(float(result.get("time_taken_minutes", 0.0)) for result in quiz_results)
    current_streak = min(total_tests, 14)
    longest_streak = max(current_streak, min(total_tests + _safe_int(activity.get("practice_interviews")), 30))

    USER_PROGRESS_STATS[user_id] = {
        "total_problems_solved": total_problems,
        "total_tests_taken": total_tests,
        "total_interviews": _safe_int(activity.get("practice_interviews")),
        "current_streak": current_streak,
        "longest_streak": longest_streak,
        "total_time_spent_hours": round(total_minutes / 60.0, 2),
        "achievements_earned": _safe_int(activity.get("practice_interviews")) + (1 if avg_test_score >= 70 else 0),
        "avg_test_score": avg_test_score,
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
        base_date = datetime.now(timezone.utc) - timedelta(days=days)
        
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
    quiz_results = await _fetch_quiz_attempt_results(user_id, limit=60)
    test_scores: List[Dict[str, Any]] = []
    for result in quiz_results:
        attempt_id = _safe_int(result.get("attempt_id"))
        percentage = float(result.get("percentage", 0.0))
        total_score = _safe_int(result.get("total_score"))
        max_score = _safe_int(result.get("max_score"))
        topics_covered = result.get("strengths") or []
        weak_topics = result.get("weaknesses") or []
        submitted_at = result.get("submitted_at") or _current_timestamp()

        test_scores.append(
            {
                "id": attempt_id,
                "user_id": user_id,
                "test_type": "quiz_attempt",
                "subject": result.get("quiz_title") or "mixed",
                "score": total_score,
                "max_score": max_score,
                "percentage": round(percentage, 2),
                "date_taken": submitted_at,
                "duration_minutes": float(result.get("time_taken_minutes", 0.0)),
                "topics_covered": topics_covered if isinstance(topics_covered, list) else [],
                "weak_topics": weak_topics if isinstance(weak_topics, list) else [],
            }
        )

    if not test_scores:
        test_scores = _get_or_init_user_data(user_id, USER_TEST_SCORES, list)
    
    return {
        "resumes": resumes,
        "test_scores": test_scores,
        "certifications": certificates,
        "recommendations": recommendations[:3],  
        "progress_stats": progress_stats,
    }


@app.get("/learning/roadmap")
async def get_learning_roadmap(current_user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    user_id = current_user["id"]
    existing = await _fetch_latest_learning_roadmap(user_id)
    if existing:
        return existing

    quiz_results = await _fetch_quiz_attempt_results(user_id, limit=30)
    activity = await _get_user_activity_stats(user_id)
    roadmap = _build_user_learning_roadmap(user_id, quiz_results, activity)
    await _persist_learning_roadmap(user_id, roadmap)
    return roadmap


@app.post("/learning/roadmap/generate")
async def regenerate_learning_roadmap(current_user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    user_id = current_user["id"]
    quiz_results = await _fetch_quiz_attempt_results(user_id, limit=30)
    activity = await _get_user_activity_stats(user_id)
    roadmap = _build_user_learning_roadmap(user_id, quiz_results, activity)
    await _persist_learning_roadmap(user_id, roadmap)
    return roadmap


@app.get("/notifications/reminders")
async def get_user_reminders(current_user: Dict[str, Any] = Depends(get_current_user)) -> List[Dict[str, Any]]:
    user_id = current_user["id"]
    activity = await _get_user_activity_stats(user_id)
    await _upsert_default_reminders(user_id, _build_default_reminders(activity))
    reminders = await _fetch_user_reminders(user_id, status="pending")
    return reminders


@app.put("/notifications/reminders/{reminder_id}/status")
async def update_reminder_status(
    reminder_id: int,
    status: str = Query(..., regex="^(pending|done|dismissed)$"),
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, str]:
    user_id = current_user["id"]
    client = get_supabase_client()

    def _update() -> None:
        (
            client.table(USER_REMINDERS_TABLE)
            .update({"status": status, "updated_at": _current_timestamp()})
            .eq("id", reminder_id)
            .eq("user_id", user_id)
            .execute()
        )

    await run_in_threadpool(_update)
    return {"message": f"Reminder {reminder_id} updated to {status}"}


@app.get("/analytics/readiness")
async def get_readiness_analytics(current_user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    user_id = current_user["id"]
    stats = await get_progress_stats(current_user)
    activity = await _get_user_activity_stats(user_id)
    quiz_results = await _fetch_quiz_attempt_results(user_id, limit=30)

    weak_topic_counts: Dict[str, int] = {}
    for result in quiz_results:
        for topic in result.get("recommended_topics", []) or []:
            key = str(topic).strip().lower()
            if key:
                weak_topic_counts[key] = weak_topic_counts.get(key, 0) + 1
    weak_topics = [name for name, _ in sorted(weak_topic_counts.items(), key=lambda item: item[1], reverse=True)[:5]]

    readiness_score = int(
        min(
            100,
            max(
                20,
                stats.get("avg_test_score", 0) * 0.55
                + min(_safe_int(activity.get("practice_interviews")), 10) * 3
                + min(_safe_int(activity.get("mock_tests")), 12) * 2,
            ),
        )
    )

    return {
        "readiness_score": readiness_score,
        "avg_test_score": stats.get("avg_test_score", 0),
        "practice_interviews": _safe_int(activity.get("practice_interviews")),
        "mock_tests": _safe_int(activity.get("mock_tests")),
        "weak_topics": weak_topics,
    }


# ============================================================================
# LEARNING ASSISTANT AI SERVICE
# ============================================================================

class ConversationMessage(BaseModel):
    role: str  # "user" or "assistant"
    content: str


class DoubtChatRequest(BaseModel):
    message: str
    conversation_history: List[Dict[str, str]] = Field(default_factory=list)
    weak_topics: List[str] = Field(default_factory=list, description="User's weak topics for personalization")
    readiness_score: Optional[int] = None
    learning_goal: Optional[str] = None


class DoubtChatResponse(BaseModel):
    response: str
    section: Optional[str] = None  # "explanation", "example", "summary", "question"
    practice_question: Optional[str] = None
    difficulty_level: Optional[str] = None
    suggestions: List[str] = Field(default_factory=list, description="Follow-up suggestions for user")
    sources: List[Dict[str, Any]] = Field(default_factory=list)
    confidence: Optional[float] = None
    rag_used: Optional[bool] = None


class LearningAssistant:
    """
    Intelligent Learning Assistant AI that helps users deeply understand concepts.
    Provides dynamic, context-aware responses similar to ChatGPT/Gemini.
    Adapts based on user level, weak topics, and learning goals.
    """

    DIFFICULTY_KEYWORDS = {
        "beginner": ["what is", "how to", "tell me about", "basics", "intro", "explain simply", "ez", "easy", "beginner", "simple"],
        "intermediate": ["why", "how does", "when", "advanced", "complex", "comparison", "intermediate", "scenario"],
        "advanced": ["optimize", "edge case", "performance", "system design", "architecture", "deep dive", "advanced", "production"],
    }
    
    # System prompt for better context understanding
    SYSTEM_PROMPT = """You are an expert learning coach and mentor who teaches programming, data structures, algorithms, and interview preparation. Your role is to:

1. **Understand the user**: Listen carefully to their exact question and level
2. **Adapt responses**: Tailor explanations based on their skill level and learning goal
3. **Teach deeply**: Don't just give answers - help them understand the 'why' and 'how'
4. **Be conversational**: Like a real mentor, ask follow-up questions to check understanding
5. **Provide examples**: Use real-world analogies and code examples when relevant
6. **Suggest practice**: Recommend specific practice problems or scenarios
7. **Track progress**: Remember previous topics discussed in this conversation
8. **Be encouraging**: Maintain a supportive, positive tone

When responding:
- Start with a brief, clear answer to their question
- Explain the reasoning behind the concept
- Provide 1-2 concrete examples
- Highlight common mistakes or edge cases
- Suggest the next learning step or related topics
- End with an actionable suggestion or practice challenge
"""

    TOPIC_EXAMPLES = {
        "array": {
            "beginner": "Arrays store multiple items in one place. Like a row of boxes, each box holds something.",
            "intermediate": "Arrays are contiguous memory blocks. Access is O(1), but insertion/deletion can be O(n).",
            "advanced": "Arrays vs Linked Lists: O(1) access vs O(n) access; O(n) insertion vs O(1) insertion.",
        },
        "recursion": {
            "beginner": "Recursion is when a function calls itself. Like looking in a mirror reflecting another mirror.",
            "intermediate": "A recursive function must have a base case (stop condition) and a recursive case.",
            "advanced": "Tail recursion optimization; solving recurrence relations T(n) = T(n-1) + O(1)",
        },
        "binary search": {
            "beginner": "Binary search divides a sorted list in half each time to find an item quickly.",
            "intermediate": "Time complexity is O(log n). Works only on SORTED data.",
            "advanced": "Binary search tree operations; applications in finding boundary conditions; bisect algorithm",
        },
        "hash table": {
            "beginner": "Hash tables use a key to find values quickly, like a phone directory.",
            "intermediate": "Hash function distributes keys. Collision handling: chaining or open addressing.",
            "advanced": "Load factor; hash function properties (universality); consistent hashing",
        },
        "linked list": {
            "beginner": "A linked list is a chain of boxes, each pointing to the next.",
            "intermediate": "Singly vs Doubly linked lists. No random access; O(n) traversal.",
            "advanced": "Skip lists; XOR linked lists; memory efficiency; cycle detection (Floyd's algorithm)",
        },
        "graph": {
            "beginner": "A graph is a network of connected nodes (vertices). Edges show connections.",
            "intermediate": "Directed vs undirected. DFS/BFS for traversal. Adjacency matrix vs list.",
            "advanced": "Topological sort; minimum spanning tree; shortest path algorithms; network flow",
        },
        "tree": {
            "beginner": "A tree is a hierarchical structure with a root and branches.",
            "intermediate": "Binary tree, BST. Traversals: inorder, preorder, postorder. Height & balance.",
            "advanced": "AVL trees, Red-Black trees, B-trees. Splay trees; self-balancing properties",
        },
        "sorting": {
            "beginner": "Sorting arranges items in order. Bubble sort is simple but slow.",
            "intermediate": "Quick sort O(n log n), Merge sort O(n log n), Heap sort. Stability matters.",
            "advanced": "Comparison-based lower bound O(n log n); counting sort, radix sort; online algorithms",
        },
    }

    PRACTICE_QUESTIONS = {
        "array": [
            "MCQ: To find max in array [1,5,3,2], which approach is O(1)? A) Linear search B) Skip to last C) You need to scan all",
            "CODE: Write code to reverse an array without extra space.",
            "SCENARIO: You have student marks [45, 89, 76]. Find students scoring > 50. How would you do it efficiently?",
        ],
        "recursion": [
            "MCQ: What makes this infinite? A) Missing base case B) Wrong return C) Function name",
            "TRACE: What does factorial(3) return? Trace the calls.",
            "CODE: Write a recursive function to sum array elements.",
        ],
    }

    def __init__(self):
        self.user_levels: Dict[str, str] = {}  # Track user levels by conversation
        self.last_topics: Dict[str, str] = {}  # Track last topic

    def detect_user_level(self, message: str, history: List[Dict[str, str]]) -> str:
        """Detect if user is beginner, intermediate, or advanced."""
        message_lower = message.lower()

        score = {"beginner": 0, "intermediate": 0, "advanced": 0}

        for level, keywords in self.DIFFICULTY_KEYWORDS.items():
            for keyword in keywords:
                if keyword in message_lower:
                    score[level] += 1

        if history:
            # If user asks follow-ups on advanced topics, likely advanced
            if any(
                word in history[-1].get("content", "").lower()
                for word in ["optimize", "performance", "edge case"]
            ):
                score["advanced"] += 2

        detected = max(score, key=score.get)
        return detected if score[detected] > 0 else "intermediate"

    def extract_topic(self, message: str) -> str:
        """Extract the topic from user message."""
        message_lower = message.lower()
        for topic in self.TOPIC_EXAMPLES.keys():
            if topic in message_lower or topic.replace(" ", "") in message_lower.replace(" ", ""):
                return topic
        return "general"

    def generate_response(
        self,
        user_message: str,
        conversation_history: List[Dict[str, str]],
        user_id: Optional[str] = None,
        weak_topics: Optional[List[str]] = None,
        readiness_score: Optional[int] = None,
        learning_goal: Optional[str] = None,
    ) -> DoubtChatResponse:
        """
        Generate a dynamic, context-aware response that's personalized to the user.
        Takes into account their level, weak topics, and learning goals.
        """
        history = conversation_history or []
        weak_topics = weak_topics or []
        
        # Detect user's difficulty level based on question
        level = self.detect_user_level(user_message, history)
        
        # Extract topic from the message
        topic = self.extract_topic(user_message)
        
        # Build context for personalized response
        context_factors = []
        if readiness_score:
            context_factors.append(f"readiness score: {readiness_score}%")
        if weak_topics:
            context_factors.append(f"weak areas: {', '.join(weak_topics)}")
        if learning_goal:
            context_factors.append(f"current goal: {learning_goal}")
        
        # Build enhanced response
        response_text = ""
        practice_q = None
        suggestions = []
        
        # Process specific known topics
        if topic in self.TOPIC_EXAMPLES:
            explanation = self.TOPIC_EXAMPLES[topic].get(level, self.TOPIC_EXAMPLES[topic].get("beginner"))
            
            response_text = f"🎯 **{topic.title()}**\n\n"
            
            # Personalized intro
            if topic in weak_topics:
                response_text += f"I see this is one of your weak areas - let's master it together! 💪\n\n"
            
            # Main explanation
            response_text += f"**Explanation** ({level.title()} Level):\n"
            response_text += f"{explanation}\n\n"
            
            # Real-world connection
            response_text += f"**Why It Matters**:\n"
            if level == "beginner":
                response_text += f"Understanding {topic} is fundamental for interview preparation. It's one of the most asked topics!\n\n"
            elif level == "intermediate":
                response_text += f"{topic.title()} is crucial for optimization problems. Interviewers love to test deep understanding here.\n\n"
            else:
                response_text += f"At this level, you should know {topic} deeply - edge cases, optimizations, and when to use alternatives.\n\n"
            
            # Concrete example
            response_text += f"**Practical Example**:\n"
            if topic == "array":
                response_text += "If you're building a student grade system, an array stores each grade. O(1) access makes retrieval instant!\n\n"
            elif topic == "hash table":
                response_text += "A dictionary (hash table) lets you look up a person's phone number in O(1) instead of searching through a list.\n\n"
            elif topic == "linked list":
                response_text += "When you need to frequently insert/delete from the middle (like a playlist), linked lists are better than arrays.\n\n"
            else:
                response_text += f"In interviews, {topic} problems often appear in medium to hard questions.\n\n"
            
            # Add practice question
            if topic in self.PRACTICE_QUESTIONS:
                practice_q = random.choice(self.PRACTICE_QUESTIONS[topic])
                response_text += f"**Try This Practice Question:**\n{practice_q}\n\n"
            
            # Suggestions for follow-up
            if level == "beginner":
                suggestions = [
                    f"Ask me to trace through a {topic} example step-by-step",
                    f"Request common mistakes with {topic}",
                    "Want to try a beginner practice problem?"
                ]
            elif level == "intermediate":
                suggestions = [
                    f"Compare {topic} with alternatives",
                    "Discuss time/space complexity analysis",
                    "Show me interview-level problems"
                ]
            else:
                suggestions = [
                    "Discuss optimization techniques",
                    "Edge cases and corner scenarios",
                    "System design applications"
                ]
        
        elif "help" in user_message.lower() or "explain" in user_message.lower():
            response_text = (
                "👋 Hi! I'm your personalized Learning Coach. Here's what I can help with:\n\n"
                "📚 **Data Structures**: Arrays, Linked Lists, Trees, Graphs, Hash Tables, Stacks, Queues\n"
                "🔍 **Algorithms**: Sorting, Searching, Recursion, DFS/BFS, Binary Search, Dynamic Programming\n"
                "🎯 **Interview Prep**: System Design, Problem-Solving Strategies, Optimal Solutions\n"
                "💡 **Concepts**: Time/Space Complexity, Trade-offs, Real-world Applications\n\n"
                "**How I can help:**\n"
                "• Explain concepts at your level (beginner → advanced)\n"
                "• Provide practice problems with hints\n"
                "• Help you understand 'why' not just 'how'\n"
                "• Remember your weak areas and focus on them\n\n"
                "Just ask me anything! 🚀"
            )
            suggestions = ["Explain arrays for beginners", "Why is recursion important?", "How do hash tables work?"]
        
        elif any(word in user_message.lower() for word in ["improve", "weak", "struggle", "difficult"]):
            # User asking about improvement
            response_text = (
                "Great mindset! 🌟 Let's work on strengthening your understanding.\n\n"
                "Here's my approach:\n"
                "1. **Identify the gap**: What specific part are you struggling with?\n"
                "2. **Learn foundations**: We'll build from basics up\n"
                "3. **Practice actively**: Solve problems and understand patterns\n"
                "4. **Review insights**: Reflect on what you learned\n\n"
            )
            
            if weak_topics:
                response_text += f"**Your current weak areas**: {', '.join(weak_topics)}\n\n"
                response_text += f"I recommend we focus on these one by one. Which would you like to tackle first?\n"
                suggestions = [f"Help me understand {topic}" for topic in weak_topics[:3]]
            else:
                response_text += "Tell me which specific topic you find challenging, and I'll create a focused learning plan!\n"
                suggestions = ["Explain a specific concept", "Give me a practice problem", "Create a study plan"]
        
        else:
            # Generic understanding response
            response_text = (
                f"I see you're interested in: **{user_message[:60]}{'...' if len(user_message) > 60 else ''}**\n\n"
                "Could you be more specific? Try asking:\n"
                "• 'What is [concept]?'\n"
                "• 'Explain [topic] for [level]'\n"
                "• 'How does [concept] work?'\n"
                "• 'Why do we use [concept]?'\n"
                "• 'Show me a problem with [topic]'\n\n"
                "Or type 'help' to see all available topics! 😊"
            )
            suggestions = ["Explain a data structure", "Help with algorithms", "Practice interview questions"]
        
        return DoubtChatResponse(
            response=response_text,
            section="explanation" if topic != "general" else "intro",
            practice_question=practice_q,
            difficulty_level=level,
            suggestions=suggestions,
        )


# Initialize Learning Assistant
learning_assistant = LearningAssistant()


@app.post("/doubts/chat")
async def doubts_chat(
    request: DoubtChatRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> DoubtChatResponse:
    """
    Chat endpoint for the Doubt Chatbot using Learning Assistant AI.
    Provides structured, interactive learning responses.
    Requires authentication.
    """
    try:
        user_id = current_user.get("id") or current_user.get("user_id")

        if answer_with_rag is not None:
            rag_result = answer_with_rag(
                query=request.message,
                user_context={
                    "user_id": user_id,
                    "weak_topics": request.weak_topics,
                    "readiness_score": request.readiness_score,
                    "learning_goal": request.learning_goal,
                    "conversation_history": request.conversation_history,
                },
            )
            if rag_result.get("rag_used"):
                return DoubtChatResponse(**rag_result)

        response = learning_assistant.generate_response(
            user_message=request.message,
            conversation_history=request.conversation_history,
            user_id=user_id,
            weak_topics=request.weak_topics,
            readiness_score=request.readiness_score,
            learning_goal=request.learning_goal
        )
        return response
    except Exception as e:
        logger.error(f"Error in doubts_chat: {e}", exc_info=True)
        return DoubtChatResponse(
            response="Sorry, I'm having trouble understanding. Could you rephrase your question? 🤔"
        )

# ==================== TASK & CALENDAR MANAGEMENT ====================

# In-memory storage for tasks (in production, use database)
USER_TASKS: Dict[str, Dict[str, Any]] = {}
USER_READINESS_RESPONSES: Dict[str, List[Dict[str, Any]]] = {}
TASK_ID_COUNTER = count(1)


class CalendarTaskModel(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = None
    due_date: str = Field(..., description="ISO format date string (YYYY-MM-DD)")


class ReadinessResponseModel(BaseModel):
    readiness_level: int = Field(..., ge=1, le=5)
    feedback: Optional[str] = None


@app.post("/tasks")
async def create_task(
    task: CalendarTaskModel,
    current_user: Dict[str, Any] = Depends(get_current_user)
) -> Dict[str, Any]:
    """Create a new calendar task for the user"""
    user_id = current_user["id"]
    
    if user_id not in USER_TASKS:
        USER_TASKS[user_id] = {}
    
    task_id = str(next(TASK_ID_COUNTER))
    now = _current_timestamp()
    
    new_task = {
        "id": task_id,
        "user_id": user_id,
        "title": task.title,
        "description": task.description,
        "due_date": task.due_date,
        "is_completed": False,
        "created_at": now,
        "updated_at": now,
    }
    
    USER_TASKS[user_id][task_id] = new_task
    return new_task


@app.get("/tasks")
async def get_tasks(
    current_user: Dict[str, Any] = Depends(get_current_user)
) -> List[Dict[str, Any]]:
    """Get all tasks for the current user"""
    user_id = current_user["id"]
    tasks = USER_TASKS.get(user_id, {})
    return list(tasks.values())


@app.get("/tasks/{task_id}")
async def get_task(
    task_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user)
) -> Dict[str, Any]:
    """Get a specific task by ID"""
    user_id = current_user["id"]
    tasks = USER_TASKS.get(user_id, {})
    
    if task_id not in tasks:
        raise HTTPException(status_code=404, detail="Task not found")
    
    return tasks[task_id]


@app.put("/tasks/{task_id}")
async def update_task(
    task_id: str,
    title: Optional[str] = None,
    description: Optional[str] = None,
    due_date: Optional[str] = None,
    is_completed: Optional[bool] = None,
    current_user: Dict[str, Any] = Depends(get_current_user)
) -> Dict[str, Any]:
    """Update a task"""
    user_id = current_user["id"]
    tasks = USER_TASKS.get(user_id, {})
    
    if task_id not in tasks:
        raise HTTPException(status_code=404, detail="Task not found")
    
    task = tasks[task_id]
    
    if title is not None:
        task["title"] = title
    if description is not None:
        task["description"] = description
    if due_date is not None:
        task["due_date"] = due_date
    if is_completed is not None:
        task["is_completed"] = is_completed
    
    task["updated_at"] = _current_timestamp()
    return task


@app.delete("/tasks/{task_id}")
async def delete_task(
    task_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user)
) -> Dict[str, str]:
    """Delete a task"""
    user_id = current_user["id"]
    tasks = USER_TASKS.get(user_id, {})
    
    if task_id not in tasks:
        raise HTTPException(status_code=404, detail="Task not found")
    
    del tasks[task_id]
    return {"message": "Task deleted successfully", "task_id": task_id}


@app.post("/tasks/{task_id}/readiness")
async def submit_readiness_response(
    task_id: str,
    response: ReadinessResponseModel,
    current_user: Dict[str, Any] = Depends(get_current_user)
) -> Dict[str, Any]:
    """Submit a readiness response for a task"""
    user_id = current_user["id"]
    
    # Verify task exists
    tasks = USER_TASKS.get(user_id, {})
    if task_id not in tasks:
        raise HTTPException(status_code=404, detail="Task not found")
    
    # Initialize user responses if needed
    if user_id not in USER_READINESS_RESPONSES:
        USER_READINESS_RESPONSES[user_id] = []
    
    readiness_record = {
        "id": str(next(TASK_ID_COUNTER)),
        "task_id": task_id,
        "user_id": user_id,
        "readiness_level": response.readiness_level,
        "feedback": response.feedback,
        "response_date": _current_timestamp(),
        "created_at": _current_timestamp(),
    }
    
    USER_READINESS_RESPONSES[user_id].append(readiness_record)
    
    # Mark task as completed
    tasks[task_id]["is_completed"] = True
    tasks[task_id]["updated_at"] = _current_timestamp()
    
    return readiness_record


@app.get("/readiness")
async def get_readiness_responses(
    task_id: Optional[str] = None,
    current_user: Dict[str, Any] = Depends(get_current_user)
) -> List[Dict[str, Any]]:
    """Get readiness responses for the current user"""
    user_id = current_user["id"]
    responses = USER_READINESS_RESPONSES.get(user_id, [])
    
    if task_id:
        responses = [r for r in responses if r["task_id"] == task_id]
    
    return responses


@app.get("/tasks/due-today")
async def get_tasks_due_today(
    current_user: Dict[str, Any] = Depends(get_current_user)
) -> List[Dict[str, Any]]:
    """Get tasks due today for the current user"""
    user_id = current_user["id"]
    tasks = USER_TASKS.get(user_id, {})
    
    today = datetime.now(timezone.utc).date().isoformat()
    due_today = [
        task for task in tasks.values()
        if task["due_date"] == today and not task.get("is_completed", False)
    ]
    
    return due_today
