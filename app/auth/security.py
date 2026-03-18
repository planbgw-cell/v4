"""
비밀번호 해싱(bcrypt) 및 JWT(python-jose) 유틸.
"""
import os
from datetime import datetime, timedelta, timezone
from uuid import UUID

import bcrypt
from jose import JWTError, jwt

# JWT
SECRET_KEY = os.getenv("SECRET_KEY", "flairy_v4_development_secret")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24  # 24시간


def hash_password(plain: str) -> str:
    """평문 비밀번호를 bcrypt로 해싱."""
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """평문과 해시 비교."""
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


def create_access_token(subject: str | UUID, expires_delta: timedelta | None = None) -> str:
    """JWT access_token 발급. subject는 보통 user_id 문자열."""
    to_encode = {"sub": str(subject), "exp": datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))}
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def decode_access_token(token: str) -> str | None:
    """JWT 검증 후 sub(user_id) 반환. 실패 시 None."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload.get("sub")
    except JWTError:
        return None
