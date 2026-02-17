"""
Tests for user profile endpoints.
"""
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_get_profile_success(authenticated_client: AsyncClient, test_user):
    """Test getting user profile."""
    response = await authenticated_client.get("/api/users/profile")
    assert response.status_code == 200
    data = response.json()
    assert data["username"] == test_user.username
    assert data["email"] == test_user.email


@pytest.mark.asyncio
async def test_get_profile_unauthenticated(client: AsyncClient):
    """Test getting profile without authentication."""
    response = await client.get("/api/users/profile")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_update_profile_username(authenticated_client: AsyncClient):
    """Test updating username."""
    response = await authenticated_client.patch(
        "/api/users/profile",
        json={"username": "newusername"},
    )
    assert response.status_code == 200
    assert response.json()["username"] == "newusername"


@pytest.mark.asyncio
async def test_update_profile_email(authenticated_client: AsyncClient):
    """Test updating email."""
    response = await authenticated_client.patch(
        "/api/users/profile",
        json={"email": "newemail@example.com"},
    )
    assert response.status_code == 200
    assert response.json()["email"] == "newemail@example.com"


@pytest.mark.asyncio
async def test_change_password_success(authenticated_client: AsyncClient):
    """Test successful password change."""
    response = await authenticated_client.post(
        "/api/users/change-password",
        json={
            "current_password": "TestPass123",
            "new_password": "NewSecurePass456",
        },
    )
    assert response.status_code == 204


@pytest.mark.asyncio
async def test_change_password_wrong_current(authenticated_client: AsyncClient):
    """Test password change with wrong current password."""
    response = await authenticated_client.post(
        "/api/users/change-password",
        json={
            "current_password": "WrongPassword123",
            "new_password": "NewSecurePass456",
        },
    )
    assert response.status_code == 400
    assert "incorrect" in response.json()["detail"].lower()
