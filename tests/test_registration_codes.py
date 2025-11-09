"""Tests for registration code management.

This module tests:
- Admin registration code CRUD operations
- Registration code API endpoints
- Registration code web UI
- Registration code validation logic
"""

import pytest
from datetime import datetime, timedelta


class TestRegistrationCodeCRUD:
    """Test registration code CRUD operations."""

    def test_create_registration_code(self, test_db):
        """Test creating a registration code."""
        from src.database import crud

        code = crud.create_registration_code(
            test_db,
            code="TESTCODE",
            max_uses=10,
            description="Test code"
        )

        assert code.code == "TESTCODE"
        assert code.max_uses == 10
        assert code.current_uses == 0
        assert code.is_active is True
        assert code.description == "Test code"

    def test_get_registration_code_by_code(self, test_db, test_registration_code):
        """Test getting a registration code by code string."""
        from src.database import crud

        code = crud.get_registration_code_by_code(test_db, "TEST2024")
        assert code is not None
        assert code.code == "TEST2024"

    def test_validate_and_use_registration_code(self, test_db, test_registration_code):
        """Test validating and using a registration code."""
        from src.database import crud

        # Valid code should succeed
        result = crud.validate_and_use_registration_code(test_db, "TEST2024")
        assert result is True

        # Check usage incremented
        code = crud.get_registration_code_by_code(test_db, "TEST2024")
        assert code.current_uses == 1

    def test_validate_invalid_code(self, test_db):
        """Test validating an invalid code."""
        from src.database import crud

        result = crud.validate_and_use_registration_code(test_db, "INVALID")
        assert result is False

    def test_validate_inactive_code(self, test_db, test_inactive_code):
        """Test validating an inactive code."""
        from src.database import crud

        result = crud.validate_and_use_registration_code(test_db, "INACTIVE")
        assert result is False

    def test_validate_expired_code(self, test_db, test_expired_code):
        """Test validating an expired code."""
        from src.database import crud

        result = crud.validate_and_use_registration_code(test_db, "EXPIRED")
        assert result is False

    def test_validate_fully_used_code(self, test_db, test_single_use_code):
        """Test validating a fully used code."""
        from src.database import crud

        # Use the code once
        result1 = crud.validate_and_use_registration_code(test_db, "SINGLE123")
        assert result1 is True

        # Try to use again
        result2 = crud.validate_and_use_registration_code(test_db, "SINGLE123")
        assert result2 is False

    def test_get_all_registration_codes(self, test_db, test_registration_code, test_inactive_code):
        """Test getting all registration codes."""
        from src.database import crud

        # Get active codes only
        active_codes = crud.get_all_registration_codes(test_db, include_inactive=False)
        assert len(active_codes) == 1
        assert active_codes[0].code == "TEST2024"

        # Get all codes
        all_codes = crud.get_all_registration_codes(test_db, include_inactive=True)
        assert len(all_codes) == 2

    def test_update_registration_code(self, test_db, test_registration_code):
        """Test updating a registration code."""
        from src.database import crud

        updated = crud.update_registration_code(
            test_db,
            test_registration_code.id,
            max_uses=20,
            description="Updated description"
        )

        assert updated.max_uses == 20
        assert updated.description == "Updated description"

    def test_deactivate_registration_code(self, test_db, test_registration_code):
        """Test deactivating a registration code."""
        from src.database import crud

        result = crud.deactivate_registration_code(test_db, test_registration_code.id)
        assert result is True

        code = crud.get_registration_code_by_code(test_db, "TEST2024")
        assert code.is_active is False

    def test_delete_registration_code(self, test_db, test_registration_code):
        """Test deleting a registration code."""
        from src.database import crud

        result = crud.delete_registration_code(test_db, test_registration_code.id)
        assert result is True

        code = crud.get_registration_code_by_code(test_db, "TEST2024")
        assert code is None


class TestRegistrationCodeAdminAPI:
    """Test admin API endpoints for registration codes."""

    def test_list_registration_codes_requires_admin(self, client, test_user):
        """Test that listing codes requires admin privileges."""
        # Try without authentication
        response = client.get("/api/admin/registration-codes")
        assert response.status_code == 403

    def test_list_registration_codes(self, client, admin_user, test_registration_code):
        """Test listing all registration codes."""
        from src.auth_utils import create_access_token

        token = create_access_token({"sub": str(admin_user.id)})
        response = client.get(
            "/api/admin/registration-codes",
            headers={"Authorization": f"Bearer {token}"}
        )

        assert response.status_code == 200
        codes = response.json()
        assert len(codes) >= 1
        assert any(c["code"] == "TEST2024" for c in codes)

    def test_create_registration_code(self, client, admin_user):
        """Test creating a registration code via API."""
        from src.auth_utils import create_access_token

        token = create_access_token({"sub": str(admin_user.id)})
        response = client.post(
            "/api/admin/registration-codes",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "code": "NEWCODE123",
                "max_uses": 5,
                "description": "New code"
            }
        )

        assert response.status_code == 201
        data = response.json()
        assert data["code"] == "NEWCODE123"
        assert data["max_uses"] == 5
        assert data["current_uses"] == 0

    def test_create_duplicate_code(self, client, admin_user, test_registration_code):
        """Test creating a duplicate code fails."""
        from src.auth_utils import create_access_token

        token = create_access_token({"sub": str(admin_user.id)})
        response = client.post(
            "/api/admin/registration-codes",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "code": "TEST2024",
                "max_uses": 5
            }
        )

        assert response.status_code == 400
        assert "already exists" in response.json()["detail"].lower()

    def test_get_registration_code(self, client, admin_user, test_registration_code):
        """Test getting a specific registration code."""
        from src.auth_utils import create_access_token

        token = create_access_token({"sub": str(admin_user.id)})
        response = client.get(
            f"/api/admin/registration-codes/{test_registration_code.id}",
            headers={"Authorization": f"Bearer {token}"}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["code"] == "TEST2024"

    def test_update_registration_code(self, client, admin_user, test_registration_code):
        """Test updating a registration code."""
        from src.auth_utils import create_access_token

        token = create_access_token({"sub": str(admin_user.id)})
        response = client.patch(
            f"/api/admin/registration-codes/{test_registration_code.id}",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "max_uses": 15,
                "description": "Updated via API"
            }
        )

        assert response.status_code == 200
        data = response.json()
        assert data["max_uses"] == 15
        assert data["description"] == "Updated via API"

    def test_delete_registration_code(self, client, admin_user, test_registration_code):
        """Test deleting a registration code."""
        from src.auth_utils import create_access_token

        token = create_access_token({"sub": str(admin_user.id)})
        response = client.delete(
            f"/api/admin/registration-codes/{test_registration_code.id}",
            headers={"Authorization": f"Bearer {token}"}
        )

        assert response.status_code == 204


class TestRegistrationCodeWebUI:
    """Test web UI for registration code management."""

    def test_registration_codes_page_requires_admin(self, client):
        """Test that the registration codes page requires admin."""
        response = client.get("/admin/registration-codes", follow_redirects=False)
        assert response.status_code == 302
        assert "/auth/login" in response.headers["location"]

    def test_registration_codes_page_loads(self, authenticated_admin_client, test_registration_code):
        """Test that the registration codes page loads for admins."""
        client, cookies = authenticated_admin_client
        response = client.get("/admin/registration-codes", cookies=cookies)

        assert response.status_code == 200
        assert b"Registration Code Management" in response.content
        assert b"TEST2024" in response.content

    def test_create_registration_code_web_ui(self, authenticated_admin_client):
        """Test creating a registration code via web UI."""
        client, cookies = authenticated_admin_client
        response = client.post(
            "/admin/registration-codes",
            data={
                "code": "WEBCODE",
                "max_uses": 3,
                "description": "Created via web"
            },
            cookies=cookies
        )

        assert response.status_code == 200
        assert response.json()["success"] is True

    def test_toggle_registration_code(self, authenticated_admin_client, test_registration_code):
        """Test toggling a registration code active status."""
        client, cookies = authenticated_admin_client
        response = client.patch(
            f"/admin/registration-codes/{test_registration_code.id}/toggle",
            cookies=cookies
        )

        assert response.status_code == 200
        assert response.json()["success"] is True

    def test_delete_registration_code_web_ui(self, authenticated_admin_client, test_registration_code):
        """Test deleting a registration code via web UI."""
        client, cookies = authenticated_admin_client
        response = client.delete(
            f"/admin/registration-codes/{test_registration_code.id}",
            cookies=cookies
        )

        assert response.status_code == 200
        assert response.json()["success"] is True


class TestRegistrationCodeIntegration:
    """Test end-to-end registration code flows."""

    def test_full_registration_flow(self, client, admin_user, test_db):
        """Test complete flow: create code, register user, verify usage."""
        from src.auth_utils import create_access_token
        from src.database import crud

        # Admin creates a code
        token = create_access_token({"sub": str(admin_user.id)})
        create_response = client.post(
            "/api/admin/registration-codes",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "code": "FULLFLOW",
                "max_uses": 2,
                "description": "Integration test"
            }
        )
        assert create_response.status_code == 201

        # User registers with the code
        reg_response = client.post(
            "/auth/register",
            data={
                "email": "integrationuser@example.com",
                "password": "password123",
                "confirm_password": "password123",
                "registration_code": "FULLFLOW"
            }
        )
        assert reg_response.status_code == 200
        assert reg_response.json()["success"] is True

        # Verify code usage incremented
        code = crud.get_registration_code_by_code(test_db, "FULLFLOW")
        assert code.current_uses == 1
        assert code.max_uses == 2

        # User can login
        login_response = client.post(
            "/auth/login",
            data={
                "email": "integrationuser@example.com",
                "password": "password123"
            }
        )
        assert login_response.status_code == 200
        assert login_response.json()["success"] is True

    def test_multiple_users_same_code(self, client, test_registration_code, test_db):
        """Test multiple users can register with the same code (within max_uses)."""
        # Register first user
        response1 = client.post(
            "/auth/register",
            data={
                "email": "user1@example.com",
                "password": "password123",
                "confirm_password": "password123",
                "registration_code": "TEST2024"
            }
        )
        assert response1.status_code == 200
        assert response1.json()["success"] is True

        # Register second user
        response2 = client.post(
            "/auth/register",
            data={
                "email": "user2@example.com",
                "password": "password123",
                "confirm_password": "password123",
                "registration_code": "TEST2024"
            }
        )
        assert response2.status_code == 200
        assert response2.json()["success"] is True

        # Both registrations succeeded, which means the code was validated twice
        # This verifies multiple users can use the same code within max_uses


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
