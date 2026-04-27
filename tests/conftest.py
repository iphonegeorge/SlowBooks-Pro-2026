# ============================================================================
# Test Configuration — SQLite in-memory database + FastAPI TestClient
# ============================================================================

import os

# Set test environment variables BEFORE importing app modules
os.environ["DATABASE_URL"] = "sqlite:///./test.db"
os.environ["JWT_SECRET_KEY"] = "test-secret-key-for-testing-only"
os.environ["ENCRYPTION_KEY"] = ""  # Disable encryption in tests unless testing it

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from app.database import Base, get_db
from app.main import app
from app.models.users import User, UserRole
from app.auth import hash_password, create_access_token


# In-memory SQLite for fast tests
TEST_ENGINE = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSession = sessionmaker(autocommit=False, autoflush=False, bind=TEST_ENGINE)


def override_get_db():
    db = TestSession()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db


@pytest.fixture(autouse=True)
def setup_database():
    """Create all tables before each test, drop after."""
    Base.metadata.create_all(bind=TEST_ENGINE)
    yield
    Base.metadata.drop_all(bind=TEST_ENGINE)


@pytest.fixture
def db():
    """Provide a test database session."""
    session = TestSession()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def admin_user(db):
    """Create an admin user for testing."""
    user = User(
        username="admin",
        email="admin@test.com",
        hashed_password=hash_password("testpass123"),
        role=UserRole.ADMIN,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def auth_token(admin_user):
    """Create a valid JWT token for the admin user."""
    return create_access_token({"sub": admin_user.id, "role": admin_user.role.value})


@pytest.fixture
def client():
    """Unauthenticated test client."""
    return TestClient(app)


@pytest.fixture
def auth_client(auth_token):
    """Authenticated test client with JWT token."""
    c = TestClient(app)
    c.headers["Authorization"] = f"Bearer {auth_token}"
    return c
