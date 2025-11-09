"""Tests for dashboard pages.

This module tests:
- Dashboard authentication requirements
- Dashboard homepage
- Device statistics display
"""

import pytest


class TestDashboard:
    """Test dashboard pages."""

    def test_dashboard_requires_auth(self, client):
        """Test that dashboard route redirects to login when not authenticated."""
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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
