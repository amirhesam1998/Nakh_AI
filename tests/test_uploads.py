"""
Tests for upload endpoints.
"""
import io
import pytest
from httpx import AsyncClient
from PIL import Image


def create_test_image() -> bytes:
    """Create a simple test image."""
    img = Image.new("RGB", (100, 100), color="red")
    buffer = io.BytesIO()
    img.save(buffer, format="JPEG")
    buffer.seek(0)
    return buffer.read()


@pytest.mark.asyncio
async def test_list_uploads_empty(authenticated_client: AsyncClient):
    """Test listing uploads when empty."""
    response = await authenticated_client.get("/api/uploads")
    assert response.status_code == 200
    data = response.json()
    assert data["items"] == []
    assert data["total"] == 0


@pytest.mark.asyncio
async def test_list_uploads_unauthenticated(client: AsyncClient):
    """Test listing uploads without authentication."""
    response = await client.get("/api/uploads")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_create_upload_success(authenticated_client: AsyncClient):
    """Test successful upload creation."""
    image_data = create_test_image()

    response = await authenticated_client.post(
        "/api/uploads",
        files={
            "image1": ("test1.jpg", image_data, "image/jpeg"),
        },
        data={
            "height_cm": "175",
            "weight_kg": "70",
            "gender": "male",
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["height_cm"] == 175.0
    assert data["weight_kg"] == 70.0
    assert data["gender"] == "male"
    assert data["is_processed"] == False


@pytest.mark.asyncio
async def test_create_upload_with_multiple_images(authenticated_client: AsyncClient):
    """Test upload with multiple images."""
    image_data = create_test_image()

    response = await authenticated_client.post(
        "/api/uploads",
        files={
            "image1": ("front.jpg", image_data, "image/jpeg"),
            "image2": ("tpose.jpg", image_data, "image/jpeg"),
            "image3": ("side.jpg", image_data, "image/jpeg"),
        },
        data={
            "height_cm": "175",
            "weight_kg": "70",
            "gender": "male",
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["image_count"] == 3


@pytest.mark.asyncio
async def test_create_upload_invalid_file_type(authenticated_client: AsyncClient):
    """Test upload with invalid file type."""
    response = await authenticated_client.post(
        "/api/uploads",
        files={
            "image1": ("test.txt", b"not an image", "text/plain"),
        },
        data={
            "height_cm": "175",
        },
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_get_upload_not_found(authenticated_client: AsyncClient):
    """Test getting non-existent upload."""
    response = await authenticated_client.get("/api/uploads/99999")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_delete_upload_not_found(authenticated_client: AsyncClient):
    """Test deleting non-existent upload."""
    response = await authenticated_client.delete("/api/uploads/99999")
    assert response.status_code == 404
