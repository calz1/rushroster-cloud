"""Tests for statistics dashboard.

This module tests:
- Statistics page
- Device filtering
- Period filtering
"""

import pytest


class TestStatistics:
    """Test statistics dashboard."""

    def test_stats_page_loads(self, authenticated_client):
        """Test statistics page loads."""
        client, cookies = authenticated_client
        response = client.get("/stats", cookies=cookies)
        assert response.status_code == 200
        assert b"Statistics Dashboard" in response.content
        assert b"Total Vehicles" in response.content
        assert b"Speeding Events" in response.content

    def test_stats_page_with_device_filter(self, authenticated_client, test_device):
        """Test statistics page with device filter."""
        client, cookies = authenticated_client
        device, _ = test_device

        response = client.get(f"/stats?device_id={device.id}", cookies=cookies)
        assert response.status_code == 200
        assert b"Statistics Dashboard" in response.content

    def test_stats_page_with_period_filter(self, authenticated_client):
        """Test statistics page with period filter."""
        client, cookies = authenticated_client

        for period in ["24h", "7d", "30d", "90d"]:
            response = client.get(f"/stats?period={period}", cookies=cookies)
            assert response.status_code == 200
            assert b"Statistics Dashboard" in response.content


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
