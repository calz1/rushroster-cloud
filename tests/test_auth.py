"""Tests for authentication flows.

This module tests:
- Login page
- Registration page
- User registration (with registration codes)
- User login
- Logout
- Registration code validation
"""

import pytest


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
        assert b"Registration Code" in response.content

    def test_user_registration(self, client, test_registration_code):
        """Test user registration with valid registration code."""
        response = client.post(
            "/auth/register",
            data={
                "email": "newuser@example.com",
                "password": "newpassword123",
                "confirm_password": "newpassword123",
                "registration_code": "TEST2024"
            }
        )
        assert response.status_code == 200
        assert response.json()["success"] is True
        assert "created successfully" in response.json()["message"].lower()

    def test_registration_missing_code(self, client):
        """Test registration fails without registration code."""
        response = client.post(
            "/auth/register",
            data={
                "email": "newuser@example.com",
                "password": "newpassword123",
                "confirm_password": "newpassword123"
            }
        )
        # FastAPI will reject this due to missing required field
        assert response.status_code == 422

    def test_registration_invalid_code(self, client):
        """Test registration fails with invalid registration code."""
        response = client.post(
            "/auth/register",
            data={
                "email": "newuser@example.com",
                "password": "newpassword123",
                "confirm_password": "newpassword123",
                "registration_code": "INVALID_CODE"
            }
        )
        assert response.status_code == 400
        assert response.json()["success"] is False
        assert "registration code" in response.json()["message"].lower()

    def test_registration_expired_code(self, client, test_expired_code):
        """Test registration fails with expired code."""
        response = client.post(
            "/auth/register",
            data={
                "email": "newuser@example.com",
                "password": "newpassword123",
                "confirm_password": "newpassword123",
                "registration_code": "EXPIRED"
            }
        )
        assert response.status_code == 400
        assert response.json()["success"] is False
        assert "registration code" in response.json()["message"].lower()

    def test_registration_inactive_code(self, client, test_inactive_code):
        """Test registration fails with inactive code."""
        response = client.post(
            "/auth/register",
            data={
                "email": "newuser@example.com",
                "password": "newpassword123",
                "confirm_password": "newpassword123",
                "registration_code": "INACTIVE"
            }
        )
        assert response.status_code == 400
        assert response.json()["success"] is False
        assert "registration code" in response.json()["message"].lower()

    def test_registration_code_usage_increment(self, client, test_registration_code, test_db):
        """Test that registration code usage is incremented."""
        from src.database import crud

        # Check initial usage
        code = crud.get_registration_code_by_code(test_db, "TEST2024")
        initial_uses = code.current_uses

        # Register a user
        response = client.post(
            "/auth/register",
            data={
                "email": "newuser@example.com",
                "password": "newpassword123",
                "confirm_password": "newpassword123",
                "registration_code": "TEST2024"
            }
        )
        assert response.status_code == 200
        assert response.json()["success"] is True

        # Check usage incremented
        test_db.refresh(code)
        assert code.current_uses == initial_uses + 1

    def test_registration_code_max_uses(self, client, test_single_use_code, test_db):
        """Test that registration code can't be used beyond max_uses."""
        # First registration should succeed
        response1 = client.post(
            "/auth/register",
            data={
                "email": "user1@example.com",
                "password": "password123",
                "confirm_password": "password123",
                "registration_code": "SINGLE123"
            }
        )
        assert response1.status_code == 200
        assert response1.json()["success"] is True

        # Second registration should fail (code is single-use)
        response2 = client.post(
            "/auth/register",
            data={
                "email": "user2@example.com",
                "password": "password123",
                "confirm_password": "password123",
                "registration_code": "SINGLE123"
            }
        )
        assert response2.status_code == 400
        assert response2.json()["success"] is False
        assert "registration code" in response2.json()["message"].lower()

    def test_registration_password_mismatch(self, client, test_registration_code):
        """Test registration fails with mismatched passwords."""
        response = client.post(
            "/auth/register",
            data={
                "email": "newuser@example.com",
                "password": "password123",
                "confirm_password": "different123",
                "registration_code": "TEST2024"
            }
        )
        assert response.status_code == 400
        assert response.json()["success"] is False
        assert "do not match" in response.json()["message"].lower()

    def test_registration_short_password(self, client, test_registration_code):
        """Test registration fails with short password."""
        response = client.post(
            "/auth/register",
            data={
                "email": "newuser@example.com",
                "password": "short",
                "confirm_password": "short",
                "registration_code": "TEST2024"
            }
        )
        assert response.status_code == 400
        assert response.json()["success"] is False
        assert "8 characters" in response.json()["message"].lower()

    def test_registration_duplicate_email(self, client, test_user, test_registration_code):
        """Test registration fails with duplicate email."""
        response = client.post(
            "/auth/register",
            data={
                "email": "testuser@example.com",
                "password": "password123",
                "confirm_password": "password123",
                "registration_code": "TEST2024"
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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
