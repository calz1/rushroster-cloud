"""Integration tests for the public speeders feature.

This module tests:
- Public speeders list page
- Clicking on speeding events from map popup
- Handling devices with/without photos
- Privacy: only showing community-shared devices
"""

import pytest
from datetime import datetime, timedelta
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from main import app
from src.database.models import Base
from src.database.session import get_db
from src.database import crud
from src.auth_utils import hash_password, generate_api_key, hash_api_key


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
def community_device_with_speeders(test_db, test_user):
    """Create a community-shared device with speeding events."""
    api_key = generate_api_key()
    api_key_hash = hash_api_key(api_key)

    # Create device shared with community
    device = crud.create_device(
        test_db,
        device_id="test-community-device",
        owner_id=test_user.id,
        api_key_hash=api_key_hash,
        latitude=40.7128,
        longitude=-74.0060,
        street_name="Main Street",
        speed_limit=25.0,
        share_community=True  # Device is shared with community
    )

    # Create API key record
    crud.create_device_api_key(test_db, device.id, api_key_hash, name="Test API Key")

    # Create some speeding events (with and without photos)
    now = datetime.utcnow()
    speeders = []

    for i in range(10):
        event = crud.create_speed_event(
            test_db,
            device_id=device.id,
            timestamp=now - timedelta(hours=i),
            speed=35.0 + i,  # Varying speeds
            speed_limit=25.0,
            is_speeding=True,
            photo_url=f"https://example.com/photo{i}.jpg" if i % 2 == 0 else None  # Every other event has a photo
        )
        speeders.append(event)

    # Create some non-speeding events (should not appear in results)
    for i in range(5):
        crud.create_speed_event(
            test_db,
            device_id=device.id,
            timestamp=now - timedelta(hours=i + 20),
            speed=20.0,
            speed_limit=25.0,
            is_speeding=False,
            photo_url=None
        )

    return device, speeders


@pytest.fixture(scope="function")
def private_device_with_speeders(test_db, test_user):
    """Create a private (non-shared) device with speeding events."""
    api_key = generate_api_key()
    api_key_hash = hash_api_key(api_key)

    # Create device NOT shared with community
    device = crud.create_device(
        test_db,
        device_id="test-private-device",
        owner_id=test_user.id,
        api_key_hash=api_key_hash,
        latitude=40.7589,
        longitude=-73.9851,
        street_name="Private Street",
        speed_limit=30.0,
        share_community=False  # Device is NOT shared with community
    )

    # Create API key record
    crud.create_device_api_key(test_db, device.id, api_key_hash, name="Private API Key")

    # Create speeding events
    now = datetime.utcnow()
    for i in range(5):
        crud.create_speed_event(
            test_db,
            device_id=device.id,
            timestamp=now - timedelta(hours=i),
            speed=40.0,
            speed_limit=30.0,
            is_speeding=True,
            photo_url=f"https://example.com/private_photo{i}.jpg"
        )

    return device


# ============================================================================
# Public Speeders Page Tests
# ============================================================================

class TestPublicSpeedersPage:
    """Test public speeders list page."""

    def test_speeders_page_loads_for_community_device(self, client, community_device_with_speeders):
        """Test that speeders page loads for a community-shared device."""
        device, speeders = community_device_with_speeders

        response = client.get(f"/public/location/{device.id}/speeders")
        assert response.status_code == 200
        assert b"Recent Speeders" in response.content
        assert device.street_name.encode() in response.content
        assert b"25 mph" in response.content  # Speed limit

    def test_speeders_page_shows_correct_count(self, client, community_device_with_speeders):
        """Test that speeders page shows all 10 recent speeders."""
        device, speeders = community_device_with_speeders

        response = client.get(f"/public/location/{device.id}/speeders")
        assert response.status_code == 200

        # Check that it mentions showing 10 speeders
        assert b"Showing the last 10 speeding event" in response.content

    def test_speeders_page_shows_photos_when_available(self, client, community_device_with_speeders):
        """Test that speeders page displays photos when available."""
        device, speeders = community_device_with_speeders

        response = client.get(f"/public/location/{device.id}/speeders")
        assert response.status_code == 200

        # Check for image URLs (every other event has a photo)
        assert b"https://example.com/photo" in response.content

    def test_speeders_page_handles_missing_photos(self, client, community_device_with_speeders):
        """Test that speeders page gracefully handles missing photos."""
        device, speeders = community_device_with_speeders

        response = client.get(f"/public/location/{device.id}/speeders")
        assert response.status_code == 200

        # Check for "no photo available" message
        assert b"No photo available" in response.content

    def test_speeders_page_shows_speed_over_limit(self, client, community_device_with_speeders):
        """Test that speeders page shows how much over the limit each speeder was."""
        device, speeders = community_device_with_speeders

        response = client.get(f"/public/location/{device.id}/speeders")
        assert response.status_code == 200

        # Check for "mph over limit" text
        assert b"mph over limit" in response.content

    def test_speeders_page_shows_timestamps(self, client, community_device_with_speeders):
        """Test that speeders page shows timestamp for each event."""
        device, speeders = community_device_with_speeders

        response = client.get(f"/public/location/{device.id}/speeders")
        assert response.status_code == 200

        # Check for timestamp icon and "at" text (part of time format)
        assert b"\xf0\x9f\x95\x92" in response.content  # Clock emoji UTF-8
        assert b" at " in response.content

    def test_speeders_page_has_back_link(self, client, community_device_with_speeders):
        """Test that speeders page has a link back to the public map."""
        device, speeders = community_device_with_speeders

        response = client.get(f"/public/location/{device.id}/speeders")
        assert response.status_code == 200

        # Check for back link
        assert b"Back to Map" in response.content
        assert b'href="/public"' in response.content


# ============================================================================
# Privacy and Access Control Tests
# ============================================================================

class TestPrivacyAndAccessControl:
    """Test privacy controls for speeders page."""

    def test_private_device_speeders_not_accessible(self, client, private_device_with_speeders):
        """Test that private (non-shared) device speeders are not accessible."""
        device = private_device_with_speeders

        response = client.get(f"/public/location/{device.id}/speeders")
        assert response.status_code == 404

    def test_nonexistent_device_returns_404(self, client):
        """Test that requesting speeders for non-existent device returns 404."""
        fake_uuid = "00000000-0000-0000-0000-000000000000"
        response = client.get(f"/public/location/{fake_uuid}/speeders")
        assert response.status_code == 404

    def test_inactive_device_not_accessible(self, test_db, client, community_device_with_speeders):
        """Test that inactive devices are not accessible even if shared."""
        device, speeders = community_device_with_speeders

        # Deactivate the device
        crud.update_device(test_db, device.id, is_active=False)

        response = client.get(f"/public/location/{device.id}/speeders")
        assert response.status_code == 404


# ============================================================================
# Edge Cases Tests
# ============================================================================

class TestEdgeCases:
    """Test edge cases for speeders functionality."""

    def test_device_with_no_speeders(self, test_db, client, test_user):
        """Test device with no speeding events shows appropriate message."""
        api_key = generate_api_key()
        api_key_hash = hash_api_key(api_key)

        # Create device with no speeders
        device = crud.create_device(
            test_db,
            device_id="test-no-speeders",
            owner_id=test_user.id,
            api_key_hash=api_key_hash,
            latitude=40.7128,
            longitude=-74.0060,
            street_name="Quiet Street",
            speed_limit=25.0,
            share_community=True
        )

        response = client.get(f"/public/location/{device.id}/speeders")
        assert response.status_code == 200
        assert b"No Recent Speeders" in response.content
        assert b"No speeding events have been recorded" in response.content

    def test_device_with_only_non_speeding_events(self, test_db, client, test_user):
        """Test device with only compliant traffic shows no speeders."""
        api_key = generate_api_key()
        api_key_hash = hash_api_key(api_key)

        device = crud.create_device(
            test_db,
            device_id="test-compliant-only",
            owner_id=test_user.id,
            api_key_hash=api_key_hash,
            latitude=40.7128,
            longitude=-74.0060,
            street_name="Compliant Street",
            speed_limit=25.0,
            share_community=True
        )

        # Create only non-speeding events
        now = datetime.utcnow()
        for i in range(5):
            crud.create_speed_event(
                test_db,
                device_id=device.id,
                timestamp=now - timedelta(hours=i),
                speed=20.0,
                speed_limit=25.0,
                is_speeding=False,
                photo_url=None
            )

        response = client.get(f"/public/location/{device.id}/speeders")
        assert response.status_code == 200
        assert b"No Recent Speeders" in response.content

    def test_device_without_speed_limit(self, test_db, client, test_user):
        """Test device without speed limit configured."""
        api_key = generate_api_key()
        api_key_hash = hash_api_key(api_key)

        device = crud.create_device(
            test_db,
            device_id="test-no-limit",
            owner_id=test_user.id,
            api_key_hash=api_key_hash,
            latitude=40.7128,
            longitude=-74.0060,
            street_name="Unknown Limit Street",
            speed_limit=None,  # No speed limit configured
            share_community=True
        )

        # Create a speeding event
        now = datetime.utcnow()
        crud.create_speed_event(
            test_db,
            device_id=device.id,
            timestamp=now,
            speed=50.0,
            speed_limit=25.0,  # Event has speed limit even if device doesn't
            is_speeding=True,
            photo_url="https://example.com/photo.jpg"
        )

        response = client.get(f"/public/location/{device.id}/speeders")
        assert response.status_code == 200
        assert b"50 mph" in response.content


# ============================================================================
# CRUD Function Tests
# ============================================================================

class TestSpeedersDataRetrieval:
    """Test the CRUD function for retrieving speeders."""

    def test_get_device_recent_speeders_returns_correct_count(self, test_db, community_device_with_speeders):
        """Test that get_device_recent_speeders returns correct number of events."""
        device, speeders = community_device_with_speeders

        result = crud.get_device_recent_speeders(test_db, device.id, limit=10)
        assert len(result) == 10

    def test_get_device_recent_speeders_only_returns_speeding_events(self, test_db, community_device_with_speeders):
        """Test that only speeding events are returned."""
        device, speeders = community_device_with_speeders

        result = crud.get_device_recent_speeders(test_db, device.id, limit=10)

        # All returned events should be speeding events
        for event in result:
            assert event.is_speeding is True

    def test_get_device_recent_speeders_ordered_by_timestamp(self, test_db, community_device_with_speeders):
        """Test that speeders are returned in descending timestamp order (most recent first)."""
        device, speeders = community_device_with_speeders

        result = crud.get_device_recent_speeders(test_db, device.id, limit=10)

        # Check that timestamps are in descending order
        for i in range(len(result) - 1):
            assert result[i].timestamp >= result[i + 1].timestamp

    def test_get_device_recent_speeders_respects_limit(self, test_db, community_device_with_speeders):
        """Test that limit parameter is respected."""
        device, speeders = community_device_with_speeders

        # Request only 5 speeders
        result = crud.get_device_recent_speeders(test_db, device.id, limit=5)
        assert len(result) == 5

    def test_get_device_recent_speeders_filters_by_5mph_threshold(self, test_db, test_user):
        """Test that only speeders going >5 mph over the limit are returned."""
        api_key = generate_api_key()
        api_key_hash = hash_api_key(api_key)

        # Create device
        device = crud.create_device(
            test_db,
            device_id="test-threshold-device",
            owner_id=test_user.id,
            api_key_hash=api_key_hash,
            latitude=40.7128,
            longitude=-74.0060,
            street_name="Threshold Test Street",
            speed_limit=30.0,
            share_community=True
        )

        now = datetime.utcnow()

        # Create events at different speeds
        # 32 mph in 30 zone = 2 over (should NOT appear)
        crud.create_speed_event(
            test_db,
            device_id=device.id,
            timestamp=now - timedelta(hours=1),
            speed=32.0,
            speed_limit=30.0,
            is_speeding=True,
            photo_url=None
        )

        # 35 mph in 30 zone = 5 over (should NOT appear, must be >5)
        crud.create_speed_event(
            test_db,
            device_id=device.id,
            timestamp=now - timedelta(hours=2),
            speed=35.0,
            speed_limit=30.0,
            is_speeding=True,
            photo_url=None
        )

        # 36 mph in 30 zone = 6 over (SHOULD appear)
        crud.create_speed_event(
            test_db,
            device_id=device.id,
            timestamp=now - timedelta(hours=3),
            speed=36.0,
            speed_limit=30.0,
            is_speeding=True,
            photo_url=None
        )

        # 40 mph in 30 zone = 10 over (SHOULD appear)
        crud.create_speed_event(
            test_db,
            device_id=device.id,
            timestamp=now - timedelta(hours=4),
            speed=40.0,
            speed_limit=30.0,
            is_speeding=True,
            photo_url=None
        )

        result = crud.get_device_recent_speeders(test_db, device.id, limit=10)

        # Should only return events with >5 mph over limit
        assert len(result) == 2
        assert all((event.speed - event.speed_limit) > 5 for event in result)
        assert all(event.speed >= 36.0 for event in result)


# ============================================================================
# Run Tests
# ============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
