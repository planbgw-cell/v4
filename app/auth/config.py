"""
OAuth2 환경 변수. .env에서 Client ID/Secret, Redirect URI 등을 읽음.
"""
import os

from dotenv import load_dotenv

load_dotenv()


def get_google_client_id() -> str:
    return os.getenv("GOOGLE_CLIENT_ID", "").strip()


def get_google_client_secret() -> str:
    return os.getenv("GOOGLE_CLIENT_SECRET", "").strip()


def get_google_redirect_uri() -> str:
    return os.getenv("GOOGLE_REDIRECT_URI", "http://localhost:8000/api/auth/google/callback").strip()


def get_apple_client_id() -> str:
    return os.getenv("APPLE_CLIENT_ID", "").strip()


def get_apple_team_id() -> str:
    return os.getenv("APPLE_TEAM_ID", "").strip()


def get_apple_key_id() -> str:
    return os.getenv("APPLE_KEY_ID", "").strip()


def get_apple_private_key() -> str:
    return os.getenv("APPLE_PRIVATE_KEY", "").strip()


def get_apple_redirect_uri() -> str:
    return os.getenv("APPLE_REDIRECT_URI", "http://localhost:8000/api/auth/apple/callback").strip()


def google_oauth_configured() -> bool:
    return bool(get_google_client_id() and get_google_client_secret())


def apple_oauth_configured() -> bool:
    return bool(get_apple_client_id() and get_apple_private_key())
