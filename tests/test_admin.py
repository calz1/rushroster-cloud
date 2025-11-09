"""Integration tests for admin functionality.

This module tests the admin features including:
- Admin dashboard access
- User management (list, promote/demote, delete)
- Device management (list, delete)
- Admin API endpoints
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
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    Base.metadata.create_all(bind=engine)

    def override_get_db():
        try:
            db = TestingSessionLocal()
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    yield TestingSessionLocal()

    Base.metadata.drop_all(bind=engine)
    app.dependency_overrides.clear()


@pytest.fixture(scope="function")
def client(test_db):
    """Create a test client."""
    return TestClient(app)


@pytest.fixture(scope="function")
def admin_user(test_db):
    """Create an admin user (must be created first to be auto-admin)."""
    user = crud.create_user(
        test_db,
        email="admin@example.com",
        password_hash=hash_password("adminpass123")
        # Don't pass is_admin - let it auto-set as first user
    )
    crud.create_user_preferences(test_db, user.id)
    return user


@pytest.fixture(scope="function")
def regular_user(test_db, admin_user):
    """Create a regular (non-admin) user (depends on admin_user to ensure it's created second)."""
    user = crud.create_user(
        test_db,
        email="user@example.com",
        password_hash=hash_password("userpass123"),
        is_admin=False
    )
    crud.create_user_preferences(test_db, user.id)
    return user


@pytest.fixture(scope="function")
def authenticated_admin_client(client, admin_user):
    """Create an authenticated admin test client."""
    response = client.post(
        "/auth/login",
        data={
            "email": "admin@example.com",
            "password": "adminpass123"
        }
    )
    assert response.status_code == 200
    cookies = response.cookies
    return client, cookies


@pytest.fixture(scope="function")
def authenticated_regular_client(client, regular_user):
    """Create an authenticated regular user test client."""
    response = client.post(
        "/auth/login",
        data={
            "email": "user@example.com",
            "password": "userpass123"
        }
    )
    assert response.status_code == 200
    cookies = response.cookies
    return client, cookies


@pytest.fixture(scope="function")
def test_device(test_db, regular_user):
    """Create a test device owned by regular user."""
    from src.auth_utils import generate_api_key, hash_api_key
    api_key = generate_api_key()
    api_key_hash = hash_api_key(api_key)

    device = crud.create_device(
        test_db,
        device_id="test-device-001",
        owner_id=regular_user.id,
        api_key_hash=api_key_hash,
        latitude=40.7128,
        longitude=-74.0060,
        street_name="Main Street",
        speed_limit=25.0
    )

    crud.create_device_api_key(test_db, device.id, api_key_hash, name="Test API Key")
    return device


# ============================================================================
# Admin Dashboard Tests
# ============================================================================

class TestAdminDashboard:
    """Test admin dashboard access and functionality."""

    def test_admin_dashboard_requires_auth(self, client):
        """Test that admin dashboard redirects to login when not authenticated."""
        response = client.get("/admin", follow_redirects=False)
        assert response.status_code == 302
        assert "/auth/login" in response.headers["location"]

    def test_admin_dashboard_requires_admin(self, authenticated_regular_client):
        """Test that regular users cannot access admin dashboard."""
        client, cookies = authenticated_regular_client
        response = client.get("/admin", cookies=cookies)
        assert response.status_code == 403

    def test_admin_dashboard_loads(self, authenticated_admin_client):
        """Test that admin dashboard loads for admin users."""
        client, cookies = authenticated_admin_client
        response = client.get("/admin", cookies=cookies)
        assert response.status_code == 200
        assert b"Admin Dashboard" in response.content
        assert b"Users" in response.content
        assert b"Devices" in response.content

    def test_admin_dashboard_shows_stats(self, authenticated_admin_client, regular_user):
        """Test that admin dashboard shows platform statistics."""
        client, cookies = authenticated_admin_client
        response = client.get("/admin", cookies=cookies)
        assert response.status_code == 200
        # Should show at least 2 users (admin + regular_user)
        assert b"Total Users" in response.content


# ============================================================================
# User Management Tests
# ============================================================================

class TestUserManagement:
    """Test admin user management features."""

    def test_admin_users_page_requires_admin(self, authenticated_regular_client):
        """Test that regular users cannot access user management."""
        client, cookies = authenticated_regular_client
        response = client.get("/admin/users", cookies=cookies)
        assert response.status_code == 403

    def test_admin_users_page_loads(self, authenticated_admin_client, regular_user):
        """Test that admin users page loads."""
        client, cookies = authenticated_admin_client
        response = client.get("/admin/users", cookies=cookies)
        assert response.status_code == 200
        assert b"User Management" in response.content
        assert b"admin@example.com" in response.content
        assert b"user@example.com" in response.content

    def test_admin_can_promote_user(self, authenticated_admin_client, regular_user):
        """Test that admin can promote a regular user to admin."""
        client, cookies = authenticated_admin_client
        response = client.post(
            f"/admin/users/{regular_user.id}/admin",
            data={"is_admin": "true"},
            cookies=cookies
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "promoted" in data["message"].lower()

    def test_admin_can_demote_user(self, authenticated_admin_client, test_db):
        """Test that admin can demote another admin to regular user."""
        # Create another admin user
        other_admin = crud.create_user(
            test_db,
            email="otheradmin@example.com",
            password_hash=hash_password("password123"),
            is_admin=True
        )

        client, cookies = authenticated_admin_client
        response = client.post(
            f"/admin/users/{other_admin.id}/admin",
            data={"is_admin": "false"},
            cookies=cookies
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "demoted" in data["message"].lower()

    def test_admin_cannot_demote_self(self, authenticated_admin_client, admin_user):
        """Test that admin cannot remove their own admin privileges."""
        client, cookies = authenticated_admin_client
        response = client.post(
            f"/admin/users/{admin_user.id}/admin",
            data={"is_admin": "false"},
            cookies=cookies
        )
        assert response.status_code == 400
        data = response.json()
        assert data["success"] is False
        assert "own" in data["message"].lower()

    def test_admin_can_delete_user(self, authenticated_admin_client, regular_user):
        """Test that admin can delete a user."""
        client, cookies = authenticated_admin_client
        response = client.delete(
            f"/admin/users/{regular_user.id}",
            cookies=cookies
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

    def test_admin_cannot_delete_self(self, authenticated_admin_client, admin_user):
        """Test that admin cannot delete their own account."""
        client, cookies = authenticated_admin_client
        response = client.delete(
            f"/admin/users/{admin_user.id}",
            cookies=cookies
        )
        assert response.status_code == 400
        data = response.json()
        assert data["success"] is False
        assert "own" in data["message"].lower()

    def test_regular_user_cannot_manage_users(self, authenticated_regular_client, admin_user):
        """Test that regular users cannot manage other users."""
        client, cookies = authenticated_regular_client

        # Try to promote another user
        response = client.post(
            f"/admin/users/{admin_user.id}/admin",
            data={"is_admin": "true"},
            cookies=cookies
        )
        assert response.status_code == 403


# ============================================================================
# Device Management Tests
# ============================================================================

class TestDeviceManagement:
    """Test admin device management features."""

    def test_admin_devices_page_requires_admin(self, authenticated_regular_client):
        """Test that regular users cannot access device management."""
        client, cookies = authenticated_regular_client
        response = client.get("/admin/devices", cookies=cookies)
        assert response.status_code == 403

    def test_admin_devices_page_loads(self, authenticated_admin_client, test_device):
        """Test that admin devices page loads."""
        client, cookies = authenticated_admin_client
        response = client.get("/admin/devices", cookies=cookies)
        assert response.status_code == 200
        assert b"Device Management" in response.content
        assert b"test-device-001" in response.content
        assert b"user@example.com" in response.content

    def test_admin_can_delete_device(self, authenticated_admin_client, test_device):
        """Test that admin can delete any device."""
        client, cookies = authenticated_admin_client
        response = client.delete(
            f"/admin/devices/{test_device.id}",
            cookies=cookies
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

    def test_regular_user_cannot_delete_device(self, authenticated_regular_client, test_device):
        """Test that regular users cannot delete devices via admin endpoint."""
        client, cookies = authenticated_regular_client
        response = client.delete(
            f"/admin/devices/{test_device.id}",
            cookies=cookies
        )
        assert response.status_code == 403


# ============================================================================
# Admin API Endpoint Tests
# ============================================================================

class TestAdminAPI:
    """Test admin API endpoints."""

    def test_admin_stats_endpoint_requires_admin(self, authenticated_regular_client):
        """Test that regular users cannot access admin stats API."""
        client, cookies = authenticated_regular_client
        response = client.get("/api/admin/stats", cookies=cookies)
        assert response.status_code == 403

    def test_admin_stats_endpoint(self, authenticated_admin_client, regular_user, test_device):
        """Test admin stats API endpoint."""
        client, cookies = authenticated_admin_client

        # Use JWT token for API endpoint
        login_response = client.post(
            "/api/auth/login",
            json={
                "email": "admin@example.com",
                "password": "adminpass123"
            }
        )
        token = login_response.json()["access_token"]

        response = client.get(
            "/api/admin/stats",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "total_users" in data
        assert "total_devices" in data
        assert data["total_users"] >= 2  # admin + regular_user
        assert data["total_devices"] >= 1  # test_device

    def test_admin_users_list_endpoint(self, authenticated_admin_client, regular_user):
        """Test admin users list API endpoint."""
        client, cookies = authenticated_admin_client

        # Use JWT token for API endpoint
        login_response = client.post(
            "/api/auth/login",
            json={
                "email": "admin@example.com",
                "password": "adminpass123"
            }
        )
        token = login_response.json()["access_token"]

        response = client.get(
            "/api/admin/users",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200
        users = response.json()
        assert len(users) >= 2
        assert any(u["email"] == "admin@example.com" for u in users)
        assert any(u["email"] == "user@example.com" for u in users)


# ============================================================================
# First User Admin Test
# ============================================================================

class TestFirstUserAdmin:
    """Test that first user is automatically made admin."""

    def test_first_user_is_admin(self, test_db):
        """Test that the first user is automatically made admin."""
        # Create first user
        user1 = crud.create_user(
            test_db,
            email="first@example.com",
            password_hash=hash_password("password123")
        )
        assert user1.is_admin is True

        # Create second user
        user2 = crud.create_user(
            test_db,
            email="second@example.com",
            password_hash=hash_password("password123")
        )
        assert user2.is_admin is False


# ============================================================================
# Navigation Tests
# ============================================================================

class TestAdminNavigation:
    """Test admin UI elements in navigation."""

    def test_admin_link_in_nav_for_admin(self, authenticated_admin_client):
        """Test that admin link appears in navigation for admin users."""
        client, cookies = authenticated_admin_client
        response = client.get("/dashboard", cookies=cookies)
        assert response.status_code == 200
        assert b"Admin" in response.content
        assert b"ADMIN" in response.content  # Badge

    def test_no_admin_link_for_regular_user(self, authenticated_regular_client):
        """Test that admin link does not appear for regular users."""
        client, cookies = authenticated_regular_client
        response = client.get("/dashboard", cookies=cookies)
        assert response.status_code == 200
        # Should not have admin link or badge
        assert b'href="/admin"' not in response.content


# ============================================================================
# Run Tests
# ============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
