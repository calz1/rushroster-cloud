"""Tests for photo upload workflow.

This module tests:
- Photo upload URL generation
- Photo file upload to local storage
- Photo upload confirmation
- Absolute URL conversion for local storage
- Photo retrieval from storage
"""

import pytest
from datetime import datetime
from io import BytesIO
from pathlib import Path
import tempfile
import shutil


class TestPhotoUploadWorkflow:
    """Test complete photo upload workflow."""

    def test_request_upload_url(self, client, test_device, test_db):
        """Test requesting a pre-signed upload URL."""
        device, api_key = test_device

        # Create a speed event with photo flag
        from src.database import crud
        event = crud.create_speed_event(
            test_db,
            device_id=device.id,
            timestamp=datetime.utcnow(),
            speed=35.0,
            speed_limit=25.0,
            is_speeding=True
        )

        # Request upload URL
        response = client.post(
            f"/api/ingest/v1/events/{event.id}/photo/url",
            headers={"X-API-Key": api_key}
        )

        assert response.status_code == 200
        data = response.json()

        # Verify response structure
        assert "event_id" in data
        assert "upload_url" in data
        assert "photo_key" in data
        assert "expires_in" in data

        # Verify event ID matches
        assert data["event_id"] == str(event.id)

        # Verify URL is absolute (not relative) for local storage
        assert data["upload_url"].startswith("http://")
        assert "/api/storage/upload/" in data["upload_url"]

        # Verify photo key structure
        assert data["photo_key"].startswith(f"photos/{device.id}/")
        assert data["photo_key"].endswith(f"/{event.id}.jpg")

        # Verify expiration
        assert data["expires_in"] == 3600

    def test_request_upload_url_wrong_device(self, client, test_device, test_db, test_user):
        """Test that device cannot request upload URL for another device's event."""
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

        # Create event for device 2
        event = crud.create_speed_event(
            test_db,
            device_id=device2.id,
            timestamp=datetime.utcnow(),
            speed=35.0,
            speed_limit=30.0,
            is_speeding=True
        )

        # Try to request upload URL with device 1's API key
        response = client.post(
            f"/api/ingest/v1/events/{event.id}/photo/url",
            headers={"X-API-Key": api_key1}
        )

        assert response.status_code == 403
        assert "does not belong to this device" in response.json()["detail"]

    def test_request_upload_url_nonexistent_event(self, client, test_device):
        """Test requesting upload URL for non-existent event."""
        device, api_key = test_device

        # Use a random UUID
        from uuid import uuid4
        fake_event_id = uuid4()

        response = client.post(
            f"/api/ingest/v1/events/{fake_event_id}/photo/url",
            headers={"X-API-Key": api_key}
        )

        assert response.status_code == 404
        assert "Event not found" in response.json()["detail"]

    def test_upload_photo_to_local_storage(self, client, test_device, test_db):
        """Test complete workflow: request URL, upload photo, confirm."""
        device, api_key = test_device

        # Create a speed event
        from src.database import crud
        event = crud.create_speed_event(
            test_db,
            device_id=device.id,
            timestamp=datetime.utcnow(),
            speed=35.0,
            speed_limit=25.0,
            is_speeding=True
        )

        # Step 1: Request upload URL
        response = client.post(
            f"/api/ingest/v1/events/{event.id}/photo/url",
            headers={"X-API-Key": api_key}
        )
        assert response.status_code == 200
        data = response.json()
        photo_key = data["photo_key"]
        upload_url = data["upload_url"]

        # Extract the path from the absolute URL
        # URL format: http://testserver/api/storage/upload/{photo_key}
        upload_path = upload_url.split("/api/storage/upload/")[-1]

        # Step 2: Create a fake image file
        fake_image = BytesIO(b"fake image content for testing")
        fake_image.name = "test.jpg"

        # Upload the photo
        response = client.put(
            f"/api/storage/upload/{upload_path}",
            files={"file": ("test.jpg", fake_image, "image/jpeg")}
        )

        assert response.status_code == 200
        upload_data = response.json()
        assert upload_data["status"] == "success"
        assert upload_data["key"] == photo_key

        # Step 3: Confirm the upload
        response = client.post(
            f"/api/ingest/v1/events/{event.id}/photo/confirm",
            params={"photo_key": photo_key},
            headers={"X-API-Key": api_key}
        )

        assert response.status_code == 200
        confirm_data = response.json()
        assert confirm_data["status"] == "success"
        assert "photo_url" in confirm_data

        # Step 4: Verify the event was updated with photo URL
        test_db.refresh(event)
        assert event.photo_url is not None
        assert photo_key in event.photo_url

    def test_batch_upload_with_photos(self, client, test_device):
        """Test uploading batch events with photo flags."""
        device, api_key = test_device

        # Upload batch of events with has_photo flags
        batch_data = {
            "events": [
                {
                    "timestamp": datetime.utcnow().isoformat(),
                    "speed": 35.0,
                    "speed_limit": 25.0,
                    "is_speeding": True,
                    "has_photo": True
                },
                {
                    "timestamp": datetime.utcnow().isoformat(),
                    "speed": 30.0,
                    "speed_limit": 25.0,
                    "is_speeding": True,
                    "has_photo": False
                },
                {
                    "timestamp": datetime.utcnow().isoformat(),
                    "speed": 40.0,
                    "speed_limit": 25.0,
                    "is_speeding": True,
                    "has_photo": True
                }
            ]
        }

        response = client.post(
            "/api/ingest/v1/events",
            json=batch_data,
            headers={"X-API-Key": api_key}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["processed"] == 3
        assert len(data["created_events"]) == 3

        # Verify has_photo flags
        created_events = data["created_events"]
        assert created_events[0]["has_photo"] is True
        assert created_events[1]["has_photo"] is False
        assert created_events[2]["has_photo"] is True

        # All events should have event_id for upload
        for event in created_events:
            assert "event_id" in event

    def test_confirm_photo_wrong_device(self, client, test_device, test_db, test_user):
        """Test that device cannot confirm photo for another device's event."""
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

        # Create event for device 2
        event = crud.create_speed_event(
            test_db,
            device_id=device2.id,
            timestamp=datetime.utcnow(),
            speed=35.0,
            speed_limit=30.0,
            is_speeding=True
        )

        # Try to confirm with device 1's API key
        response = client.post(
            f"/api/ingest/v1/events/{event.id}/photo/confirm",
            params={"photo_key": f"photos/{device2.id}/2025/10/{event.id}.jpg"},
            headers={"X-API-Key": api_key1}
        )

        assert response.status_code == 403
        assert "does not belong to this device" in response.json()["detail"]

    def test_download_photo(self, client, test_device, test_db):
        """Test downloading a photo from local storage."""
        device, api_key = test_device

        # Create event and upload photo
        from src.database import crud
        event = crud.create_speed_event(
            test_db,
            device_id=device.id,
            timestamp=datetime.utcnow(),
            speed=35.0,
            speed_limit=25.0,
            is_speeding=True
        )

        # Request upload URL
        response = client.post(
            f"/api/ingest/v1/events/{event.id}/photo/url",
            headers={"X-API-Key": api_key}
        )
        data = response.json()
        photo_key = data["photo_key"]
        upload_url = data["upload_url"]
        upload_path = upload_url.split("/api/storage/upload/")[-1]

        # Upload photo
        fake_image = BytesIO(b"fake image content for testing")
        response = client.put(
            f"/api/storage/upload/{upload_path}",
            files={"file": ("test.jpg", fake_image, "image/jpeg")}
        )
        assert response.status_code == 200

        # Download the photo
        response = client.get(f"/api/storage/files/{photo_key}")

        assert response.status_code == 200
        assert response.content == b"fake image content for testing"

    def test_download_nonexistent_photo(self, client):
        """Test downloading a photo that doesn't exist."""
        response = client.get("/api/storage/files/photos/nonexistent/2025/10/fake.jpg")

        assert response.status_code == 404
        assert "File not found" in response.json()["detail"]


class TestPhotoURLConversion:
    """Test URL conversion for local storage."""

    def test_absolute_url_for_local_storage(self, client, test_device, test_db):
        """Test that local storage returns absolute URLs."""
        device, api_key = test_device

        # Create event
        from src.database import crud
        event = crud.create_speed_event(
            test_db,
            device_id=device.id,
            timestamp=datetime.utcnow(),
            speed=35.0,
            speed_limit=25.0,
            is_speeding=True
        )

        # Request upload URL
        response = client.post(
            f"/api/ingest/v1/events/{event.id}/photo/url",
            headers={"X-API-Key": api_key}
        )

        assert response.status_code == 200
        data = response.json()

        # URL should be absolute, not relative
        assert data["upload_url"].startswith("http://")
        assert "testserver" in data["upload_url"] or "localhost" in data["upload_url"]
        assert not data["upload_url"].startswith("/api/")

    def test_photo_key_structure(self, client, test_device, test_db):
        """Test that photo keys follow the correct structure."""
        device, api_key = test_device

        # Create event
        from src.database import crud
        event = crud.create_speed_event(
            test_db,
            device_id=device.id,
            timestamp=datetime.utcnow(),
            speed=35.0,
            speed_limit=25.0,
            is_speeding=True
        )

        # Request upload URL
        response = client.post(
            f"/api/ingest/v1/events/{event.id}/photo/url",
            headers={"X-API-Key": api_key}
        )

        data = response.json()
        photo_key = data["photo_key"]

        # Verify structure: photos/{device_id}/{year}/{month}/{event_id}.jpg
        parts = photo_key.split("/")
        assert len(parts) == 5
        assert parts[0] == "photos"
        assert parts[1] == str(device.id)
        assert parts[2].isdigit()  # year
        assert parts[3].isdigit()  # month
        assert parts[4] == f"{event.id}.jpg"


class TestPhotoStorageCleaning:
    """Test photo storage cleanup and management."""

    def test_multiple_photos_same_device(self, client, test_device, test_db):
        """Test uploading multiple photos from the same device."""
        device, api_key = test_device
        from src.database import crud

        # Create and upload 3 photos
        event_ids = []
        for i in range(3):
            event = crud.create_speed_event(
                test_db,
                device_id=device.id,
                timestamp=datetime.utcnow(),
                speed=35.0 + i,
                speed_limit=25.0,
                is_speeding=True
            )
            event_ids.append(event.id)

            # Request upload URL
            response = client.post(
                f"/api/ingest/v1/events/{event.id}/photo/url",
                headers={"X-API-Key": api_key}
            )
            assert response.status_code == 200
            data = response.json()
            upload_path = data["upload_url"].split("/api/storage/upload/")[-1]

            # Upload photo
            fake_image = BytesIO(f"image {i}".encode())
            response = client.put(
                f"/api/storage/upload/{upload_path}",
                files={"file": (f"test{i}.jpg", fake_image, "image/jpeg")}
            )
            assert response.status_code == 200

            # Confirm upload
            response = client.post(
                f"/api/ingest/v1/events/{event.id}/photo/confirm",
                params={"photo_key": data["photo_key"]},
                headers={"X-API-Key": api_key}
            )
            assert response.status_code == 200

        # Refresh the session to get latest data
        test_db.expire_all()

        # Verify all 3 events have photo URLs
        events = crud.get_device_events(test_db, device_id=device.id, limit=10)
        assert len(events) == 3

        # Count how many events have photo URLs
        events_with_photos = sum(1 for event in events if event.photo_url is not None)
        assert events_with_photos == 3, f"Expected 3 events with photos, but found {events_with_photos}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
