# Nakh FastAPI

AI-powered tailoring platform for body measurement analysis.

## Overview

Nakh uses advanced AI models (PARE for 3D body reconstruction, MediaPipe for 2D pose estimation) to analyze user photos and extract accurate body measurements for tailoring purposes. Users upload front, T-pose, and side view photos, and the system generates precise measurements along with visualizations.

## Features

- **AI Body Measurement**: Extracts accurate body measurements from photos
- **3D Body Reconstruction**: PARE-based mesh generation from images
- **2D Pose Estimation**: MediaPipe integration for pose detection
- **Multi-View Analysis**: Combines front, T-pose, and side measurements
- **Bilingual Output**: Results available in English and Farsi (Persian)
- **Visualization Generation**: Silhouettes, 3D mannequins, Three.js-compatible configs
- **Token-Based Authentication**: Secure API access with auto-expiring tokens
- **Background Processing**: Celery-powered async processing for heavy computations
- **Rate Limiting**: Built-in API rate limiting per IP address

## Tech Stack

| Component | Technology |
|-----------|------------|
| Framework | FastAPI (Python 3.11+) |
| Database | Redis |
| Task Queue | Celery with Redis broker |
| AI/ML | PyTorch, PARE, MediaPipe, SMPL-X |
| Image Processing | OpenCV, Pillow |
| Server | Uvicorn (ASGI) |

## Quick Start

### Prerequisites

- Python 3.11+
- Redis 7+
- Docker & Docker Compose (optional)
- PARE model checkpoints (see AI Setup section)

### Local Development

1. **Clone and setup:**
   ```bash
   cd nakh-fastapi
   python -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   ```

2. **Configure environment:**
   ```bash
   cp .env.example .env
   # Edit .env with your settings
   ```

3. **Start Redis:**
   ```bash
   redis-server
   ```

4. **Run the application:**
   ```bash
   uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
   ```

5. **Run Celery worker (for background processing):**
   ```bash
   celery -A app.tasks.processing worker --loglevel=info --concurrency=1
   ```

6. **Run Celery beat (for scheduled cleanup):**
   ```bash
   celery -A app.tasks.cleanup beat --loglevel=info
   ```

### Docker Deployment

```bash
# Build and start all services
docker-compose up -d

# View logs
docker-compose logs -f

# Stop services
docker-compose down
```

For GPU support:
```bash
docker-compose -f docker-compose.yml -f docker-compose.gpu.yml up -d
```

## API Endpoints

### Authentication

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/auth/register` | User registration |
| POST | `/api/auth/login` | User login |
| POST | `/api/auth/logout` | User logout |

### Users

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/users/profile` | Get profile |
| PATCH | `/api/users/profile` | Update profile |
| POST | `/api/users/change-password` | Change password |

### Uploads

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/uploads` | List uploads (paginated) |
| POST | `/api/uploads` | Upload photos (1-3 images) |
| GET | `/api/uploads/{id}` | Get upload details |
| DELETE | `/api/uploads/{id}` | Delete upload |
| POST | `/api/uploads/{id}/process` | Trigger AI processing |
| GET | `/api/uploads/{id}/results` | Get processing results |

### Chat (Persian Chatbot)

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/chat/message` | Send message, get response |
| POST | `/api/chat/sessions` | Create chat session |
| GET | `/api/chat/sessions` | List chat sessions |
| GET | `/api/chat/sessions/{id}` | Get chat session |
| DELETE | `/api/chat/sessions/{id}` | Delete chat session |
| GET | `/api/chat/history/{id}` | Get chat history |
| DELETE | `/api/chat/history/{id}` | Clear chat history |
| GET | `/api/chat/preferences` | Get user preferences |
| PUT | `/api/chat/preferences` | Update user preferences |

### Health

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/health` | Health check |

## Authentication

The API uses Bearer token authentication:

```bash
# Register
curl -X POST http://localhost:8000/api/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username":"user1","email":"user@example.com","password":"Password123"}'

# Use the returned token
curl -X GET http://localhost:8000/api/users/profile \
  -H "Authorization: Bearer <your-token>"
```

Tokens expire after 7 days by default.

## API Documentation

Interactive API documentation is available when the server is running:
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

## Project Structure

```
nakh-fastapi/
├── app/
│   ├── main.py              # FastAPI app entry point
│   ├── config.py            # Pydantic Settings configuration
│   ├── database.py          # Redis storage layer
│   ├── api/                  # API routers
│   │   ├── auth.py          # Authentication endpoints
│   │   ├── users.py         # User management
│   │   ├── uploads.py       # Photo upload handling
│   │   ├── chat.py          # Persian chatbot endpoints
│   │   └── health.py        # Health check
│   ├── core/                 # Core utilities
│   │   ├── security.py      # Password hashing, token handling
│   │   ├── dependencies.py  # FastAPI dependencies
│   │   └── middleware.py    # Rate limiting, request logging
│   ├── schemas/              # Pydantic request/response models
│   │   └── chat.py          # Chat/preferences schemas
│   ├── services/             # Business logic layer
│   │   ├── chat_service.py  # Chat orchestration
│   │   ├── context_builder.py # Prompt building with user data
│   │   ├── product_service.py # Product recommendations
│   │   └── llm/             # LLM abstraction layer
│   │       ├── base.py      # Base provider interface
│   │       ├── transformers_provider.py  # HuggingFace models
│   │       ├── gguf_provider.py         # GGUF/llama.cpp models
│   │       └── manager.py   # LLM manager singleton
│   └── tasks/                # Celery background tasks
├── measure/                  # AI processing modules
│   ├── PARE/                # PARE model integration
│   ├── MediaPipe/           # MediaPipe utilities
│   ├── body_measurement.py  # Measurement extraction
│   └── silhouette.py        # Visualization generation
├── tests/                    # Test suite (pytest)
├── media/                    # User uploads and processed files
├── logs/                     # Application logs
├── .env.example              # Environment template
├── requirements.txt          # Python dependencies
├── Dockerfile
└── docker-compose.yml
```

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `SECRET_KEY` | Application secret key | Required |
| `DEBUG` | Enable debug mode | `false` |
| `REDIS_URL` | Redis connection URL | `redis://localhost:6379/0` |
| `CELERY_ENABLED` | Enable background processing | `true` |
| `CELERY_BROKER_URL` | Celery broker URL | `redis://localhost:6379/1` |
| `CELERY_RESULT_BACKEND` | Celery result backend | `redis://localhost:6379/2` |
| `CORS_ORIGINS` | CORS allowed origins (comma-separated) | `http://localhost:3000` |
| `RATE_LIMIT_ENABLED` | Enable rate limiting | `true` |
| `RATE_LIMIT_PER_MINUTE` | Requests per minute per IP | `30` |
| `MAX_UPLOAD_SIZE_MB` | Max upload file size | `10` |
| `TOKEN_EXPIRY_SECONDS` | Auth token TTL | `604800` (7 days) |
| `UPLOAD_EXPIRY_SECONDS` | Upload data TTL | `86400` (24 hours) |
| `LOG_LEVEL` | Logging level | `INFO` |
| `LLM_ENABLED` | Enable Persian chatbot | `true` |
| `LLM_MODEL_PATH` | Model path (HF or local) | Required for chat |
| `LLM_MODEL_TYPE` | Model type | `transformers` |
| `LLM_DEVICE` | Device for inference | `auto` |
| `SHOP_API_URL` | External shop API URL | Optional |

## Persian Chatbot

The application includes a Persian language chatbot that can:

- Discuss user's body measurements
- Help with clothing and fabric preferences
- Recommend products from the shop database
- Answer questions about sizing and styles

### Supported Persian LLMs

| Model | Type | Description |
|-------|------|-------------|
| `HooshvareLab/gpt2-fa` | HuggingFace | Persian GPT-2 |
| `m3hrdadfi/gpt2-persian` | HuggingFace | Persian GPT-2 variant |
| Dorna models | HuggingFace | Persian fine-tuned models |
| PersianLLaMA | GGUF | Quantized Persian LLaMA |

### Chatbot Setup

1. Set the model path in `.env`:
```bash
LLM_MODEL_PATH=HooshvareLab/gpt2-fa
LLM_DEVICE=cuda  # or cpu
```

2. For larger models with limited VRAM, enable quantization:
```bash
LLM_LOAD_IN_8BIT=True
# or for more aggressive quantization:
LLM_LOAD_IN_4BIT=True
```

3. For GGUF models (llama.cpp):
```bash
pip install llama-cpp-python
LLM_MODEL_PATH=/path/to/model.gguf
LLM_MODEL_TYPE=gguf
```

### Chat API Usage

```bash
# Send a message
curl -X POST http://localhost:8000/api/chat/message \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"message": "سلام، می‌خواهم یک پیراهن مناسب اندامم انتخاب کنم"}'
```

## AI Processing Pipeline

1. **Image Upload**: User uploads 1-3 photos (front, T-pose, side views)
2. **Enhancement**: Images preprocessed (contrast, brightness normalization)
3. **Video Creation**: Multiple views combined into video for PARE
4. **PARE Inference**: 3D body reconstruction using PARE model
5. **Measurement Extraction**: Body measurements from SMPL-X parameters
6. **Visualization**: Silhouettes and 3D mannequin images generated

### PARE Model Setup

Download PARE checkpoints and place them in:
```
measure/PARE/scripts/data/pare/checkpoints/
├── pare_w_3dpw_config.yaml
└── pare_w_3dpw_checkpoint.ckpt
```

## Supported Image Formats

- JPEG (.jpg, .jpeg)
- PNG (.png)
- HEIC/HEIF (.heic, .heif)

Maximum file size: 10 MB per image

## Testing

```bash
# Install test dependencies
pip install pytest pytest-asyncio httpx

# Run all tests
pytest

# Run with verbose output
pytest -v

# Run specific test file
pytest tests/test_auth.py

# Run with coverage
pytest --cov=app
```

## Data Storage

The application uses Redis for all data storage:

- **Users**: `user:{user_id}` with username/email index keys
- **Tokens**: `token:{token_key}` with 7-day TTL
- **Uploads**: `upload:{upload_id}` with 24-hour TTL
- **User Upload Lists**: `user_uploads:{user_id}`
- **Chat Sessions**: `chat_session:{session_id}` with 7-day TTL
- **Chat Messages**: `chat_messages:{session_id}` with 7-day TTL
- **User Preferences**: `user_preferences:{user_id}`

## License

Private - All rights reserved.
