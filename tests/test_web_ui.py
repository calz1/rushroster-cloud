"""Integration tests for the web UI dashboard.

This module tests the complete web dashboard flow including:
- Authentication (registration, login, logout)
- Dashboard homepage
- Device management
- Event browsing
- Statistics dashboard
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


# ============================================================================
# Authentication Tests
# ============================================================================

class TestAuthentication:
    """Test authentication flows."""

    def test_login_page_loads(self, client):
        """Test that login page loads correctly."""
        response = client.get("/auth/login")
        assert response.status_code == 200
        assert b"Sign in to your account" in response.content
        assert b"RushRoster Cloud" in response.content

    def test_register_page_loads(self, client):
        """Test that registration page loads correctly."""
        response = client.get("/auth/register")
        assert response.status_code == 200
        assert b"Create your account" in response.content

    def test_user_registration(self, client):
        """Test user registration."""
        response = client.post(
            "/auth/register",
            data={
                "email": "newuser@example.com",
                "password": "newpassword123",
                "confirm_password": "newpassword123"
            }
        )
        assert response.status_code == 200
        assert response.json()["success"] is True
        assert "created successfully" in response.json()["message"].lower()

    def test_registration_password_mismatch(self, client):
        """Test registration fails with mismatched passwords."""
        response = client.post(
            "/auth/register",
            data={
                "email": "newuser@example.com",
                "password": "password123",
                "confirm_password": "different123"
            }
        )
        assert response.status_code == 400
        assert response.json()["success"] is False
        assert "do not match" in response.json()["message"].lower()

    def test_registration_short_password(self, client):
        """Test registration fails with short password."""
        response = client.post(
            "/auth/register",
            data={
                "email": "newuser@example.com",
                "password": "short",
                "confirm_password": "short"
            }
        )
        assert response.status_code == 400
        assert response.json()["success"] is False
        assert "8 characters" in response.json()["message"].lower()

    def test_registration_duplicate_email(self, client, test_user):
        """Test registration fails with duplicate email."""
        response = client.post(
            "/auth/register",
            data={
                "email": "testuser@example.com",
                "password": "password123",
                "confirm_password": "password123"
            }
        )
        assert response.status_code == 400
        assert response.json()["success"] is False
        assert "already registered" in response.json()["message"].lower()

    def test_user_login(self, client, test_user):
        """Test user login."""
        response = client.post(
            "/auth/login",
            data={
                "email": "testuser@example.com",
                "password": "testpassword123"
            }
        )
        assert response.status_code == 200
        assert response.json()["success"] is True
        assert "rushroster_session" in response.cookies

    def test_login_invalid_credentials(self, client, test_user):
        """Test login fails with invalid credentials."""
        response = client.post(
            "/auth/login",
            data={
                "email": "testuser@example.com",
                "password": "wrongpassword"
            }
        )
        assert response.status_code == 401
        assert response.json()["success"] is False

    def test_logout(self, authenticated_client):
        """Test logout."""
        client, cookies = authenticated_client
        response = client.get("/logout", cookies=cookies, follow_redirects=False)
        assert response.status_code == 302
        assert response.headers["location"] == "/auth/login"


# ============================================================================
# Dashboard Tests
# ============================================================================

class TestDashboard:
    """Test dashboard pages."""

    def test_dashboard_requires_auth(self, client):
        """Test that dashboard redirects to login when not authenticated."""
        response = client.get("/dashboard", follow_redirects=False)
        assert response.status_code == 302
        assert "/auth/login" in response.headers["location"]

    def test_dashboard_loads_authenticated(self, authenticated_client):
        """Test that dashboard loads for authenticated users."""
        client, cookies = authenticated_client
        response = client.get("/dashboard", cookies=cookies)
        assert response.status_code == 200
        assert b"Dashboard" in response.content
        assert b"testuser@example.com" in response.content

    def test_dashboard_shows_no_devices_message(self, authenticated_client):
        """Test dashboard shows 'no devices' message when user has no devices."""
        client, cookies = authenticated_client
        response = client.get("/dashboard", cookies=cookies)
        assert response.status_code == 200
        assert b"No Devices Registered" in response.content

    def test_dashboard_shows_device_stats(self, authenticated_client, test_device):
        """Test dashboard shows device statistics."""
        client, cookies = authenticated_client
        device, _ = test_device

        response = client.get("/dashboard", cookies=cookies)
        assert response.status_code == 200
        assert device.device_id.encode() in response.content
        assert b"Total Vehicles (24h)" in response.content


# ============================================================================
# Device Management Tests
# ============================================================================

class TestDeviceManagement:
    """Test device management features."""

    def test_devices_page_loads(self, authenticated_client):
        """Test devices page loads."""
        client, cookies = authenticated_client
        response = client.get("/devices", cookies=cookies)
        assert response.status_code == 200
        assert b"Device Management" in response.content

    def test_device_registration_form_loads(self, authenticated_client):
        """Test device registration form loads."""
        client, cookies = authenticated_client
        response = client.get("/devices/register/form", cookies=cookies)
        assert response.status_code == 200
        assert b"Register New Device" in response.content

    def test_device_registration(self, authenticated_client):
        """Test registering a new device."""
        client, cookies = authenticated_client
        response = client.post(
            "/devices/register",
            data={
                "device_id": "test-device-new",
                "street_name": "Test Street",
                "speed_limit": "30",
                "latitude": "40.7128",
                "longitude": "-74.0060",
                "share_community": "false"
            },
            cookies=cookies
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "api_key" in data
        assert data["api_key"].startswith("rushroster_")

    def test_device_registration_duplicate(self, authenticated_client, test_device):
        """Test registering duplicate device fails."""
        client, cookies = authenticated_client
        device, _ = test_device

        response = client.post(
            "/devices/register",
            data={
                "device_id": device.device_id,
                "street_name": "Test Street",
                "speed_limit": "30"
            },
            cookies=cookies
        )
        assert response.status_code == 400
        assert response.json()["success"] is False
        assert "already registered" in response.json()["message"].lower()

    def test_device_detail_page(self, authenticated_client, test_device):
        """Test device detail page loads."""
        client, cookies = authenticated_client
        device, _ = test_device

        response = client.get(f"/devices/{device.id}", cookies=cookies)
        assert response.status_code == 200
        assert device.device_id.encode() in response.content
        assert b"Device Information" in response.content
        assert b"Statistics (30 Days)" in response.content

    def test_device_detail_wrong_user(self, client, test_device):
        """Test accessing device detail from wrong user fails."""
        # Create a different user
        response = client.post(
            "/auth/register",
            data={
                "email": "otheruser@example.com",
                "password": "password123",
                "confirm_password": "password123"
            }
        )
        assert response.status_code == 200

        # Login as the other user
        response = client.post(
            "/auth/login",
            data={
                "email": "otheruser@example.com",
                "password": "password123"
            }
        )
        cookies = response.cookies

        # Try to access the device
        device, _ = test_device
        response = client.get(f"/devices/{device.id}", cookies=cookies)
        assert response.status_code == 404


# ============================================================================
# Event Browsing Tests
# ============================================================================

class TestEventBrowsing:
    """Test event browsing features."""

    def test_events_page_loads(self, authenticated_client):
        """Test events page loads."""
        client, cookies = authenticated_client
        response = client.get("/events", cookies=cookies)
        assert response.status_code == 200
        assert b"Speed Events" in response.content
        assert b"Filters" in response.content

    def test_events_page_with_device_filter(self, authenticated_client, test_device):
        """Test events page with device filter."""
        client, cookies = authenticated_client
        device, _ = test_device

        response = client.get(f"/events?device_id={device.id}", cookies=cookies)
        assert response.status_code == 200
        assert b"Speed Events" in response.content


# ============================================================================
# Statistics Tests
# ============================================================================

class TestStatistics:
    """Test statistics dashboard."""

    def test_stats_page_loads(self, authenticated_client):
        """Test statistics page loads."""
        client, cookies = authenticated_client
        response = client.get("/stats", cookies=cookies)
        assert response.status_code == 200
        assert b"Statistics Dashboard" in response.content
        assert b"Total Vehicles" in response.content
        assert b"Speeding Events" in response.content

    def test_stats_page_with_device_filter(self, authenticated_client, test_device):
        """Test statistics page with device filter."""
        client, cookies = authenticated_client
        device, _ = test_device

        response = client.get(f"/stats?device_id={device.id}", cookies=cookies)
        assert response.status_code == 200
        assert b"Statistics Dashboard" in response.content

    def test_stats_page_with_period_filter(self, authenticated_client):
        """Test statistics page with period filter."""
        client, cookies = authenticated_client

        for period in ["24h", "7d", "30d", "90d"]:
            response = client.get(f"/stats?period={period}", cookies=cookies)
            assert response.status_code == 200
            assert b"Statistics Dashboard" in response.content


# ============================================================================
# Run Tests
# ============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
