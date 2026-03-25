import logging
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator
from typing import Any, Dict, List, Optional
from app.core.firebase import get_current_user_claims, get_current_user_uid
from app.models.user import User, UserRole
from app.utils.caregiver_links import sync_invited_links
from datetime import datetime

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])


MAX_DISPLAY_NAME_LENGTH = 100
MAX_PHOTO_URL_LENGTH = 500


class RegisterRequest(BaseModel):
    display_name: str = ""
    photo_url: str = ""

    @field_validator('display_name')
    @classmethod
    def validate_display_name(cls, v: str) -> str:
        if v and len(v) > MAX_DISPLAY_NAME_LENGTH:
            raise ValueError(f'Display name cannot exceed {MAX_DISPLAY_NAME_LENGTH} characters')
        return v.strip() if v else ""

    @field_validator('photo_url')
    @classmethod
    def validate_photo_url(cls, v: str) -> str:
        if v and len(v) > MAX_PHOTO_URL_LENGTH:
            raise ValueError(f'Photo URL cannot exceed {MAX_PHOTO_URL_LENGTH} characters')
        
        if v and not v.startswith(('http://', 'https://')):
            raise ValueError('Photo URL must start with http:// or https://')
        return v.strip() if v else ""


class UpdateProfileRequest(BaseModel):
    display_name: Optional[str] = None
    photo_url: Optional[str] = None

    @field_validator('display_name')
    @classmethod
    def validate_display_name(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            if len(v) > MAX_DISPLAY_NAME_LENGTH:
                raise ValueError(f'Display name cannot exceed {MAX_DISPLAY_NAME_LENGTH} characters')
            return v.strip()
        return v

    @field_validator('photo_url')
    @classmethod
    def validate_photo_url(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            if len(v) > MAX_PHOTO_URL_LENGTH:
                raise ValueError(f'Photo URL cannot exceed {MAX_PHOTO_URL_LENGTH} characters')
            if v and not v.startswith(('http://', 'https://')):
                raise ValueError('Photo URL must start with http:// or https://')
            return v.strip()
        return v


class UserResponse(BaseModel):
    id: str
    firebase_uid: str
    email: str
    display_name: str
    photo_url: str
    role: str
    linked_patients: List[str]
    is_onboarded: bool
    is_banned: bool


#------This Function registers a user---------
@router.post("/register", response_model=UserResponse)
async def register(
    body: RegisterRequest,
    claims: Dict[str, Any] = Depends(get_current_user_claims),
):
    try:
        uid = _get_verified_uid(claims)
        verified_email = _get_verified_email(claims)
        resolved_name = _normalize_display_name(body.display_name or _get_optional_claim_string(claims, "name"))
        resolved_photo = _normalize_photo_url(body.photo_url or _get_optional_claim_string(claims, "picture"))

        existing = await User.find_one(User.firebase_uid == uid)
        if existing:
            if existing.is_banned:
                logger.warning(f"Banned user attempted registration: {uid}")
                raise HTTPException(status_code=403, detail="Account banned")

            changed = False
            if existing.email != verified_email:
                existing.email = verified_email
                changed = True
            if resolved_name and existing.display_name != resolved_name:
                existing.display_name = resolved_name
                changed = True
            if resolved_photo and existing.photo_url != resolved_photo:
                existing.photo_url = resolved_photo
                changed = True
            if await sync_invited_links(existing):
                changed = True
            if changed:
                existing.updated_at = datetime.utcnow()
                await existing.save()
            return _to_response(existing)

        user = User(
            firebase_uid=uid,
            email=verified_email,
            display_name=resolved_name,
            photo_url=resolved_photo,
            role=UserRole.PATIENT,
            linked_patients=[],
        )
        await sync_invited_links(user)
        await user.insert()
        logger.info(f"New user registered: {uid} with role {user.role.value}")
        return _to_response(user)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to register user {uid}: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to register user")


#------This Function gets current user---------
@router.get("/me", response_model=UserResponse)
async def get_me(uid: str = Depends(get_current_user_uid)):
    try:
        user = await User.find_one(User.firebase_uid == uid)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        if user.is_banned:
            raise HTTPException(status_code=403, detail="Account banned")
        return _to_response(user)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get user profile {uid}: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to retrieve user profile")


#------This Function updates profile---------
@router.put("/me", response_model=UserResponse)
async def update_profile(
    body: UpdateProfileRequest,
    uid: str = Depends(get_current_user_uid)
):
    try:
        user = await User.find_one(User.firebase_uid == uid)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        if user.is_banned:
            raise HTTPException(status_code=403, detail="Account banned")
        
        
        if body.display_name is not None:
            user.display_name = body.display_name
        if body.photo_url is not None:
            user.photo_url = body.photo_url
        
        user.updated_at = datetime.utcnow()
        await user.save()
        logger.info(f"Updated profile for user {uid}")
        return _to_response(user)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update profile for user {uid}: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to update profile")


#------This Function converts user to response---------
def _to_response(user: User) -> UserResponse:
    return UserResponse(
        id=str(user.id),
        firebase_uid=user.firebase_uid,
        email=user.email,
        display_name=user.display_name,
        photo_url=user.photo_url,
        role=user.role.value,
        linked_patients=user.linked_patients,
        is_onboarded=user.is_onboarded,
        is_banned=user.is_banned,
    )


#------This Function resolves a required verified UID---------
def _get_verified_uid(claims: Dict[str, Any]) -> str:
    uid = claims.get("uid") or claims.get("user_id") or claims.get("sub")
    if isinstance(uid, str) and uid.strip():
        return uid.strip()
    raise HTTPException(status_code=401, detail="Invalid or expired token")


#------This Function resolves a required verified email---------
def _get_verified_email(claims: Dict[str, Any]) -> str:
    email = claims.get("email")
    if not isinstance(email, str) or not email.strip():
        raise HTTPException(status_code=400, detail="Verified email is required")
    if claims.get("email_verified") is False:
        raise HTTPException(status_code=403, detail="Email must be verified")
    return email.strip().lower()


#------This Function resolves an optional string claim---------
def _get_optional_claim_string(claims: Dict[str, Any], key: str) -> str:
    value = claims.get(key)
    return value.strip() if isinstance(value, str) else ""


#------This Function normalizes display name values---------
def _normalize_display_name(value: str) -> str:
    if value and len(value) > MAX_DISPLAY_NAME_LENGTH:
        return value[:MAX_DISPLAY_NAME_LENGTH].strip()
    return value.strip() if value else ""


#------This Function normalizes photo URL values---------
def _normalize_photo_url(value: str) -> str:
    if not value:
        return ""
    trimmed = value.strip()
    if len(trimmed) > MAX_PHOTO_URL_LENGTH:
        trimmed = trimmed[:MAX_PHOTO_URL_LENGTH].strip()
    if not trimmed.startswith(("http://", "https://")):
        return ""
    return trimmed
