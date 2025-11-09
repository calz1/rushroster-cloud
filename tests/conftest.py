"""Shared test fixtures for web UI tests.

This module contains pytest fixtures used across multiple test files.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from main import app
from src.database.models import Base
from src.database.session import get_db
from src.database import crud
from src.auth_utils import hash_password


# ============================================================================
# Test Database Setup
# ============================================================================

@pytest.fixture(scope="function")
def test_db():
    """Create a test database for each test."""
    # Use in-memory SQLite for testing
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    # Create tables
    Base.metadata.create_all(bind=engine)

    # Override the get_db dependency
    def override_get_db():
        try:
            db = TestingSessionLocal()
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    yield TestingSessionLocal()

    # Cleanup
    Base.metadata.drop_all(bind=engine)
    app.dependency_overrides.clear()


@pytest.fixture(scope="function")
def client(test_db):
    """Create a test client."""
    return TestClient(app)


@pytest.fixture(scope="function")
def test_user(test_db):
    """Create a test user."""
    user = crud.create_user(
        test_db,
        email="testuser@example.com",
        password_hash=hash_password("testpassword123")
    )
    crud.create_user_preferences(test_db, user.id)
    return user


@pytest.fixture(scope="function")
def test_device(test_db, test_user):
    """Create a test device."""
    from src.auth_utils import generate_api_key, hash_api_key
    api_key = generate_api_key()
    api_key_hash = hash_api_key(api_key)

    device = crud.create_device(
        test_db,
        device_id="test-device-001",
        owner_id=test_user.id,
        api_key_hash=api_key_hash,
        latitude=40.7128,
        longitude=-74.0060,
        street_name="Main Street",
        speed_limit=25.0,
        share_community=False
    )

    # Create API key record
    crud.create_device_api_key(test_db, device.id, api_key_hash, name="Test API Key")

    return device, api_key


@pytest.fixture(scope="function")
def authenticated_client(client, test_user):
    """Create an authenticated test client with session cookie."""
    # Login
    response = client.post(
        "/auth/login",
        data={
            "email": "testuser@example.com",
            "password": "testpassword123"
        }
    )
    assert response.status_code == 200
    assert response.json()["success"] is True

    # Extract session cookie
    cookies = response.cookies
    return client, cookies


@pytest.fixture(scope="function")
def test_registration_code(test_db):
    """Create a test registration code."""
    from datetime import datetime, timedelta
    code = crud.create_registration_code(
        test_db,
        code="TEST2024",
        max_uses=5,
        expires_at=datetime.now() + timedelta(days=30),
        description="Test registration code"
    )
    return code


@pytest.fixture(scope="function")
def test_single_use_code(test_db):
    """Create a single-use registration code."""
    code = crud.create_registration_code(
        test_db,
        code="SINGLE123",
        max_uses=1,
        description="Single use code"
    )
    return code


@pytest.fixture(scope="function")
def test_expired_code(test_db):
    """Create an expired registration code."""
    from datetime import datetime, timedelta
    code = crud.create_registration_code(
        test_db,
        code="EXPIRED",
        max_uses=10,
        expires_at=datetime.now() - timedelta(days=1),
        description="Expired code"
    )
    return code


@pytest.fixture(scope="function")
def test_inactive_code(test_db):
    """Create an inactive registration code."""
    code = crud.create_registration_code(
        test_db,
        code="INACTIVE",
        max_uses=10,
        description="Inactive code"
    )
    code.is_active = False
    test_db.commit()
    return code


@pytest.fixture(scope="function")
def admin_user(test_db):
    """Create an admin user."""
    user = crud.create_user(
        test_db,
        email="admin@example.com",
        password_hash=hash_password("adminpassword123"),
        is_admin=True
    )
    crud.create_user_preferences(test_db, user.id)
    return user


@pytest.fixture(scope="function")
def authenticated_admin_client(client, admin_user):
    """Create an authenticated admin client with session cookie."""
    # Login
    response = client.post(
        "/auth/login",
        data={
            "email": "admin@example.com",
            "password": "adminpassword123"
        }
    )
    assert response.status_code == 200
    assert response.json()["success"] is True

    # Extract session cookie
    cookies = response.cookies
    return client, cookies
