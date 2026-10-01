# Nakh AI

**AI-Powered Smart Tailoring Platform** — Precision body measurement from photos, personalized clothing recommendations, and Persian-language AI consultation.

Nakh AI is the intelligent backend of a two-tier e-commerce tailoring platform. It receives user photos, reconstructs 3D body meshes, extracts accurate measurements, and generates personalized product recommendations by combining computer vision, 3D reconstruction, and large language models.

---

## Table of Contents

- [System Architecture](#system-architecture)
- [AI Body Measurement Pipeline](#ai-body-measurement-pipeline)
  - [Image Validation & Quality Scoring](#1-image-validation--quality-scoring)
  - [Image Enhancement](#2-image-enhancement)
  - [PARE 3D Body Reconstruction](#3-pare-3d-body-reconstruction)
  - [Consensus Mesh Fusion](#4-consensus-mesh-fusion)
  - [Measurement Extraction](#5-measurement-extraction)
  - [Calibration & Correction](#6-calibration--learned-correction)
  - [Confidence & Sanity Validation](#7-confidence--sanity-validation)
  - [Visualization](#8-visualization)
- [Recommendation System](#recommendation-system)
  - [Stage 1: CMS Product Query](#stage-1-cms-product-query)
  - [Stage 2: Python Attribute Scoring](#stage-2-python-attribute-scoring)
  - [Stage 3: LLM Consultation](#stage-3-llm-consultation)
- [AI Consultation Layer](#ai-consultation-layer)
- [Technical Stack](#technical-stack)
- [Quick Start](#quick-start)
- [API Reference](#api-reference)
- [Configuration](#configuration)
- [Docker Deployment](#docker-deployment)
- [Project Structure](#project-structure)
- [Performance & Scalability](#performance--scalability)
- [Security & Reliability](#security--reliability)
- [Future Roadmap](#future-roadmap)

---

## System Architecture

```
                        +---------------------+
                        |   Frontend (Blade)   |
                        |   Questionnaire UI   |
                        +----------+----------+
                                   |
                    +--------------+--------------+
                    |                              |
          +---------v----------+       +-----------v-----------+
          |   Laravel CMS      |       |   FastAPI (Nakh AI)    |
          |   (Product DB)     |<----->|   Python 3.11+         |
          |   - Categories     |  HTTP |   - Body Measurement   |
          |   - Products       |  API  |   - Recommendations    |
          |   - Variants       |       |   - LLM Chat           |
          |   - Attributes     |       |   - Image Processing   |
          +--------------------+       +-----------+-----------+
                                                   |
                                       +-----------+-----------+
                                       |                       |
                                +------v------+    +-----------v---------+
                                |   Ollama    |    |   Redis + Celery    |
                                |   LLM       |    |   Task Queue        |
                                +-------------+    +---------------------+
```

**Two-tier architecture:**
- **Laravel CMS** — Product catalog, categories, variants, attributes, user management
- **FastAPI (this repo)** — All AI/ML workloads: body measurement, recommendation scoring, LLM generation

The frontend sends questionnaire answers and photos to the AI service, which fetches candidate products from the CMS API, scores them against user preferences, and generates personalized recommendations via an LLM.

---

## AI Body Measurement Pipeline

The measurement pipeline transforms 1–4 user photos into precise body measurements through an 8-stage process:

```
Photos → Validation → Enhancement → PARE (3D Mesh) → Consensus Fusion
       → Measurement Extraction → Calibration → Confidence Scoring → Output
```

### 1. Image Validation & Quality Scoring

**File:** `measure/image_validator.py`, `measure/quality_score.py`

Before any ML inference, each image passes through validation gates:

| Check | Method | Reject | Warn |
|-------|--------|--------|------|
| **Blur** | Laplacian variance | < 50 | 50–100 |
| **Lighting** | Mean pixel brightness | < 40 (dark) | > 240 (overexposed) |
| **Body framing** | Body-to-image height ratio | — | < 0.50 or > 0.95 |
| **Pose detection** | MediaPipe PoseLandmarker (33 landmarks) | No person detected | Low visibility |
| **Pose template** | Per-view landmark checks | Wrong pose for view | — |

**Pose template rules:**
- **front_a** (A-pose front): Shoulders and hips level (dy < 0.12), wrists visible between shoulders and hips
- **front_t** (T-pose front): Arm span > 1.5x shoulder width, wrists at shoulder height
- **side**: Not both shoulders symmetrically visible
- **back_a**: Nose not confidently detected (visibility < 0.95)

**Quality score formula:**
```
quality = mp_visibility                          # base: mean landmark visibility [0,1]
        × (0.5  if blur_score < 100)             # blur penalty
        × (0.7  if body_ratio out of range)      # framing penalty
        × (0.4  if pose template invalid)        # pose penalty
→ clamped to [0, 1]
```

### 2. Image Enhancement

**File:** `measure/image_enhancement.py`

An adaptive preprocessing pipeline maximizes PARE's reconstruction accuracy:

1. **Format conversion** — HEIF/HEIC to JPEG via `pillow_heif`
2. **ICC color profile** — Force sRGB conversion for consistent color
3. **CLAHE** — Contrast Limited Adaptive Histogram Equalization
4. **Adaptive gamma correction** — Based on mean luminance
5. **Bilateral filtering** + unsharp masking for edge preservation
6. **Conditional sharpening** — Applied only when blur_score < 120
7. **Conditional denoising** — `cv2.fastNlMeansDenoisingColored()` when noise sigma >= 12
8. **Auto-upright** — Hough line detection with IQR-trimmed angle estimation, roll + shear correction

### 3. PARE 3D Body Reconstruction

**Files:** `measure/model_registry.py`, `measure/PARE/`

PARE (Part Attention Regressor) reconstructs a full 3D SMPL body mesh from a single image:

```
Input Image (224×224) → HRNet Backbone → Part-Based Attention → Iterative Regression
                      → SMPL Parameters: shape (10-D β), pose (72-D θ), camera (3-D)
                      → SMPL Forward: 6,890 vertices + 45 joints in 3D
```

**Key architecture details:**
- **Backbone:** HRNet-W32 (primary), with ResNet and MobileNet alternatives
- **Attention:** Keypoint attention + co-attention modules for part-level focus
- **Regression:** Iterative refinement passes for pose/shape convergence
- **Output per frame:**
  - `pred_shape`: 10-D SMPL shape betas (body proportions)
  - `pred_pose`: 72-D axis-angle pose vector (24 joints × 3)
  - `smpl_vertices`: (6890, 3) mesh vertex positions
  - `smpl_joints3d`: (49, 3) joint positions (PARE/OpenPose convention)

**GPU acceleration:**
- Auto-detects CUDA; falls back to CPU
- Mixed-precision inference (`torch.amp.autocast`) for ~50% memory savings and 1.5–2x speedup
- Warm-up pass on CUDA to pre-compile kernels
- `torch.cuda.empty_cache()` after each batch

### 4. Consensus Mesh Fusion

**File:** `measure/consensus_mesh.py`

When multiple views are available, their shape estimates are fused into a single consensus mesh:

```python
# Per-view: PARE → shape betas (10-D) + quality score
# Fusion:   weighted average of betas, quality as weight
consensus_betas = Σ(quality_i × betas_i) / Σ(quality_i)
```

**View weighting rules:**
- T-pose views are downweighted (0.5x) due to torso distortion from raised arms
- Only views with quality > 0.0 contribute
- Supported views: `front_a`, `side`, `back_a`, `front_t`

**Canonical A-pose:** The consensus betas are applied to a canonical A-pose (arms ~30° from body, legs ~10° apart) to produce the final measurement mesh — eliminating pose-dependent distortions.

```python
CANONICAL_APOSE = np.zeros(72)
CANONICAL_APOSE[50] = -0.52   # left shoulder Z  (arm ~30° down)
CANONICAL_APOSE[53] = +0.52   # right shoulder Z
CANONICAL_APOSE[5]  = +0.17   # left hip Z       (leg ~10° apart)
CANONICAL_APOSE[8]  = -0.17   # right hip Z
```

### 5. Measurement Extraction

**File:** `measure/body_measurement.py`

The `BodyMeasurement` class extracts 12 measurements from the consensus mesh using cross-section scanning and joint-based geometric computation.

#### Height Rescaling
```python
scale_factor = user_height_cm / 100.0 / mesh_height
vertices_scaled = vertices * scale_factor
```

#### BMI-Based Width Scaling
Circumferences are adjusted by a BMI-derived width scale to compensate for SMPL's limited shape space:
```
width_scale = clamp(((bmi / 23.0) ^ 0.15), [0.90, 1.12])
```
Applied only to circumferences (not lengths) to prevent frame distortion.

#### Circumference Measurements (7)

Cross-section scanning with **alpha-shape (concave hull)** perimeter computation:

| Measurement | Y-Range | Vertex Filter | Method |
|-------------|---------|---------------|--------|
| **Chest** | neck−0.02 to waist midpoint | Torso (parts 0,3,6,9) | Horizontal scan, median perimeter |
| **Waist** | pelvis+0.03 to mid(neck,pelvis) | Torso | Horizontal scan, median perimeter |
| **Hip** | hip joints ±0.18m | Torso + Thigh (parts 0,3,6,9,1,2) | Horizontal scan, median perimeter |
| **Neck** | Actual neck vertex Y range | Neck (part 12) | Horizontal scan, median perimeter |
| **Upper Arm** | Along shoulder→elbow segment | Upper arm (parts 13,14,16,17) | Orthogonal slice, max of t∈[0.3–0.6] |
| **Thigh** | Along hip→knee segment | Thigh (parts 1,2) | Orthogonal slice |
| **Calf** | Along knee→ankle segment | Calf (parts 4,5) | Orthogonal slice |

**Alpha-shape algorithm** (`measure/alpha_shape.py`):
1. Deduplicate near-coincident points (tolerance: 1e-6)
2. Compute Delaunay triangulation of cross-section
3. Auto-alpha = 1 / median(edge_lengths)
4. Filter triangles: keep only those with circumradius < 1/alpha
5. Extract boundary edges (appearing in exactly 1 triangle)
6. Sum boundary edge lengths → perimeter

**IQR outlier rejection** on scan slices: Q1−1.5×IQR to Q3+1.5×IQR

#### Length Measurements (5)

Computed from joint positions:

| Measurement | Formula |
|-------------|---------|
| **Shoulder Width** | ‖left_shoulder − right_shoulder‖ |
| **Sleeve Length** | (‖shoulder→elbow‖ + ‖elbow→wrist‖), avg L+R |
| **Pants Outseam** | hip_Y − ground_Y |
| **Top Length** | neck_Y − (hip_mean_Y + 0.02) |
| **Gown Length** | neck_Y − ground_Y |

### 6. Calibration & Learned Correction

**Files:** `measure/calibration.py`, `measure/learned_correction.py`

**Offset calibration** — Additive offsets per measurement, per body model (adult/teen/child):
```python
result[key] += calibration_offset[body_model][key]
# Offsets computed as: mean(ground_truth - predicted) over training set
```

**Learned linear correction** — Per-measurement regression model:
```
corrected = slope × raw + intercept + feature_weights @ [height, bmi, width_scale, is_male, body_model]
```

Trained via least-squares on paired ground-truth data for 10 measurement keys.

### 7. Confidence & Sanity Validation

**Files:** `measure/confidence.py`, `measure/sanity_validator.py`

**Per-measurement confidence:**
```
confidence = 0.35 × quality_component      # mean quality of relevant views
           + 0.35 × stability_component    # cross-section scan stability
           + 0.30 × sanity_component       # (1.0 − 0.25 × n_warnings)
→ clamped to [0, 1]
```

Each measurement has a **view relevance map** — e.g., chest confidence depends on `front_a` + `side` quality scores, sleeve length depends on `front_t`.

**Sanity validation** performs two checks:
- **Absolute ranges** — Anthropometric bounds per body model (e.g., adult chest: 70–145 cm)
- **Body-proportion ratios** — Cross-measurement consistency (e.g., waist/hip ratio: 0.58–1.08)

### 8. Visualization

**Files:** `measure/body_silhouette.py`, `measure/body_mannequin.py`

| Output | Description | Method |
|--------|-------------|--------|
| **Front Silhouette** | 2D outline from measurements | Circumference → half-width via Ramanujan ellipse, interpolated curves, mirrored polygon |
| **3D Mannequin** | Detailed body drawing | Head + neck + torso (multi-point polygon) + arms + legs with taper ratios |
| **Side-by-Side** | Before/after comparison | `silhouette_compare.py` |

**Ramanujan ellipse approximation** (circumference → width):
```
C ≈ π × (3(a+b) − √((3a+b)(a+3b)))
where a = half_width, b = depth_ratio × half_width
```

**MediaPipe single-image fallback** (`measure/mediapipe_single.py`): When PARE is unavailable, estimates measurements from 2D landmarks using anthropometric proportions and depth ratios per body part.

---

## Recommendation System

A 3-stage pipeline transforms questionnaire answers into personalized product recommendations:

```
User Answers → [Stage 1: CMS Query] → [Stage 2: Python Scoring] → [Stage 3: LLM Generation]
                  40 products              20 scored                  5–10 recommended
```

### Stage 1: CMS Product Query

**File:** `app/services/product_service.py`

Fetches a broad candidate pool from the Laravel CMS using only **structurally safe filters**:

| Filter | Source | Notes |
|--------|--------|-------|
| `category` | "garment" or "fabric" | From questionnaire step 1 |
| `subcategory` | Product type slug | e.g., "shirt", "pants" |
| `gender` | "male" / "female" | From questionnaire |
| `min_price` / `max_price` | Budget range | Optional |

**Limit:** 40 products per query (`_CMS_FETCH_LIMIT`)

**Why not filter by attributes at CMS level?** Attribute filters (occasion, season, color) cause the CMS PHP process to hang indefinitely. This was confirmed through systematic testing — only structural filters are safe.

**Progressive relaxation:** If no results, the query progressively drops min_price → max_price → subcategory to ensure a non-empty candidate pool.

**Multi-product support:** For multi-product questionnaires (e.g., user selects both "shirt" and "pants"), separate CMS queries run per product type, with deduplication by product ID.

### Stage 2: Python Attribute Scoring

**File:** `app/services/product_service.py` — `score_product_relevance()`

Each candidate product is scored against the user's questionnaire answers using weighted fuzzy substring matching:

```python
score = matched_weight / total_weight    # 0.0 to 1.0
```

**Attribute weights:**

| Attribute | Weight | Questionnaire Key | CMS Variant Fields |
|-----------|--------|-------------------|--------------------|
| Style | 0.25 | استایل / سبک | style |
| Occasion | 0.20 | مناسبت | occasion |
| Season | 0.15 | فصل | season |
| Colors | 0.15 | رنگ | color |
| Size | 0.15 | سایز / اندازه | size |
| Material | 0.05 | جنس / جنس پارچه | material |
| Pattern | 0.03 | طرح | pattern |
| Weave | 0.01 | بافت | weave |
| Usage | 0.01 | کاربرد | usage |

**Matching algorithm:**
1. Tokenize user answers and product attributes on commas (Persian `،` and English `,`) and whitespace
2. For each attribute: check if any user token is a substring of any product token (or vice versa)
3. If match found → add attribute weight to `matched_weight`
4. Unanswered preferences don't penalize; missing product data incurs a small penalty

Products are sorted by score descending; top 20 are passed to Stage 3.

### Stage 3: LLM Consultation

**File:** `app/api/recommendations.py`

The top-scored products are presented to an LLM (via Ollama) in a structured Persian prompt:

**Prompt structure:**
1. Role definition — "مشاور لباس و استایلیست شخصی" (Personal clothing advisor and stylist)
2. User measurements and calculated size
3. Questionnaire answers (preferences)
4. Numbered product list with specs, sizes, brand, price
5. Output format instruction: `{"picks": [1-based indices]}` followed by narrative

**LLM output parsing:**
- Extracts JSON picks array (1-based indices → 0-based)
- Extracts Persian narrative text
- Falls back to `_build_fallback_text()` if LLM unavailable

**Prompt safety:**
- `_safe()` escapes backticks, chat-template delimiters (`<|...|>`), newlines
- Field length capped at 200 characters
- Max 10 products per prompt (scales with product types)

**Blocking prevention:** `asyncio.to_thread()` wraps the synchronous Ollama HTTP call to prevent blocking the FastAPI event loop.

---

## AI Consultation Layer

**Files:** `app/services/chat_service.py`, `app/services/context_builder.py`, `app/services/llm/`

### Persian Chat System

A conversational AI assistant that discusses measurements, recommends products, and answers sizing questions — all in Persian.

**Chat flow:**
1. User sends message → sanitized (2000 char cap, stripped delimiters)
2. `ContextBuilder` assembles system prompt with user's measurements, preferences, and translated terminology
3. `LLMManager` dispatches to the configured provider
4. Response checked for product recommendation keywords → triggers product fetch if relevant
5. Session, messages, and preferences persisted as JSON files

**Measurement translations** (English → Persian):
- height → قد, chest → دور سینه, waist → دور کمر, hips → دور باسن
- shoulder_width → عرض شانه, arm_length → طول دست, neck → دور گردن

### LLM Provider Abstraction

Three interchangeable backends behind a unified `BaseLLMProvider` interface:

| Provider | Backend | Format | Best For |
|----------|---------|--------|----------|
| `OllamaProvider` | Ollama HTTP API (`/api/chat`) | System + User messages | Production (recommended) |
| `TransformersProvider` | HuggingFace `AutoModelForCausalLM` | ChatML or Persian format | Direct GPU inference |
| `GGUFProvider` | `llama-cpp-python` | Llama-2 chat format | Low-memory quantized models |

**OllamaProvider** (primary):
- Uses `/api/chat` endpoint (not `/api/generate`) for proper instruction-following
- Smart prompt splitting: separates system and user messages via `\n---` separator
- Timeout: 180s read (CPU inference on large models can be slow)
- Returns `LLMResponse(text, tokens_used, finish_reason, model_name)`

**`LLMManager`** — Singleton that handles provider selection, model loading at startup, and generation dispatch. Configured via environment variables.

---

## Technical Stack

| Component | Technology |
|-----------|------------|
| **Framework** | FastAPI (Python 3.11+, ASGI) |
| **3D Reconstruction** | PARE (HRNet backbone) + SMPL body model |
| **Pose Estimation** | MediaPipe PoseLandmarker (33 landmarks) |
| **ML Runtime** | PyTorch (CUDA + AMP mixed precision) |
| **LLM Integration** | Ollama (primary), HuggingFace Transformers, llama-cpp-python |
| **Image Processing** | OpenCV, Pillow, pillow-heif |
| **HTTP Client** | httpx (async for CMS, sync for Ollama) |
| **Task Queue** | Celery with Redis broker |
| **Data Storage** | Redis (users, tokens, uploads) + JSON files (chat sessions) |
| **Server** | Uvicorn (ASGI) |
| **Containerization** | Docker multi-stage build, Docker Compose |
| **CMS Backend** | Laravel (PHP 8.2) — separate repo |

---

## Quick Start

### Prerequisites

- Python 3.11
- [uv](https://docs.astral.sh/uv/getting-started/installation/)
- Redis 7+
- Ollama (for LLM features)
- PARE model checkpoints
- Docker & Docker Compose (optional)

### Local Development

```bash
# Clone and set up the locked environment
cd Nakh_AI
uv sync

# Configure
cp .env.example .env
# Edit .env — set LLM_MODEL_PATH, SHOP_API_URL, etc.

# Start dependencies
redis-server
ollama serve  # In separate terminal

# Pull an LLM model
ollama pull gemma2:9b

# Run the application
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# (Optional) Celery worker for background processing
uv run celery -A app.tasks.processing worker --loglevel=info --concurrency=1
```

### PARE Model Setup

Download PARE checkpoints and place them in:
```
measure/PARE/scripts/data/pare/checkpoints/
├── pare_w_3dpw_config.yaml
└── pare_w_3dpw_checkpoint.ckpt
```

Also required:
```
measure/PARE/scripts/data/body_models/smpl/    # SMPL model weights
measure/PARE/scripts/data/pose_landmarker_lite.task  # MediaPipe model
```

---

## API Reference

### Authentication
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/auth/register` | User registration |
| POST | `/api/v1/auth/login` | User login |
| POST | `/api/v1/auth/logout` | User logout |

### Uploads & Measurement
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/uploads` | Upload 1–4 photos |
| POST | `/api/v1/uploads/{id}/process` | Trigger AI measurement pipeline |
| GET | `/api/v1/uploads/{id}/results` | Get measurements + visualizations |

### Recommendations
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/recommendations` | Generate personalized recommendations |
| POST | `/api/v1/recommendations/size-recommendation` | Get size from available sizes |

### Chat
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/chat/message` | Send message, get AI response |
| POST | `/api/v1/chat/sessions` | Create chat session |
| GET | `/api/v1/chat/sessions` | List user's sessions |
| GET | `/api/v1/chat/history/{id}` | Get conversation history |

### Health
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/health` | Health check |

Interactive docs available at `/docs` (Swagger) and `/redoc` (ReDoc) when running.

---

## Configuration

Key environment variables (see `.env.example` for full list):

| Variable | Description | Default |
|----------|-------------|---------|
| `SECRET_KEY` | Application secret key | Required |
| `REDIS_URL` | Redis connection URL | `redis://localhost:6379/0` |
| `LLM_MODEL_PATH` | Ollama model name or HF path | Required for AI features |
| `LLM_MODEL_TYPE` | `ollama`, `transformers`, or `gguf` | `transformers` |
| `LLM_DEVICE` | `auto`, `cpu`, or `cuda` | `auto` |
| `OLLAMA_BASE_URL` | Ollama server URL | `http://localhost:11434` |
| `SHOP_API_URL` | Laravel CMS API base URL | Required for recommendations |
| `SHOP_API_KEY` | CMS API authentication key | Optional |
| `CORS_ORIGINS` | Allowed origins (comma-separated) | `http://localhost:3000` |
| `CELERY_ENABLED` | Enable background task processing | `false` |
| `LLM_LOAD_IN_8BIT` | 8-bit quantization (Transformers) | `false` |
| `LLM_LOAD_IN_4BIT` | 4-bit quantization (Transformers) | `false` |

---

## Docker Deployment

```bash
# Build and start all services
docker-compose up -d

# View logs
docker-compose logs -f api

# Stop services
docker-compose down
```

**Docker Compose services:**

| Service | Image | Port | Description |
|---------|-------|------|-------------|
| `redis` | redis:7-alpine | 6379 | Data store + Celery broker |
| `nakh-cms` | webdevops/php-nginx:8.2 | 8000 | Laravel CMS |
| `api` | Custom (multi-stage) | 8002→8000 | FastAPI AI service |
| `celery-worker` | Same as api | — | Background task processor |
| `celery-beat` | Same as api | — | Scheduled task runner |

The Dockerfile uses a multi-stage build with a non-root `nakh` user, health checks, and separate builder/production stages for minimal image size.

---

## Project Structure

```
Nakh_AI/
├── app/
│   ├── main.py                    # FastAPI app, lifespan, middleware
│   ├── config.py                  # Pydantic Settings (env-driven)
│   ├── database.py                # Redis storage layer
│   ├── api/                       # API routers
│   │   ├── auth.py                #   Authentication
│   │   ├── users.py               #   User management
│   │   ├── uploads.py             #   Photo upload handling
│   │   ├── chat.py                #   Chat endpoints
│   │   ├── recommendations.py     #   Recommendation pipeline
│   │   └── health.py              #   Health check
│   ├── core/                      # Cross-cutting concerns
│   │   ├── security.py            #   Password hashing, tokens
│   │   ├── dependencies.py        #   FastAPI dependencies
│   │   └── middleware.py          #   Rate limiting, logging
│   ├── schemas/                   # Pydantic request/response models
│   └── services/                  # Business logic
│       ├── product_service.py     #   3-stage recommendation scoring
│       ├── chat_service.py        #   Chat session management
│       ├── context_builder.py     #   Prompt building + translations
│       └── llm/                   #   LLM abstraction layer
│           ├── base.py            #     BaseLLMProvider + LLMResponse
│           ├── manager.py         #     LLMManager singleton
│           ├── ollama_provider.py #     Ollama HTTP provider
│           ├── transformers_provider.py  # HuggingFace provider
│           └── gguf_provider.py   #     GGUF/llama.cpp provider
│
├── measure/                       # AI measurement modules
│   ├── body_measurement.py        #   Circumference + length extraction
│   ├── consensus_mesh.py          #   Multi-view SMPL beta fusion
│   ├── alpha_shape.py             #   Concave hull perimeter
│   ├── image_validator.py         #   Pre-PARE validation
│   ├── image_enhancement.py       #   Adaptive image preprocessing
│   ├── quality_score.py           #   Per-view quality [0,1]
│   ├── confidence.py              #   Per-measurement confidence
│   ├── sanity_validator.py        #   Anthropometric range checks
│   ├── calibration.py             #   Offset table application
│   ├── learned_correction.py      #   Linear correction model
│   ├── mediapipe_single.py        #   Fallback: 2D landmark measurement
│   ├── body_silhouette.py         #   2D silhouette visualization
│   ├── body_mannequin.py          #   Detailed mannequin rendering
│   ├── model_registry.py          #   PARE + SMPL model management
│   └── PARE/                      #   PARE model submodule
│       └── scripts/
│           ├── pare/core/         #     PARETester, config
│           ├── pare/models/       #     HRNet, ResNet backbones
│           └── data/              #     Checkpoints, SMPL weights
│
├── media/                         # Runtime data (uploads, results, chat)
├── logs/                          # Application logs
├── Dockerfile                     # Multi-stage production build
├── docker-compose.yml             # Full stack orchestration
├── requirements.txt               # Python dependencies
└── .env.example                   # Environment template
```

---

## Performance & Scalability

| Aspect | Approach |
|--------|----------|
| **GPU inference** | CUDA auto-detection + AMP mixed precision (float16 forward pass) |
| **Event loop safety** | All synchronous LLM calls wrapped in `asyncio.to_thread()` |
| **CMS resilience** | 3-second reachability pre-check; progressive filter relaxation; mock fallback |
| **Background tasks** | Celery workers for heavy image processing (configurable concurrency) |
| **Memory** | `torch.cuda.empty_cache()` after batches; model unloading on shutdown |
| **Rate limiting** | Per-IP request throttling (configurable per-minute limit) |
| **Timeouts** | Separate connect (5s) and read (30s) timeouts for CMS; 180s for LLM |
| **Scoring** | Pure Python attribute scoring avoids CMS database bottlenecks |
| **Caching** | Redis-backed token and session caching with TTL |

---

## Security & Reliability

| Measure | Implementation |
|---------|----------------|
| **Authentication** | Bearer token with configurable TTL (default: 7 days) |
| **Prompt injection** | `_safe()` escapes backticks, chat-template delimiters, control chars; field length caps |
| **Input sanitization** | Chat messages capped at 2000 chars; stripped of injection patterns |
| **Non-root container** | Docker runs as `nakh:nakh` user |
| **CORS** | Strict origin list in production; permissive only in debug mode |
| **Health checks** | Docker healthcheck on `/api/v1/health` (30s interval, 3 retries) |
| **Graceful degradation** | Mock products if CMS unreachable; fallback text if LLM unavailable; MediaPipe fallback if PARE fails |
| **Error isolation** | LLM errors return empty response (not exceptions); CMS timeouts don't cascade |

---

## Future Roadmap

- **Real-time try-on** — Virtual garment overlay on user body mesh
- **Fabric drape simulation** — Physics-based fabric behavior on body shape
- **Size prediction learning** — Feedback loop from purchase/return data
- **Multi-language expansion** — Arabic, Turkish support in chat and recommendations
- **Edge deployment** — ONNX/TensorRT export for mobile inference
- **A/B testing framework** — Compare recommendation strategies
- **Ground-truth calibration pipeline** — Automated offset tuning from tailor measurements

---

## License

Private — All rights reserved.
