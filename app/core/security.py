import logging
from typing import Optional
from datetime import datetime, timedelta, timezone
from pwdlib import PasswordHash
from app.core.config import settings
import jwt

logger = logging.getLogger(__name__)

# 密码哈希配置对象 - recommended() 选择Argon2id算法
password_hash = PasswordHash.recommended()

def get_password_hash(password: str) -> str:
    """把明文密码转换成不可逆的哈希值"""
    return password_hash.hash(password)

def verify_password(plain_password: str,hashed_password: str) -> bool:
    """验证明文密码是否与数据库中的哈希值匹配"""
    return password_hash.verify(plain_password,hashed_password)

def create_access_token(
    data: dict,
    expires_delta: Optional[timedelta] = None,
) -> str:
    """创建短期JWT访问令牌"""

    now = datetime.now(timezone.utc)
    expire = now + (
        expires_delta
        if expires_delta
        else timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )

    to_encode = data.copy()
    #区分令牌
    to_encode.update({
        "iat": now,
        "exp": expire,
        "type": "access",
    })

    return jwt.encode(
        to_encode,
        settings.SECRET_KEY,
        algorithm=settings.ALGORITHM,
    )

def decode_access_token(token: str) -> Optional[dict]:
    """验证并解码访问令牌"""
    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM],
            options={
                "require": ["exp", "iat", "sub"],
            }
        )

        if payload.get("type") != "access":
            return None

        return payload

    except jwt.InvalidTokenError:
        return None
