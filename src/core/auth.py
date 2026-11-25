"""Authentication module"""

import secrets

import bcrypt
from typing import Optional
from fastapi import Header, HTTPException, Query, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from .config import config

security = HTTPBearer()
optional_security = HTTPBearer(auto_error=False)

DEFAULT_ADMIN_PASSWORD = "admin"
MIN_ADMIN_PASSWORD_LENGTH = 8
MAX_ADMIN_PASSWORD_BYTES = 72  # bcrypt ignores (or rejects) anything longer

# ClientKeyService, wired by the app. Client keys are accepted only by
# verify_api_key_flexible (model listing and generation); every other use of
# the API key, such as the CAPTCHA WebSocket, still requires the master key.
_client_keys = None


def set_client_key_service(service) -> None:
    global _client_keys
    _client_keys = service


def get_client_key_service():
    return _client_keys


class AuthManager:
    """Authentication manager"""

    # True while the stored admin password is still the factory default. Refreshed whenever the
    # configuration is reloaded (bcrypt is too slow to check on every request).
    default_password_active = False

    @staticmethod
    def verify_api_key(api_key: str) -> bool:
        """Verify API key"""
        return secrets.compare_digest(str(api_key or "").encode(), str(config.api_key or "").encode())

    @staticmethod
    def is_hashed(stored: str) -> bool:
        return str(stored or "").startswith("$2")

    @staticmethod
    def password_matches(password: str, stored: str) -> bool:
        """Check a password against a bcrypt hash, or a legacy plain-text value."""
        stored = str(stored or "")
        raw = str(password or "").encode()
        if AuthManager.is_hashed(stored):
            try:
                return bcrypt.checkpw(raw, stored.encode())
            except ValueError:
                return False
        return secrets.compare_digest(raw, stored.encode())

    @staticmethod
    def verify_admin(username: str, password: str) -> bool:
        """Verify admin credentials"""
        # Compare with current config (which may be from database or config file)
        user_ok = secrets.compare_digest(str(username or "").encode(), str(config.admin_username or "").encode())
        return AuthManager.password_matches(password, config.admin_password) and user_ok

    @classmethod
    def refresh_password_state(cls) -> bool:
        cls.default_password_active = cls.password_matches(DEFAULT_ADMIN_PASSWORD, config.admin_password)
        return cls.default_password_active

    @staticmethod
    def validate_new_password(new_password: str, old_password: str = "") -> Optional[str]:
        """Reason a new admin password is refused, or None."""
        value = str(new_password or "")
        if len(value) < MIN_ADMIN_PASSWORD_LENGTH:
            return f"新密码至少 {MIN_ADMIN_PASSWORD_LENGTH} 位"
        if len(value.encode()) > MAX_ADMIN_PASSWORD_BYTES:
            return f"新密码不能超过 {MAX_ADMIN_PASSWORD_BYTES} 字节"
        if value.casefold() == DEFAULT_ADMIN_PASSWORD or value == old_password:
            return "新密码不能是默认密码或与旧密码相同"
        return None

    @staticmethod
    def hash_password(password: str) -> str:
        """Hash password"""
        return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

    @staticmethod
    def verify_password(password: str, hashed: str) -> bool:
        """Verify password"""
        return bcrypt.checkpw(password.encode(), hashed.encode())


async def verify_api_key_header(
    credentials: HTTPAuthorizationCredentials = Security(security),
) -> str:
    """Verify API key from Authorization header"""
    api_key = credentials.credentials
    if not AuthManager.verify_api_key(api_key):
        raise HTTPException(status_code=401, detail="Invalid API key")
    return api_key


async def verify_api_key_flexible(
    credentials: Optional[HTTPAuthorizationCredentials] = Security(optional_security),
    x_goog_api_key: Optional[str] = Header(None, alias="x-goog-api-key"),
    key: Optional[str] = Query(None),
) -> str:
    """Verify API key from Authorization header, x-goog-api-key header, or key query param."""
    api_key = None

    if credentials is not None:
        api_key = credentials.credentials
    elif x_goog_api_key:
        api_key = x_goog_api_key
    elif key:
        api_key = key

    if not api_key or not (
        AuthManager.verify_api_key(api_key)
        or (_client_keys is not None and _client_keys.authenticate(api_key) is not None)
    ):
        raise HTTPException(status_code=401, detail="Invalid API key")

    return api_key
