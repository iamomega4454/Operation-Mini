import logging
import os
import time
from typing import Any, Dict, Optional

import firebase_admin
import jwt
from firebase_admin import auth as firebase_auth
from firebase_admin import credentials
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token

from app.core.config import settings

logger = logging.getLogger(__name__)

_bearer = HTTPBearer()
_app = None
_google_request: Optional[google_requests.Request] = None
_use_firebase_admin_verification = True
_verified_token_cache: Dict[str, Dict[str, Any]] = {}
_TOKEN_CACHE_MAX_SIZE = 1024
_TOKEN_CACHE_EXP_SKEW_SECONDS = 5


#------This Function creates a reusable request adapter for Google cert verification---------
def _get_google_request() -> google_requests.Request:
    global _google_request
    if _google_request is None:
        _google_request = google_requests.Request()
    return _google_request


#------This Function decodes JWT claims without signature checks---------
def _decode_unverified_claims(token: str) -> Dict[str, Any]:
    try:
        decoded = jwt.decode(
            token,
            options={
                "verify_signature": False,
                "verify_exp": False,
                "verify_aud": False,
                "verify_iss": False,
            },
        )
        if isinstance(decoded, dict):
            return decoded
    except Exception:
        pass
    return {}


#------This Function resolves Firebase project ID for strict token verification---------
def _resolve_project_id(token: str) -> str:
    configured = (settings.firebase_project_id or "").strip()
    if configured:
        return configured

    env_project = os.getenv("GOOGLE_CLOUD_PROJECT", "").strip() or os.getenv("GCLOUD_PROJECT", "").strip()
    if env_project:
        return env_project

    claims = _decode_unverified_claims(token)
    audience = claims.get("aud")
    if isinstance(audience, str):
        return audience.strip()

    return ""


#------This Function verifies Firebase token via Google public certs---------
def _verify_token_with_google_public_keys(token: str) -> Optional[Dict[str, Any]]:
    project_id = _resolve_project_id(token)
    if not project_id:
        return None

    try:
        decoded = google_id_token.verify_firebase_token(
            token,
            _get_google_request(),
            audience=project_id,
            clock_skew_in_seconds=60,
        )
        if not isinstance(decoded, dict):
            return None

        expected_issuer = f"https://securetoken.google.com/{project_id}"
        issuer = decoded.get("iss")
        if issuer != expected_issuer:
            logger.warning("Firebase token issuer mismatch: expected=%s got=%s", expected_issuer, issuer)
            return None

        return decoded
    except Exception as exc:
        logger.warning("Google cert token verification failed: %s", exc)
        return None


#------This Function returns cached claims for a previously verified token---------
def _get_cached_verified_claims(token: str) -> Optional[Dict[str, Any]]:
    cached = _verified_token_cache.get(token)
    if not cached:
        return None

    expires_at = cached.get("expires_at")
    if not isinstance(expires_at, int):
        _verified_token_cache.pop(token, None)
        return None

    if expires_at <= int(time.time()) + _TOKEN_CACHE_EXP_SKEW_SECONDS:
        _verified_token_cache.pop(token, None)
        return None

    claims = cached.get("claims")
    if isinstance(claims, dict):
        return claims

    _verified_token_cache.pop(token, None)
    return None


#------This Function stores verified token claims until token expiry---------
def _cache_verified_claims(token: str, claims: Dict[str, Any]) -> None:
    exp_claim = claims.get("exp")
    if not isinstance(exp_claim, (int, float)):
        return

    expires_at = int(exp_claim)
    if expires_at <= int(time.time()) + _TOKEN_CACHE_EXP_SKEW_SECONDS:
        return

    if len(_verified_token_cache) >= _TOKEN_CACHE_MAX_SIZE:
        oldest_key = next(iter(_verified_token_cache))
        _verified_token_cache.pop(oldest_key, None)

    _verified_token_cache[token] = {
        "expires_at": expires_at,
        "claims": claims,
    }


#------This Function extracts the Firebase UID from verified claims---------
def _extract_uid_from_claims(claims: Dict[str, Any]) -> Optional[str]:
    uid = claims.get("uid") or claims.get("user_id") or claims.get("sub")
    if isinstance(uid, str) and uid.strip():
        return uid.strip()
    return None


#------This Function initializes Firebase---------
def init_firebase():
    global _app, _use_firebase_admin_verification
    if _app:
        return
    cred_path = settings.firebase_credentials_path
    configured_project_id = (settings.firebase_project_id or "").strip()

    if os.path.exists(cred_path):
        cred = credentials.Certificate(cred_path)
        if configured_project_id:
            _app = firebase_admin.initialize_app(cred, options={"projectId": configured_project_id})
        else:
            _app = firebase_admin.initialize_app(cred)
        _use_firebase_admin_verification = True
        return

    if configured_project_id:
        _app = firebase_admin.initialize_app(options={"projectId": configured_project_id})
        _use_firebase_admin_verification = False
        logger.warning(
            "Firebase credentials file not found at %s. Using FIREBASE_PROJECT_ID=%s for token verification.",
            cred_path,
            configured_project_id,
        )
        return

    _app = firebase_admin.initialize_app()
    _use_firebase_admin_verification = False
    logger.warning(
        "Firebase credentials file not found at %s and FIREBASE_PROJECT_ID is empty. "
        "Token verification will rely on token audience fallback.",
        cred_path,
    )


#------This Function verifies the current token and returns claims---------
async def get_current_user_claims(
    creds: HTTPAuthorizationCredentials = Depends(_bearer),
) -> Dict[str, Any]:
    global _use_firebase_admin_verification
    token = creds.credentials.strip()
    decoded: Optional[Dict[str, Any]] = None

    cached_claims = _get_cached_verified_claims(token)
    if cached_claims:
        uid = _extract_uid_from_claims(cached_claims)
        if uid:
            return cached_claims

    if _use_firebase_admin_verification:
        try:
            decoded = firebase_auth.verify_id_token(
                token,
                check_revoked=False,
                clock_skew_seconds=60,
            )
        except Exception as exc:
            logger.warning("firebase_admin token verification failed: %s", exc)
            if "default credentials were not found" in str(exc).lower():
                _use_firebase_admin_verification = False
            decoded = _verify_token_with_google_public_keys(token)
    else:
        decoded = _verify_token_with_google_public_keys(token)

    uid = None
    if decoded:
        _cache_verified_claims(token, decoded)
        uid = _extract_uid_from_claims(decoded)

    if not isinstance(uid, str) or not uid.strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )

    return decoded


#------This Function gets the current user UID from token---------
async def get_current_user_uid(
    claims: Dict[str, Any] = Depends(get_current_user_claims),
) -> str:
    uid = _extract_uid_from_claims(claims)
    if not uid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )
    return uid
