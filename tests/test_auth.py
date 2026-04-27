# ============================================================================
# Auth Tests — login, registration, token validation, protected endpoints
# ============================================================================


def test_register_first_user(client):
    """First user registration should succeed (bootstrap admin)."""
    resp = client.post("/api/auth/register", json={
        "username": "admin", "email": "admin@test.com", "password": "securepass123",
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["username"] == "admin"
    assert data["role"] == "admin"


def test_register_second_user_blocked(client, admin_user):
    """Registration should be blocked after first user exists."""
    resp = client.post("/api/auth/register", json={
        "username": "hacker", "email": "hacker@test.com", "password": "sneaky",
    })
    assert resp.status_code == 403


def test_login_valid(client, admin_user):
    """Login with correct credentials returns JWT."""
    resp = client.post("/api/auth/login", json={
        "username": "admin", "password": "testpass123",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    assert data["user"]["username"] == "admin"


def test_login_wrong_password(client, admin_user):
    """Login with wrong password returns 401."""
    resp = client.post("/api/auth/login", json={
        "username": "admin", "password": "wrong",
    })
    assert resp.status_code == 401


def test_login_nonexistent_user(client):
    """Login with nonexistent user returns 401."""
    resp = client.post("/api/auth/login", json={
        "username": "nobody", "password": "test",
    })
    assert resp.status_code == 401


def test_protected_endpoint_no_token(client):
    """Accessing protected endpoint without token returns 401."""
    resp = client.get("/api/accounts")
    assert resp.status_code == 401


def test_protected_endpoint_with_token(auth_client):
    """Accessing protected endpoint with valid token succeeds."""
    resp = auth_client.get("/api/accounts")
    assert resp.status_code == 200


def test_protected_endpoint_bad_token(client):
    """Accessing protected endpoint with invalid token returns 401."""
    client.headers["Authorization"] = "Bearer invalid-token-here"
    resp = client.get("/api/accounts")
    assert resp.status_code == 401


def test_me_endpoint(auth_client):
    """/auth/me returns current user info."""
    resp = auth_client.get("/api/auth/me")
    assert resp.status_code == 200
    data = resp.json()
    assert data["username"] == "admin"
    assert data["role"] == "admin"


def test_refresh_token(auth_client):
    """Token refresh returns new valid token."""
    resp = auth_client.post("/api/auth/refresh")
    assert resp.status_code == 200
    assert "access_token" in resp.json()
