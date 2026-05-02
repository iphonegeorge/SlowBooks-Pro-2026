# ============================================================================
# Authentication — JWT token management, password hashing, FastAPI dependencies
# ============================================================================

import os
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.limiter import limiter
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.users import User, UserRole

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SECRET_KEY = os.getenv("JWT_SECRET_KEY", "change-me-in-production-use-a-real-secret")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", "480"))  # 8 hours
ALLOW_REGISTRATION = os.getenv("ALLOW_REGISTRATION", "true").lower() in ("true", "1", "yes")
MAX_LOGIN_ATTEMPTS = int(os.getenv("MAX_LOGIN_ATTEMPTS", "5"))
LOGIN_LOCKOUT_MINUTES = int(os.getenv("LOGIN_LOCKOUT_MINUTES", "15"))

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer(auto_error=False)

# ---------------------------------------------------------------------------
# Password utilities
# ---------------------------------------------------------------------------


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


# ---------------------------------------------------------------------------
# JWT utilities
# ---------------------------------------------------------------------------


def create_access_token(data: dict, expires_delta: timedelta = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> dict:
    return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])


# ---------------------------------------------------------------------------
# FastAPI dependencies
# ---------------------------------------------------------------------------


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
) -> User:
    """Dependency that extracts and validates the JWT, returning the User."""
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        payload = decode_token(credentials.credentials)
        sub = payload.get("sub")
        if sub is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
        user_id = int(sub)
        if not user_id:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")

    user = db.query(User).filter(User.id == user_id, User.is_active == True).first()
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or inactive")
    return user


def require_role(*roles: UserRole):
    """Dependency factory — restricts endpoint to specific roles."""
    def _check(current_user: User = Depends(get_current_user)):
        if current_user.role not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
        return current_user
    return _check


# ---------------------------------------------------------------------------
# Auth router (login, register, me, refresh)
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


class RegisterRequest(BaseModel):
    username: str
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict


class UserResponse(BaseModel):
    id: int
    username: str
    email: str
    role: str
    is_active: bool


@router.post("/login", response_model=TokenResponse)
@limiter.limit("5/minute")
def login(request: Request, data: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == data.username).first()

    # Check account lockout
    if user and user.locked_until:
        now = datetime.now(timezone.utc)
        if now < user.locked_until:
            remaining = int((user.locked_until - now).total_seconds() // 60) + 1
            raise HTTPException(
                status_code=status.HTTP_423_LOCKED,
                detail=f"Account locked. Try again in {remaining} minute(s).",
            )
        # Lockout expired — reset
        user.failed_login_attempts = 0
        user.locked_until = None
        db.commit()

    if not user or not verify_password(data.password, user.hashed_password):
        # Track failed attempts
        if user:
            user.failed_login_attempts = (user.failed_login_attempts or 0) + 1
            if user.failed_login_attempts >= MAX_LOGIN_ATTEMPTS:
                user.locked_until = datetime.now(timezone.utc) + timedelta(minutes=LOGIN_LOCKOUT_MINUTES)
            db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Account is disabled")

    # Successful login — reset failed attempts
    if user.failed_login_attempts:
        user.failed_login_attempts = 0
        user.locked_until = None
        db.commit()

    token = create_access_token({"sub": str(user.id), "role": user.role.value})
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {"id": user.id, "username": user.username, "email": user.email, "role": user.role.value},
    }


def _validate_password(password: str):
    """Enforce password complexity: min 8 chars, must contain upper, lower, and digit."""
    if len(password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")
    if len(password.encode("utf-8")) > 72:
        raise HTTPException(status_code=400, detail="Password too long (max 72 bytes for bcrypt)")
    if not any(c.isupper() for c in password):
        raise HTTPException(status_code=400, detail="Password must contain at least one uppercase letter")
    if not any(c.islower() for c in password):
        raise HTTPException(status_code=400, detail="Password must contain at least one lowercase letter")
    if not any(c.isdigit() for c in password):
        raise HTTPException(status_code=400, detail="Password must contain at least one digit")


@router.post("/register", response_model=UserResponse, status_code=201)
@limiter.limit("3/minute")
def register(request: Request, data: RegisterRequest, db: Session = Depends(get_db)):
    # Check if registration is disabled via env var
    if not ALLOW_REGISTRATION:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Registration is disabled. Contact your administrator.",
        )
    _validate_password(data.password)
    # Only allow registration if no users exist (first-run setup)
    user_count = db.query(User).count()
    if user_count > 0:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Registration disabled. Ask an admin to create your account.",
        )
    user = User(
        username=data.username,
        email=data.email,
        hashed_password=hash_password(data.password),
        role=UserRole.ADMIN,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return UserResponse(id=user.id, username=user.username, email=user.email, role=user.role.value, is_active=True)


@router.post("/users", response_model=UserResponse, status_code=201)
def create_user(
    data: RegisterRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.ADMIN)),
):
    """Admin-only: create a new user."""
    _validate_password(data.password)
    existing = db.query(User).filter(
        (User.username == data.username) | (User.email == data.email)
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Username or email already exists")
    user = User(
        username=data.username,
        email=data.email,
        hashed_password=hash_password(data.password),
        role=UserRole.USER,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return UserResponse(id=user.id, username=user.username, email=user.email, role=user.role.value, is_active=True)


@router.get("/status")
def auth_status(db: Session = Depends(get_db)):
    """Public endpoint — tells the frontend whether admin setup is needed."""
    user_count = db.query(User).count()
    return {
        "needs_setup": user_count == 0 and ALLOW_REGISTRATION,
        "registration_allowed": ALLOW_REGISTRATION,
        "user_count": user_count,
    }


def seed_admin_from_env(db: Session) -> bool:
    """Create admin user from ADMIN_USERNAME/ADMIN_PASSWORD env vars if no users exist.
    Called once at startup. Returns True if a user was created."""
    username = os.getenv("ADMIN_USERNAME")
    password = os.getenv("ADMIN_PASSWORD")
    if not username or not password:
        return False
    if db.query(User).count() > 0:
        return False
    if len(password) < 8:
        import logging
        logging.getLogger(__name__).warning("ADMIN_PASSWORD must be at least 8 characters — skipping admin seed")
        return False
    email = os.getenv("ADMIN_EMAIL", f"{username}@localhost")
    user = User(
        username=username,
        email=email,
        hashed_password=hash_password(password),
        role=UserRole.ADMIN,
    )
    db.add(user)
    db.commit()
    return True


@router.get("/me", response_model=UserResponse)
def get_me(current_user: User = Depends(get_current_user)):
    return UserResponse(
        id=current_user.id, username=current_user.username,
        email=current_user.email, role=current_user.role.value,
        is_active=current_user.is_active,
    )


@router.post("/refresh", response_model=TokenResponse)
def refresh_token(current_user: User = Depends(get_current_user)):
    token = create_access_token({"sub": str(current_user.id), "role": current_user.role.value})
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "id": current_user.id, "username": current_user.username,
            "email": current_user.email, "role": current_user.role.value,
        },
    }
