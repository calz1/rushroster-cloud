"""Tests for event browsing features.

This module tests:
- Event listing page
- Event filtering by device
"""

import pytest


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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
