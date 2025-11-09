"""Tests for device event retrieval.

This module tests:
- Device retrieving its own events
- Pagination
- Filtering by speeding events
"""

import pytest
from datetime import datetime, timedelta


class TestDeviceEventRetrieval:
    """Test device event retrieval endpoints."""

    def test_get_events_empty(self, client, test_device):
        """Test getting events when device has no events."""
        device, api_key = test_device

        response = client.get(
            "/api/ingest/v1/events",
            headers={"X-API-Key": api_key}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["device_id"] == "test-device-001"
        assert data["count"] == 0
        assert data["limit"] == 100
        assert data["offset"] == 0
        assert data["events"] == []

    def test_get_events_with_data(self, client, test_device, test_db):
        """Test getting events when device has events."""
        device, api_key = test_device

        # Create some test events
        from src.database import crud
        events_data = [
            {
                "device_id": device.id,
                "timestamp": datetime.utcnow() - timedelta(hours=i),
                "speed": 30.0 + i,
                "speed_limit": 25.0,
                "is_speeding": True,
                "photo_url": None
            }
            for i in range(5)
        ]

        for event_data in events_data:
            crud.create_speed_event(test_db, **event_data)

        response = client.get(
            "/api/ingest/v1/events",
            headers={"X-API-Key": api_key}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["device_id"] == "test-device-001"
        assert data["count"] == 5
        assert len(data["events"]) == 5

        # Verify events are ordered by timestamp (newest first)
        for i in range(len(data["events"]) - 1):
            current = datetime.fromisoformat(data["events"][i]["timestamp"].replace("Z", "+00:00"))
            next_event = datetime.fromisoformat(data["events"][i + 1]["timestamp"].replace("Z", "+00:00"))
            assert current >= next_event

    def test_get_events_pagination(self, client, test_device, test_db):
        """Test event pagination."""
        device, api_key = test_device

        # Create 25 test events
        from src.database import crud
        for i in range(25):
            crud.create_speed_event(
                test_db,
                device_id=device.id,
                timestamp=datetime.utcnow() - timedelta(minutes=i),
                speed=30.0,
                speed_limit=25.0,
                is_speeding=True
            )

        # Get first page (10 events)
        response = client.get(
            "/api/ingest/v1/events?limit=10&offset=0",
            headers={"X-API-Key": api_key}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 10
        assert data["limit"] == 10
        assert data["offset"] == 0

        # Get second page
        response = client.get(
            "/api/ingest/v1/events?limit=10&offset=10",
            headers={"X-API-Key": api_key}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 10
        assert data["limit"] == 10
        assert data["offset"] == 10

        # Get third page (partial)
        response = client.get(
            "/api/ingest/v1/events?limit=10&offset=20",
            headers={"X-API-Key": api_key}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 5
        assert data["limit"] == 10
        assert data["offset"] == 20

    def test_get_events_speeding_filter(self, client, test_device, test_db):
        """Test filtering for only speeding events."""
        device, api_key = test_device

        # Create mix of speeding and non-speeding events
        from src.database import crud
        for i in range(10):
            crud.create_speed_event(
                test_db,
                device_id=device.id,
                timestamp=datetime.utcnow() - timedelta(minutes=i),
                speed=30.0 if i % 2 == 0 else 20.0,
                speed_limit=25.0,
                is_speeding=i % 2 == 0
            )

        # Get only speeding events
        response = client.get(
            "/api/ingest/v1/events?speeding_only=true",
            headers={"X-API-Key": api_key}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 5
        assert data["speeding_only"] is True

        # Verify all returned events are speeding
        for event in data["events"]:
            assert event["is_speeding"] is True
            assert event["speed"] > event["speed_limit"]

    def test_get_events_unauthorized(self, client):
        """Test getting events without API key."""
        response = client.get("/api/ingest/v1/events")
        assert response.status_code == 422  # Missing header

    def test_get_events_invalid_api_key(self, client):
        """Test getting events with invalid API key."""
        response = client.get(
            "/api/ingest/v1/events",
            headers={"X-API-Key": "invalid_key"}
        )
        assert response.status_code == 401

    def test_get_events_wrong_device(self, client, test_device, test_db, test_user):
        """Test that device can only see its own events."""
        device1, api_key1 = test_device

        # Create a second device
        from src.auth_utils import generate_api_key, hash_api_key
        from src.database import crud

        api_key2 = generate_api_key()
        api_key_hash2 = hash_api_key(api_key2)

        device2 = crud.create_device(
            test_db,
            device_id="test-device-002",
            owner_id=test_user.id,
            latitude=40.7128,
            longitude=-74.0060,
            street_name="Second Street",
            speed_limit=30.0
        )
        crud.create_device_api_key(test_db, device2.id, api_key_hash2, name="Test API Key 2")

        # Create events for both devices
        crud.create_speed_event(
            test_db,
            device_id=device1.id,
            timestamp=datetime.utcnow(),
            speed=30.0,
            speed_limit=25.0,
            is_speeding=True
        )

        crud.create_speed_event(
            test_db,
            device_id=device2.id,
            timestamp=datetime.utcnow(),
            speed=35.0,
            speed_limit=30.0,
            is_speeding=True
        )

        # Device 1 should only see its own event
        response = client.get(
            "/api/ingest/v1/events",
            headers={"X-API-Key": api_key1}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 1
        assert data["events"][0]["speed"] == 30.0

        # Device 2 should only see its own event
        response = client.get(
            "/api/ingest/v1/events",
            headers={"X-API-Key": api_key2}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 1
        assert data["events"][0]["speed"] == 35.0

    def test_get_events_with_photos(self, client, test_device, test_db):
        """Test getting events with photo URLs."""
        device, api_key = test_device

        # Create event with photo
        from src.database import crud
        crud.create_speed_event(
            test_db,
            device_id=device.id,
            timestamp=datetime.utcnow(),
            speed=35.0,
            speed_limit=25.0,
            is_speeding=True,
            photo_url="https://storage.example.com/photos/test.jpg"
        )

        response = client.get(
            "/api/ingest/v1/events",
            headers={"X-API-Key": api_key}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 1
        assert data["events"][0]["photo_url"] == "https://storage.example.com/photos/test.jpg"

    def test_get_events_large_limit(self, client, test_device, test_db):
        """Test retrieving all events with a large limit."""
        device, api_key = test_device

        # Create 500 test events
        from src.database import crud
        for i in range(500):
            crud.create_speed_event(
                test_db,
                device_id=device.id,
                timestamp=datetime.utcnow() - timedelta(seconds=i),
                speed=30.0,
                speed_limit=25.0,
                is_speeding=True
            )

        # Request all events with large limit
        response = client.get(
            "/api/ingest/v1/events?limit=1000",
            headers={"X-API-Key": api_key}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 500
        assert data["limit"] == 1000


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
