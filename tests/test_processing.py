"""
Tests for processing functionality.
"""
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_trigger_processing_not_found(authenticated_client: AsyncClient):
    """Test triggering processing for non-existent upload."""
    response = await authenticated_client.post("/api/uploads/99999/process")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_results_not_found(authenticated_client: AsyncClient):
    """Test getting results for non-existent upload."""
    response = await authenticated_client.get("/api/uploads/99999/results")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_health_check(client: AsyncClient):
    """Test health check endpoint."""
    response = await client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert "status" in data
    assert "database" in data
