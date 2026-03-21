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


def get_kakao_client_id() -> str:
    return os.getenv("KAKAO_CLIENT_ID", "").strip()


def get_kakao_client_secret() -> str:
    return os.getenv("KAKAO_CLIENT_SECRET", "").strip()


def get_kakao_redirect_uri() -> str:
    # Kakao 콘솔 설정 필요:
    # - 제품 설정 > 카카오 로그인 > 활성화 ON
    # - Redirect URI: http://121.133.47.184:8000/api/auth/kakao/callback
    return os.getenv("KAKAO_REDIRECT_URI", "http://localhost:8000/api/auth/kakao/callback").strip()


def google_oauth_configured() -> bool:
    return bool(get_google_client_id() and get_google_client_secret())


def kakao_oauth_configured() -> bool:
    return bool(get_kakao_client_id() and get_kakao_client_secret())
