"""Tests for device management features.

This module tests:
- Device listing page
- Device registration form
- Device registration
- Device detail page
- Access control for devices
"""

import pytest


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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
