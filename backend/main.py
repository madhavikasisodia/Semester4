import logging
import os
from functools import lru_cache
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr, Field
from supabase import Client, create_client
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class SignUpRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=6, max_length=64)
    metadata: Optional[Dict[str, Any]] = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=6, max_length=64)


class AuthResponse(BaseModel):
    user_id: str
    email: EmailStr
    message: str
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None


class HealthResponse(BaseModel):
    status: str


class Settings(BaseModel):
    supabase_url: str
    supabase_key: str
    cors_origins: List[str]


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


app = FastAPI(
    title="Supabase Auth API",
    description="Login and sign-up endpoints backed by Supabase Auth",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_parse_origins(os.getenv("ALLOWED_ORIGINS")),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)


@app.on_event("startup")
async def startup_event() -> None:
    try:
        get_supabase_client()
    except RuntimeError as exc:
        logger.error("Startup aborted: %s", exc)
        raise


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
