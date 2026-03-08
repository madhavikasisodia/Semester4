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
from urllib.parse import urlparse
from uuid import uuid4

import httpx
from fastapi import File, FastAPI, Form, HTTPException, Query, UploadFile
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
    metadata: Optional[Dict[str, Any]] = None

    @field_validator("email")
    @classmethod
    def enforce_email(cls, value: str) -> str:
        return _validate_email(value)


class LoginRequest(BaseModel):
    email: str
    password: str = Field(..., min_length=6, max_length=64)

    @field_validator("email")
    @classmethod
    def enforce_email(cls, value: str) -> str:
        return _validate_email(value)


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


def _parse_origins(raw_origins: Optional[str]) -> List[str]:
    if not raw_origins:
        return ["http://localhost:3000"]
    return [origin.strip() for origin in raw_origins.split(",") if origin.strip()]


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
        supabase_client = create_client(settings.supabase_url, settings.supabase_key)
        logger.info("Supabase client initialized")
    return supabase_client


def _build_user_profile_record(user_id: str, email: str, metadata: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    meta = metadata or {}
    record = {
        "id": user_id,
        "email": _validate_email(email),
        "full_name": meta.get("full_name"),
        "username": meta.get("username"),
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


RECOMMENDATION_ID_COUNTER = count(len(RECOMMENDATIONS) + 1)


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
FILLER_WORDS = {"um", "uh", "like", "you know", "so"}


def _flatten_questions() -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for questions in QUESTION_BANK.values():
        items.extend(questions)
    return items


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


def _select_questions(difficulty: Optional[str], count_questions: int) -> List[Dict[str, Any]]:
    pool = [q for q in _flatten_questions() if not difficulty or q["difficulty"].lower() == difficulty.lower()]
    if len(pool) < count_questions:
        pool = _flatten_questions()
    rng = random.Random()
    return rng.sample(pool, k=min(count_questions, len(pool)))


def _evaluate_answer(question: Dict[str, Any], answer: str) -> Dict[str, Any]:
    tokens = answer.split()
    word_count = len(tokens)
    completeness = min(100, max(40, word_count))
    technical_accuracy = min(100, 60 + word_count // 2)
    clarity = min(100, 55 + word_count // 3)
    has_examples = any(keyword in answer.lower() for keyword in ["for example", "for instance", "e.g."])
    structured = any(keyword in answer.lower() for keyword in ["first", "second", "finally", "approach"])
    feedback = "Solid structure, expand on trade-offs." if structured else "Add more structure and concrete examples."
    follow_ups = [
        f"How would you handle edge cases for {question['title'].lower()}?",
        "What optimizations could improve your solution?",
    ]
    return {
        "question": question["title"],
        "answer": answer,
        "technical_accuracy": technical_accuracy,
        "completeness": completeness,
        "clarity": clarity,
        "has_real_world_examples": has_examples,
        "has_structured_approach": structured,
        "feedback": feedback,
        "follow_up_questions": follow_ups,
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
    confidence_trend = "increasing" if answered > 1 and responses[-1]["clarity"] >= responses[0]["clarity"] else "stable"
    strengths = ["Clear communication", "Structured approach"] if responses else ["Preparation"]
    weaknesses = ["Add more real-world examples"]
    question_perf = []
    for idx, (question, resp) in enumerate(zip(session.get("questions", []), responses), start=1):
        question_perf.append(
            {
                "question_number": idx,
                "question": question["title"],
                "difficulty": question["difficulty"],
                "score": resp["technical_accuracy"],
                "feedback": resp["feedback"],
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
        get_supabase_client()
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
    payload = {"email": request.email, "password": request.password, "options": {"data": request.metadata or {}}}
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
        await _persist_user_profile(client, user.id, request.email, request.metadata)
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


# ----------------------- Profile & Social APIs -----------------------


@app.get("/leetcode/{username}")
async def get_leetcode_profile(username: str) -> Dict[str, Any]:
    return await _fetch_leetcode_profile(username)


@app.get("/github/{username}")
async def get_github_profile(username: str) -> Dict[str, Any]:
    return await _fetch_github_profile(username)


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


# ----------------------- Learning Management APIs -----------------------


@app.get("/recommendations")
async def get_recommendations(status: Optional[str] = None, priority: Optional[str] = None) -> List[Dict[str, Any]]:
    items = RECOMMENDATIONS
    if status:
        items = [rec for rec in items if rec["status"].lower() == status.lower()]
    if priority:
        items = [rec for rec in items if rec["priority"].lower() == priority.lower()]
    return items


@app.post("/recommendations/generate")
async def generate_recommendations() -> Dict[str, str]:
    rec_id = next(RECOMMENDATION_ID_COUNTER)
    suggestion = random.choice(list(QUESTION_BANK.keys()))
    new_rec = {
        "id": rec_id,
        "user_id": 1,
        "title": f"Deep dive into {suggestion}",
        "description": f"Focus on strengthening your {suggestion} fundamentals this week.",
        "category": suggestion.title(),
        "priority": random.choice(["high", "medium", "low"]),
        "source": "AI Planner",
        "resources": [
            {"title": "Curated playlist", "url": "https://roadmap.sh"},
        ],
        "estimated_time": "5 hours",
        "status": "pending",
        "created_at": _current_timestamp(),
        "completed_at": None,
    }
    RECOMMENDATIONS.append(new_rec)
    return {"message": "New recommendations generated."}


@app.put("/recommendations/{rec_id}/status")
async def update_recommendation_status(rec_id: int, status: str = Query(...)) -> Dict[str, str]:
    for rec in RECOMMENDATIONS:
        if rec["id"] == rec_id:
            rec["status"] = status.lower()
            if status.lower() == "completed":
                rec["completed_at"] = _current_timestamp()
            return {"message": "Recommendation updated."}
    raise HTTPException(status_code=404, detail="Recommendation not found")


@app.get("/progress/stats")
async def get_progress_stats() -> Dict[str, Any]:
    return _calculate_progress_stats()


@app.get("/progress/history")
async def get_progress_history(days: int = Query(30, ge=1, le=180)) -> List[Dict[str, Any]]:
    cutoff = _utcnow().date() - timedelta(days=days - 1)
    return [record for record in PROGRESS_HISTORY if datetime.fromisoformat(record["date"]).date() >= cutoff]


@app.get("/achievements")
async def get_achievements() -> List[Dict[str, Any]]:
    return ACHIEVEMENTS


@app.get("/dashboard/overview")
async def get_dashboard_overview() -> Dict[str, Any]:
    return {
        "resumes": RESUMES,
        "test_scores": TEST_SCORES,
        "certifications": CERTIFICATIONS,
        "recommendations": RECOMMENDATIONS,
        "progress_stats": _calculate_progress_stats(),
    }


# ----------------------- Agent Automation APIs -----------------------


@app.get("/agents")
async def list_agents() -> Dict[str, Any]:
    return {"agents": AGENT_CATALOG}


@app.get("/agents/runs")
async def list_agent_runs(limit: int = Query(10, ge=1, le=50)) -> Dict[str, Any]:
    runs = sorted(AGENT_RUNS.values(), key=lambda entry: entry["created_at"], reverse=True)
    return {"runs": runs[:limit]}


@app.get("/agents/runs/{run_id}")
async def get_agent_run(run_id: str) -> Dict[str, Any]:
    entry = AGENT_RUNS.get(run_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Agent run not found")
    return entry


@app.post("/agents/run")
async def run_agent(request: AgentRunRequest) -> Dict[str, Any]:
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
async def upload_resume(file: UploadFile = File(...)) -> Dict[str, Any]:
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
async def analyze_resume(resume_id: int) -> Dict[str, Any]:
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
async def list_resumes() -> List[Dict[str, Any]]:
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
) -> Dict[str, Any]:
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
async def list_certificates() -> List[Dict[str, Any]]:
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
async def start_interview(request: InterviewStartRequest) -> Dict[str, Any]:
    persona = next((p for p in INTERVIEW_PERSONAS if p["persona_id"] == request.persona), None)
    if persona is None:
        raise HTTPException(status_code=404, detail="Persona not found")
    session_id = str(uuid4())
    questions = _select_questions(request.difficulty, count_questions=5)
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
) -> Dict[str, Any]:
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
async def interview_status(session_id: str) -> Dict[str, Any]:
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
async def interview_report(session_id: str) -> Dict[str, Any]:
    session = _get_session_or_404(session_id)
    return _build_interview_report(session)


@app.delete("/interview/{session_id}")
async def delete_interview(session_id: str) -> Dict[str, str]:
    _get_session_or_404(session_id)
    INTERVIEW_SESSIONS.pop(session_id, None)
    return {"message": "Interview session deleted"}


@app.get("/interview/sessions/active")
async def active_sessions() -> Dict[str, Any]:
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
) -> Dict[str, Any]:
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
