"""
Test to verify timing attack mitigation in login endpoint.

This test demonstrates that the login endpoint now performs
constant-time password verification to prevent email enumeration
through timing analysis.
"""
import pytest
from fastapi.testclient import TestClient
import time
from main import app
from src.database.session import get_db
from src.database import crud
from src import auth_utils


@pytest.fixture
def client():
    """Create a test client."""
    return TestClient(app)


@pytest.fixture
def test_user(client):
    """Create a test user in the database."""
    import uuid
    # Use unique email to avoid conflicts between tests
    unique_email = f"timing_test_{uuid.uuid4().hex[:8]}@example.com"

    # Register a user
    response = client.post(
        "/api/auth/register",
        json={
            "email": unique_email,
            "password": "SecurePassword123",
            "full_name": "Timing Test User"
        }
    )
    assert response.status_code == 201
    user_data = response.json()
    user_data["email"] = unique_email  # Store email for later use
    user_data["password"] = "SecurePassword123"  # Store password for testing
    return user_data


def test_timing_attack_mitigation(client, test_user):
    """
    Test that login timing is consistent for existing vs non-existing users.

    This prevents email enumeration through timing analysis.
    """
    # Test login with non-existent user (should perform dummy hash check)
    start_time = time.time()
    response1 = client.post(
        "/api/auth/login",
        json={
            "email": "nonexistent@example.com",
            "password": "WrongPassword123"
        }
    )
    time_nonexistent = time.time() - start_time

    # Test login with existing user but wrong password (should perform real hash check)
    start_time = time.time()
    response2 = client.post(
        "/api/auth/login",
        json={
            "email": test_user["email"],
            "password": "WrongPassword123"
        }
    )
    time_wrong_password = time.time() - start_time

    # Both should return 401
    assert response1.status_code == 401
    assert response2.status_code == 401

    # Both should return the same generic error message
    assert response1.json()["detail"] == "Incorrect email or password"
    assert response2.json()["detail"] == "Incorrect email or password"

    # The timing difference should be minimal (within reasonable variance)
    # Both should take similar time because both perform bcrypt verification
    time_difference = abs(time_nonexistent - time_wrong_password)

    # Print timing information for analysis
    print(f"\nTiming Analysis:")
    print(f"Non-existent user: {time_nonexistent:.4f}s")
    print(f"Wrong password:    {time_wrong_password:.4f}s")
    print(f"Difference:        {time_difference:.4f}s")

    # Both should be relatively slow (bcrypt is intentionally slow)
    # Expect at least 50ms for bcrypt computation
    assert time_nonexistent > 0.05, "Non-existent user check should perform bcrypt (slow)"
    assert time_wrong_password > 0.05, "Wrong password check should perform bcrypt (slow)"

    # The difference should be small relative to the total time
    # Allow up to 30% variance (bcrypt has some natural variation)
    max_allowed_difference = max(time_nonexistent, time_wrong_password) * 0.3
    assert time_difference < max_allowed_difference, \
        f"Timing difference too large: {time_difference:.4f}s (max {max_allowed_difference:.4f}s)"


def test_successful_login_still_works(client, test_user):
    """Verify that successful login still works after timing attack fix."""
    response = client.post(
        "/api/auth/login",
        json={
            "email": test_user["email"],
            "password": test_user["password"]
        }
    )

    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["token_type"] == "bearer"


def test_login_error_message_consistency(client, test_user):
    """Verify that error messages don't reveal whether user exists."""
    # Non-existent user
    response1 = client.post(
        "/api/auth/login",
        json={"email": "doesnotexist@example.com", "password": "anypassword"}
    )

    # Existing user, wrong password
    response2 = client.post(
        "/api/auth/login",
        json={"email": test_user["email"], "password": "WrongPassword"}
    )

    # Both should have identical error messages
    assert response1.json()["detail"] == response2.json()["detail"]
    assert response1.json()["detail"] == "Incorrect email or password"
