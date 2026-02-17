"""
Tests for authentication endpoints.
"""
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_register_success(client: AsyncClient):
    """Test successful user registration."""
    response = await client.post(
        "/api/auth/register",
        json={
            "username": "newuser",
            "email": "newuser@example.com",
            "password": "SecurePass123",
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert "token" in data
    assert data["user"]["username"] == "newuser"
    assert data["user"]["email"] == "newuser@example.com"


@pytest.mark.asyncio
async def test_register_duplicate_username(client: AsyncClient, test_user):
    """Test registration with duplicate username."""
    response = await client.post(
        "/api/auth/register",
        json={
            "username": "testuser",  # Same as test_user
            "email": "different@example.com",
            "password": "SecurePass123",
        },
    )
    assert response.status_code == 400
    assert "already registered" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_register_duplicate_email(client: AsyncClient, test_user):
    """Test registration with duplicate email."""
    response = await client.post(
        "/api/auth/register",
        json={
            "username": "differentuser",
            "email": "test@example.com",  # Same as test_user
            "password": "SecurePass123",
        },
    )
    assert response.status_code == 400
    assert "already registered" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_register_weak_password(client: AsyncClient):
    """Test registration with weak password."""
    response = await client.post(
        "/api/auth/register",
        json={
            "username": "weakuser",
            "email": "weak@example.com",
            "password": "short",  # Too short
        },
    )
    assert response.status_code == 422  # Validation error


@pytest.mark.asyncio
async def test_login_success(client: AsyncClient, test_user):
    """Test successful login."""
    response = await client.post(
        "/api/auth/login",
        json={
            "username": "testuser",
            "password": "TestPass123",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert "token" in data
    assert data["user"]["username"] == "testuser"


@pytest.mark.asyncio
async def test_login_wrong_password(client: AsyncClient, test_user):
    """Test login with wrong password."""
    response = await client.post(
        "/api/auth/login",
        json={
            "username": "testuser",
            "password": "WrongPassword123",
        },
    )
    assert response.status_code == 401
    assert "invalid" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_login_nonexistent_user(client: AsyncClient):
    """Test login with nonexistent user."""
    response = await client.post(
        "/api/auth/login",
        json={
            "username": "nonexistent",
            "password": "SomePassword123",
        },
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_logout_success(authenticated_client: AsyncClient):
    """Test successful logout."""
    response = await authenticated_client.post("/api/auth/logout")
    assert response.status_code == 204


@pytest.mark.asyncio
async def test_logout_unauthenticated(client: AsyncClient):
    """Test logout without authentication."""
    response = await client.post("/api/auth/logout")
    assert response.status_code == 401
