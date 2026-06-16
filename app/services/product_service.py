"""
Product service for fetching and recommending products.

This service interfaces with the external PHP shop API
to fetch products and generate recommendations.

3-stage recommendation pipeline:
  Stage 1 — CMS query: category + subcategory + gender + price (safe, fast)
  Stage 2 — Python scoring: rank by attribute match (style, occasion, season, color, size)
  Stage 3 — LLM ranking: final pick + narrative (in recommendations.py)
"""
import logging
import re
from typing import Optional
import httpx

from app.config import settings
from app.schemas.chat import ProductRecommendation, UserPreferences

logger = logging.getLogger(__name__)

# ── Persian/Arabic text normalisation ──
# Different keyboards/CMS exports mix Arabic and Persian forms of the same
# letters (ي/ی, ك/ک), use various spaces (ZWNJ), and Arabic/Persian digits.
# Without normalising, "آبي" and "آبی" are treated as different tokens.
_CHAR_MAP = str.maketrans({
    "ي": "ی", "ك": "ک", "ﻙ": "ک", "ﻩ": "ه", "ة": "ه", "أ": "ا",
    "إ": "ا", "آ": "ا", "ؤ": "و", "ئ": "ی", "ٔ": "",
    "‌": " ",  # ZWNJ → space
    "ي": "ی", "ك": "ک",
    "۰": "0", "۱": "1", "۲": "2", "۳": "3", "۴": "4",
    "۵": "5", "۶": "6", "۷": "7", "۸": "8", "۹": "9",
})


def _normalize_fa(text: str) -> str:
    """Normalise Persian/Arabic text so equivalent forms compare equal."""
    return str(text).translate(_CHAR_MAP).strip().lower()


# ── Domain synonym groups ──
# Each set lists terms that should be treated as semantically equivalent for
# matching. This is the cheap, always-on complement to optional embeddings:
# it captures the most common fashion equivalences deterministically.
_SYNONYM_GROUPS: list[set[str]] = [
    # colours
    {"ابی", "اسمانی", "نیلی", "فیروزه ای"},
    {"سرمه ای", "ابی تیره", "نیوی", "navy"},
    {"مشکی", "سیاه", "زغالی", "black"},
    {"سفید", "شیری", "نقره ای", "white"},
    {"قرمز", "اناری", "بردو", "زرشکی", "red"},
    {"سبز", "زیتونی", "یشمی", "green"},
    {"قهوه ای", "خاکی", "کرم", "بژ", "brown", "beige"},
    {"خاکستری", "طوسی", "gray", "grey"},
    # occasions
    {"رسمی", "اداری", "کاری", "formal", "office"},
    {"مجلسی", "مهمانی", "عروسی", "شب", "party"},
    {"کژوال", "کجوال", "روزمره", "اسپرت", "casual", "راحتی"},
    {"ورزشی", "اسپرت", "sport"},
    # seasons
    {"تابستان", "تابستانه", "گرم", "summer"},
    {"زمستان", "زمستانه", "سرد", "winter"},
    {"بهار", "بهاره", "spring"},
    {"پاییز", "پاییزه", "autumn", "fall"},
    # materials
    {"پنبه", "نخی", "cotton"},
    {"پشم", "پشمی", "wool"},
    {"کتان", "لینن", "linen"},
    {"ابریشم", "حریر", "silk"},
    {"جین", "denim"},
]

# Build term → canonical-group-id lookup once.
_SYN_LOOKUP: dict[str, int] = {}
for _gid, _grp in enumerate(_SYNONYM_GROUPS):
    for _term in _grp:
        _SYN_LOOKUP[_normalize_fa(_term)] = _gid


def _expand_tokens(tokens: set[str]) -> set[str]:
    """Expand a token set with synonym-group ids so equivalent terms match."""
    expanded = set(tokens)
    for t in tokens:
        gid = _SYN_LOOKUP.get(t)
        if gid is not None:
            expanded.add(f"__syn{gid}")
    return expanded

# ── Stage 2: attribute key mapping ──
# Maps questionnaire answer keys → possible CMS variant attribute names (Persian + English).
_ATTR_KEY_MAP: dict[str, list[str]] = {
    "style":    ["استایل", "سبک", "style"],
    "occasion": ["مناسبت", "مناسبت ها", "مناسبت‌ها", "occasion"],
    "season":   ["فصل", "season"],
    "colors":   ["رنگ", "color"],
    "size":     ["سایز", "اندازه", "size"],
    "material": ["جنس", "جنس پارچه", "material"],
    "pattern":  ["طرح", "pattern"],
    "weave":    ["بافت", "weave"],
    "usage":    ["کاربرد", "usage"],
}

# Score weights per attribute (total = 1.0 when all match)
_ATTR_WEIGHTS: dict[str, float] = {
    "style":    0.25,
    "occasion": 0.20,
    "season":   0.15,
    "colors":   0.15,
    "size":     0.15,
    "material": 0.05,
    "pattern":  0.03,
    "weave":    0.01,
    "usage":    0.01,
}

# How many products to fetch from CMS (broad pool for scoring)
_CMS_FETCH_LIMIT = 40
# How many top-scored products to return for the LLM
_RETURN_LIMIT = 20


def _tokenise(text: str) -> set[str]:
    """Split a Persian/English string on commas (both ، and ,) and whitespace.

    Returns a set of normalised, non-empty tokens (Arabic/Persian forms unified).
    """
    # Replace Persian comma with standard comma, then split
    parts = re.split(r"[,،]", str(text))
    tokens: set[str] = set()
    for part in parts:
        t = _normalize_fa(part)
        if t and t != "-":
            tokens.add(t)
    return tokens


def _extract_product_attrs(product: dict) -> dict[str, set[str]]:
    """Extract all attribute values from product variants + specifications.

    Returns {questionnaire_key: {value1, value2, ...}}.
    """
    result: dict[str, set[str]] = {}

    # Keys to skip entirely (not useful for scoring)
    skip_keys = {"جنسیت", "gender", "فیت", "fit", "ویژگی ها", "ویژگی‌ها"}

    def _ingest(key: str, val: str) -> None:
        key_stripped = key.strip() if key else ""
        if key_stripped in skip_keys:
            return
        key_lower = key_stripped.lower()
        for qkey, persian_keys in _ATTR_KEY_MAP.items():
            if any(pk in key_lower for pk in persian_keys):
                result.setdefault(qkey, set()).update(_tokenise(val))
                return

    # From variant attributes
    for variant in product.get("variants") or []:
        for attr_key, attr_val in (variant.get("attributes") or {}).items():
            _ingest(attr_key, str(attr_val))

    # From top-level specifications
    for spec_key, spec_val in (product.get("specifications") or {}).items():
        _ingest(spec_key, str(spec_val))

    return result


def _normalise_answer(val) -> set[str]:
    """Convert an answer value (string, list, or None) to a token set."""
    if val is None:
        return set()
    if isinstance(val, list):
        combined: set[str] = set()
        for item in val:
            combined.update(_tokenise(str(item)))
        return combined
    return _tokenise(str(val))


def score_product_relevance(product: dict, answers: dict) -> float:
    """Score a product 0.0–1.0 based on how well it matches questionnaire answers.

    Used as Stage 2 of the recommendation pipeline: products fetched broadly
    from the CMS are scored and sorted so the LLM receives the most relevant
    ones first.
    """
    product_attrs = _extract_product_attrs(product)
    if not product_attrs and not answers:
        return 0.0

    total_weight = 0.0
    matched_weight = 0.0

    for qkey, weight in _ATTR_WEIGHTS.items():
        user_tokens = _normalise_answer(answers.get(qkey))
        if not user_tokens:
            continue  # user didn't express a preference — skip, don't penalise

        product_tokens = product_attrs.get(qkey, set())
        if not product_tokens:
            # Product has no data for this attribute — small penalty
            total_weight += weight
            continue

        total_weight += weight

        # Expand both sides with synonym-group markers so equivalent terms
        # (e.g. سرمه‌ای ≈ آبی تیره, رسمی ≈ اداری) count as matches.
        user_exp = _expand_tokens(user_tokens)
        prod_exp = _expand_tokens(product_tokens)

        # Check overlap: exact/synonym token match, OR substring containment.
        hit = bool(user_exp & prod_exp)
        if not hit:
            for ut in user_tokens:
                for pt in product_tokens:
                    if ut in pt or pt in ut:
                        hit = True
                        break
                if hit:
                    break

        if hit:
            matched_weight += weight

    return matched_weight / total_weight if total_weight > 0 else 0.0


def _product_text(product: dict) -> str:
    """Flatten a product into a short text blob for embedding."""
    parts: list[str] = []
    for key in ("title", "name_fa", "name", "category", "brand"):
        v = product.get(key)
        if v:
            parts.append(str(v))
    specs = product.get("specifications") or {}
    for k, v in specs.items():
        parts.append(f"{k} {v}")
    attrs = _extract_product_attrs(product)
    for vals in attrs.values():
        parts.extend(vals)
    return " ".join(parts)[:512]


def _query_text(answers: dict) -> str:
    """Build a natural-language preference blob from questionnaire answers."""
    parts: list[str] = []
    interesting = ("style", "occasion", "season", "colors", "material",
                   "pattern", "usage", "weave")
    for key in interesting:
        v = answers.get(key)
        if not v:
            continue
        if isinstance(v, list):
            parts.extend(str(x) for x in v if x)
        else:
            parts.append(str(v))
    # Per-type answers (multi-product mode)
    for pa in (answers.get("productAnswers") or {}).values():
        for key in interesting:
            v = pa.get(key)
            if isinstance(v, list):
                parts.extend(str(x) for x in v if x)
            elif v:
                parts.append(str(v))
    return " ".join(parts)[:512]


async def rerank_with_embeddings(
    answers: dict,
    scored_products: list[tuple[float, dict]],
    blend_weight: Optional[float] = None,
) -> list[dict]:
    """Blend token relevance with semantic similarity, return products sorted desc.

    ``scored_products`` is a list of (token_score, product). When embeddings are
    disabled/unreachable, this is a no-op that returns the products already
    ordered by token score. Otherwise:
        final = (1 - w) * token_score + w * cosine(query, product)
    """
    from app.services.embedding import embedding_service, cosine

    if not scored_products:
        return []

    if not embedding_service.enabled:
        return [p for _, p in scored_products]

    w = blend_weight if blend_weight is not None else getattr(
        settings, "embedding_blend_weight", 0.4
    )

    query = _query_text(answers)
    if not query:
        return [p for _, p in scored_products]

    products = [p for _, p in scored_products]
    texts = [query] + [_product_text(p) for p in products]
    vectors = await embedding_service.embed(texts)
    query_vec = vectors[0]
    if query_vec is None:
        # Embedder failed — keep token ordering.
        return products

    blended: list[tuple[float, dict]] = []
    for (token_score, product), pvec in zip(scored_products, vectors[1:]):
        sem = cosine(query_vec, pvec)
        final = (1.0 - w) * token_score + w * sem
        blended.append((final, product))
    blended.sort(key=lambda x: x[0], reverse=True)
    logger.info(
        "Semantic rerank: %d products, blend_w=%.2f, top=%.2f",
        len(blended), w, blended[0][0] if blended else 0.0,
    )
    return [p for _, p in blended]


class ProductService:
    """
    Service for product operations.

    Handles:
    - Fetching products from external PHP API or Meilisearch
    - Scoring and ranking by attribute match
    - Generating product recommendations
    """

    def __init__(self):
        self.api_base_url = getattr(settings, "shop_api_url", "") or getattr(settings, "SHOP_API_URL", "")
        self.api_key = getattr(settings, "shop_api_key", "") or getattr(settings, "SHOP_API_KEY", "")
        self._client: Optional[httpx.AsyncClient] = None
        # Meilisearch config
        self._meili_url = getattr(settings, "meilisearch_url", "") or ""
        self._meili_key = getattr(settings, "meilisearch_key", "") or ""
        self._meili_client: Optional[httpx.AsyncClient] = None

    @staticmethod
    def _extract_products(data) -> list[dict]:
        """Extract the product list from the CMS API response.

        The CMS wraps responses as: {"success": true, "result": {"data": [...]}}
        This method handles that structure and common variations.
        """
        if isinstance(data, list):
            return data
        if not isinstance(data, dict):
            return []
        # CMS standard: {"success": ..., "result": {"data": [...]}}
        result = data.get("result")
        if isinstance(result, dict):
            inner = result.get("data")
            if isinstance(inner, list):
                return inner
        # Flat: {"data": [...]}
        inner = data.get("data")
        if isinstance(inner, list):
            return inner
        return []

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None:
            headers = {}
            if self.api_key:
                headers["x-api-key"] = self.api_key
            self._client = httpx.AsyncClient(
                base_url=self.api_base_url or "",
                headers=headers,
                timeout=httpx.Timeout(
                    connect=5.0,   # fail fast if CMS is unreachable
                    read=30.0,
                    write=10.0,
                    pool=10.0,
                ),
            )
        return self._client

    async def check_cms_reachable(self) -> bool:
        """Quick connectivity check — returns False if CMS is down."""
        if not self.api_base_url:
            return False
        try:
            client = await self._get_client()
            resp = await client.get("/api/v1/health", timeout=3.0)
            return resp.status_code < 500
        except Exception:
            try:
                client = await self._get_client()
                resp = await client.get("/", timeout=3.0)
                return True
            except Exception:
                return False

    async def _get_meili_client(self) -> httpx.AsyncClient:
        """Get or create Meilisearch HTTP client."""
        if self._meili_client is None:
            headers = {"Content-Type": "application/json"}
            if self._meili_key:
                headers["Authorization"] = f"Bearer {self._meili_key}"
            self._meili_client = httpx.AsyncClient(
                base_url=self._meili_url,
                headers=headers,
                timeout=httpx.Timeout(connect=3.0, read=10.0, write=5.0, pool=5.0),
            )
        return self._meili_client

    @property
    def meilisearch_enabled(self) -> bool:
        """Whether Meilisearch is configured."""
        return bool(self._meili_url)

    def _fallback(self) -> tuple[list[dict], str]:
        """Return the catalogue-unavailable fallback.

        In production (``allow_mock_products`` False) we MUST NOT show fabricated
        products at made-up prices to a real shopper — we return an empty list
        with source 'unavailable' so the caller can render a clear
        "catalogue temporarily unavailable" state. Mock data is dev/test only.
        """
        if getattr(settings, "allow_mock_products", False):
            return self._get_mock_products(), "mock"
        logger.error(
            "Product catalogue unavailable and mock products are disabled "
            "(allow_mock_products=False) — returning empty result."
        )
        return [], "unavailable"

    async def search_meilisearch(
        self,
        answers: dict,
        gender: str = "",
        limit: int = 40,
    ) -> list[dict] | None:
        """Search products via Meilisearch with attribute filters.

        Returns a list of product dicts, or None if Meilisearch is not
        configured or the query fails (caller should fall back to CMS).
        """
        if not self._meili_url:
            return None

        filters: list[str] = []

        category = answers.get("category", "").lower()
        if category in ("garment", "پوشاک"):
            filters.append('category = "garment"')
        elif category in ("fabric", "پارچه"):
            filters.append('category = "fabric"')

        subcategory = (
            answers.get("garmentType")
            or answers.get("fabricType")
            or answers.get("type")
            or ""
        )
        if subcategory:
            filters.append(f'subcategory = "{subcategory}"')

        if gender:
            filters.append(f'gender = "{gender}"')

        # Attribute filters — safe in Meilisearch (unlike CMS)
        attr_filter_map = {
            "occasion": "attributes.occasion",
            "season":   "attributes.season",
            "colors":   "attributes.color",
            "style":    "attributes.style",
            "material": "attributes.material",
        }
        for answer_key, meili_field in attr_filter_map.items():
            val = answers.get(answer_key)
            if val:
                if isinstance(val, list):
                    val = val[0]  # use first value for filter
                filters.append(f'{meili_field} = "{val}"')

        # Price range
        if answers.get("minPrice"):
            filters.append(f'price >= {answers["minPrice"]}')
        if answers.get("maxPrice"):
            filters.append(f'price <= {answers["maxPrice"]}')

        try:
            client = await self._get_meili_client()
            payload = {"limit": limit}
            if filters:
                payload["filter"] = " AND ".join(filters)

            logger.info("Meilisearch query: %s", payload)
            resp = await client.post("/indexes/products/search", json=payload)
            resp.raise_for_status()
            hits = resp.json().get("hits", [])
            logger.info("Meilisearch returned %d hits", len(hits))
            return hits
        except Exception as e:
            logger.warning("Meilisearch query failed (%s: %s), falling back to CMS", type(e).__name__, e)
            return None

    async def close(self):
        """Close HTTP clients."""
        if self._client:
            await self._client.aclose()
            self._client = None
        if self._meili_client:
            await self._meili_client.aclose()
            self._meili_client = None

    async def fetch_products(
        self,
        category: Optional[str] = None,
        search_query: Optional[str] = None,
        min_price: Optional[float] = None,
        max_price: Optional[float] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[dict]:
        """Fetch products from the PHP shop API."""
        if not self.api_base_url:
            logger.warning("SHOP_API_URL not configured")
            return self._get_mock_products() if getattr(settings, "allow_mock_products", False) else []

        try:
            client = await self._get_client()

            params = {
                "limit": limit,
                "offset": offset,
            }
            if category:
                params["category"] = category
            if search_query:
                params["q"] = search_query
            if min_price is not None:
                params["min_price"] = min_price
            if max_price is not None:
                params["max_price"] = max_price

            response = await client.get("/api/products", params=params)
            response.raise_for_status()

            data = response.json()
            return self._extract_products(data) or (data if isinstance(data, list) else [])

        except httpx.HTTPError as e:
            logger.error(f"Error fetching products: {e}")
            return []
        except Exception as e:
            logger.error(f"Unexpected error fetching products: {e}")
            return []

    async def fetch_products_for_recommendation(self, answers: dict) -> list[dict]:
        """Backwards-compatible wrapper that drops the source metadata."""
        products, _ = await self.fetch_products_for_recommendation_with_source(answers)
        return products

    async def fetch_products_for_recommendation_with_source(
        self,
        answers: dict,
        gender: str = "",
        calculated_size: str = "",
    ) -> tuple[list[dict], str]:
        """
        Fetch products for recommendation (Stage 1 + Stage 2).

        Stage 1 — CMS query with safe, fast filters only:
          category, subcategory, gender, price range.
          (occasion/season/color/size filters are known to hang the CMS)

        Stage 2 — Python-side scoring:
          Score each product by attribute match (style, occasion, season,
          color, size, material, pattern) against the questionnaire answers.
          Sort by score descending so the LLM (Stage 3) sees the most
          relevant products first.

        Returns (products, source) where source is "shop" or "mock".
        """
        if not self.api_base_url and not self.meilisearch_enabled:
            logger.warning("Neither SHOP_API_URL nor MEILISEARCH_URL configured")
            return self._fallback()

        try:
            # ── Stage 1a: Try Meilisearch first (if configured) ──
            if self.meilisearch_enabled:
                meili_results = await self.search_meilisearch(answers, gender, limit=_CMS_FETCH_LIMIT)
                if meili_results:
                    # Meilisearch already filters by attributes — still run Python scoring
                    scored = [(score_product_relevance(p, answers), p) for p in meili_results]
                    scored.sort(key=lambda x: x[0], reverse=True)
                    if scored:
                        logger.info(
                            "Meilisearch+scoring: %d products, top=%.2f avg=%.2f",
                            len(scored), scored[0][0],
                            sum(s for s, _ in scored) / len(scored),
                        )
                    # Stage 2.5 — optional semantic rerank (no-op if disabled)
                    sorted_products = await rerank_with_embeddings(answers, scored)
                    return sorted_products[:_RETURN_LIMIT], "shop"
                # Meilisearch returned empty or failed — fall through to CMS
                logger.info("Meilisearch returned no results, falling back to CMS")

            if not self.api_base_url:
                logger.warning("SHOP_API_URL not configured")
                return self._fallback()

            client = await self._get_client()

            # ── Stage 1b: CMS query with structural filters only ──
            params: dict = {"limit": _CMS_FETCH_LIMIT}

            # Map category
            category = answers.get("category", "").lower()
            if category in ("garment", "پوشاک"):
                params["category"] = "garment"
            elif category in ("fabric", "پارچه"):
                params["category"] = "fabric"

            # Subcategory (product type slug)
            subcategory = (
                answers.get("garmentType")
                or answers.get("fabricType")
                or answers.get("type")
                or ""
            )
            if subcategory:
                params["subcategory"] = subcategory

            # Gender
            if gender:
                params["gender"] = gender

            # Price range (simple numeric — safe for CMS)
            if answers.get("minPrice"):
                params["min_price"] = answers["minPrice"]
            if answers.get("maxPrice"):
                params["max_price"] = answers["maxPrice"]

            logger.info("Stage 1 — CMS query params: %s", params)

            req_timeout = 15.0
            response = await client.get(
                "/api/v1/products/for-recommendation", params=params,
                timeout=req_timeout,
            )
            response.raise_for_status()

            data = response.json()
            products = self._extract_products(data)

            # Relaxation: if empty, drop filters progressively
            if not products:
                relaxable = ["min_price", "max_price", "subcategory"]
                while not products and any(k in params for k in relaxable):
                    for key in relaxable:
                        if key in params:
                            logger.info("No products, retrying without %s=%s", key, params[key])
                            params.pop(key)
                            break
                    try:
                        response = await client.get(
                            "/api/v1/products/for-recommendation", params=params,
                            timeout=req_timeout,
                        )
                        response.raise_for_status()
                        data = response.json()
                        products = self._extract_products(data)
                    except (httpx.TimeoutException, httpx.ConnectError):
                        logger.warning("CMS timeout during relaxation, stopping")
                        break

            if not products:
                logger.warning("CMS returned empty after relaxation")
                return self._fallback()

            # ── Stage 2: Python-side attribute scoring ──
            scored = []
            for p in products:
                score = score_product_relevance(p, answers)
                scored.append((score, p))

            # Sort by score descending — best matches first
            scored.sort(key=lambda x: x[0], reverse=True)

            # Log scoring summary
            if scored:
                top_score = scored[0][0]
                avg_score = sum(s for s, _ in scored) / len(scored)
                logger.info(
                    "Stage 2 — scored %d products: top=%.2f avg=%.2f (returning top %d)",
                    len(scored), top_score, avg_score, min(len(scored), _RETURN_LIMIT),
                )

            # Stage 2.5 — optional semantic rerank (no-op if disabled)
            sorted_products = await rerank_with_embeddings(answers, scored)
            return sorted_products[:_RETURN_LIMIT], "shop"

        except (httpx.TimeoutException, httpx.ConnectError) as e:
            logger.error(
                "CMS %s (%s) for %s/api/v1/products/for-recommendation — params=%s",
                "TIMEOUT" if isinstance(e, httpx.TimeoutException) else "CONNECT ERROR",
                type(e).__name__, self.api_base_url,
                params if 'params' in locals() else '?',
            )
            if isinstance(e, httpx.ConnectError):
                logger.error("Is the CMS running at %s?", self.api_base_url)
            return self._fallback()
        except httpx.HTTPError as e:
            logger.error(
                "CMS HTTP error [%s]: %s (url=%s)",
                type(e).__name__, e, self.api_base_url,
            )
            return self._fallback()
        except Exception as e:
            logger.error("Unexpected error fetching recommendation products [%s]: %s", type(e).__name__, e)
            return self._fallback()

    async def get_product_by_id(self, product_id: str) -> Optional[dict]:
        """Get a single product by ID."""
        if not self.api_base_url:
            logger.warning("SHOP_API_URL not configured")
            return None

        try:
            client = await self._get_client()
            response = await client.get(f"/api/products/{product_id}")
            response.raise_for_status()
            return response.json()

        except httpx.HTTPError as e:
            logger.error(f"Error fetching product {product_id}: {e}")
            return None

    @staticmethod
    def _preferences_to_answers(preferences: Optional[UserPreferences]) -> dict:
        """Adapt chat `UserPreferences` into the questionnaire `answers` shape.

        This lets the chat recommendation path reuse the SAME relevance scorer
        (`score_product_relevance`) as the questionnaire path, instead of a
        second, divergent heuristic.
        """
        answers: dict = {}
        if not preferences:
            return answers
        if getattr(preferences, "preferred_colors", None):
            answers["colors"] = list(preferences.preferred_colors)
        if getattr(preferences, "preferred_fabrics", None):
            answers["material"] = list(preferences.preferred_fabrics)
        if getattr(preferences, "preferred_styles", None):
            answers["style"] = list(preferences.preferred_styles)
        if getattr(preferences, "budget_range", None):
            answers["minPrice"] = preferences.budget_range[0]
            answers["maxPrice"] = preferences.budget_range[1]
        return answers

    async def get_recommendations(
        self,
        measurements: Optional[dict] = None,
        preferences: Optional[UserPreferences] = None,
        conversation_context: Optional[str] = None,
        limit: int = 5,
    ) -> list[ProductRecommendation]:
        """Get product recommendations based on user context (chat path).

        Unified with the questionnaire path: products are fetched then ranked
        with the shared `score_product_relevance` scorer (synonym-aware) and,
        when enabled, the same semantic rerank.
        """
        answers = self._preferences_to_answers(preferences)

        filter_params = {}
        if preferences and preferences.budget_range:
            filter_params["min_price"] = preferences.budget_range[0]
            filter_params["max_price"] = preferences.budget_range[1]

        products = await self.fetch_products(limit=50, **filter_params)
        if not products:
            return []

        scored = [(score_product_relevance(p, answers), p) for p in products]
        scored.sort(key=lambda x: x[0], reverse=True)
        ranked = await rerank_with_embeddings(answers, scored)

        # Recover a score per product for the response (semantic rerank reorders
        # but we keep the token score as the displayed match strength).
        score_by_id = {id(p): s for s, p in scored}

        recommendations = []
        for product in ranked[:limit]:
            score = score_by_id.get(id(product), 0.0)
            recommendations.append(ProductRecommendation(
                product_id=str(product.get("id", "")),
                name=product.get("name", "") or product.get("title", ""),
                name_fa=product.get("name_fa") or product.get("title"),
                description=product.get("description"),
                price=float(product.get("price", 0) or 0),
                category=product.get("category", ""),
                image_url=product.get("image_url") or product.get("image"),
                match_score=round(float(score), 3),
                match_reasons=self._match_reasons(product, answers),
            ))

        return recommendations

    @staticmethod
    def _match_reasons(product: dict, answers: dict) -> list[str]:
        """Human-readable Persian reasons for why a product matched (chat UI)."""
        reasons: list[str] = []
        attrs = _extract_product_attrs(product)
        labels = {
            "colors": "رنگ", "material": "جنس", "style": "سبک",
            "occasion": "مناسبت", "season": "فصل",
        }
        for key, label in labels.items():
            user_tokens = _expand_tokens(_normalise_answer(answers.get(key)))
            if not user_tokens:
                continue
            prod_tokens = _expand_tokens(attrs.get(key, set()))
            if user_tokens & prod_tokens:
                vals = "، ".join(sorted(attrs.get(key, set()))[:2])
                reasons.append(f"{label} مناسب: {vals}" if vals else f"{label} مناسب")
        return reasons

    def _get_mock_products(self) -> list[dict]:
        """Return mock products for development/testing."""
        return [
            {
                "id": "1",
                "title": "پیراهن کلاسیک پنبه‌ای",
                "title_en": "Classic Cotton Shirt",
                "slug": "classic-cotton-shirt",
                "brand": "نخ‌نما",
                "price": 450000,
                "regular_price": 500000,
                "category": "پیراهن",
                "is_available": True,
                "image": None,
                "product_url": None,
                "variants": [
                    {"price": 450000, "discount": 10, "attributes": {"اندازه": "S"}, "in_stock": True},
                    {"price": 450000, "discount": 10, "attributes": {"اندازه": "M"}, "in_stock": True},
                    {"price": 450000, "discount": 10, "attributes": {"اندازه": "L"}, "in_stock": True},
                    {"price": 460000, "discount": 8, "attributes": {"اندازه": "XL"}, "in_stock": True},
                ],
                "specifications": {"جنس پارچه": "نخ پنبه", "یقه": "کلاسیک"},
            },
            {
                "id": "2",
                "title": "شلوار رسمی پشمی",
                "title_en": "Formal Wool Pants",
                "slug": "formal-wool-pants",
                "brand": "ایران‌دوخت",
                "price": 680000,
                "regular_price": 680000,
                "category": "شلوار",
                "is_available": True,
                "image": None,
                "product_url": None,
                "variants": [
                    {"price": 680000, "discount": 0, "attributes": {"اندازه": "M"}, "in_stock": True},
                    {"price": 680000, "discount": 0, "attributes": {"اندازه": "L"}, "in_stock": True},
                    {"price": 680000, "discount": 0, "attributes": {"اندازه": "XL"}, "in_stock": False},
                ],
                "specifications": {"جنس پارچه": "پشم", "فیت": "رسمی"},
            },
            {
                "id": "3",
                "title": "کت کژوال کتانی",
                "title_en": "Casual Linen Jacket",
                "slug": "casual-linen-jacket",
                "brand": "نخ‌نما",
                "price": 890000,
                "regular_price": 990000,
                "category": "کت",
                "is_available": True,
                "image": None,
                "product_url": None,
                "variants": [
                    {"price": 890000, "discount": 10, "attributes": {"اندازه": "M"}, "in_stock": True},
                    {"price": 890000, "discount": 10, "attributes": {"اندازه": "L"}, "in_stock": True},
                    {"price": 890000, "discount": 10, "attributes": {"اندازه": "XL"}, "in_stock": True},
                    {"price": 890000, "discount": 10, "attributes": {"اندازه": "XXL"}, "in_stock": True},
                ],
                "specifications": {"جنس پارچه": "کتان", "سبک": "کژوال"},
            },
            {
                "id": "4",
                "title": "کراوات ابریشمی",
                "title_en": "Silk Tie",
                "slug": "silk-tie",
                "brand": "رِیواس",
                "price": 320000,
                "regular_price": 320000,
                "category": "اکسسوری",
                "is_available": True,
                "image": None,
                "product_url": None,
                "variants": [],
                "specifications": {"جنس پارچه": "ابریشم"},
            },
            {
                "id": "5",
                "title": "شلوار جین",
                "title_en": "Denim Jeans",
                "slug": "denim-jeans",
                "brand": "ایران‌دوخت",
                "price": 520000,
                "regular_price": 520000,
                "category": "شلوار",
                "is_available": False,
                "image": None,
                "product_url": None,
                "variants": [
                    {"price": 520000, "discount": 0, "attributes": {"اندازه": "M"}, "in_stock": False},
                    {"price": 520000, "discount": 0, "attributes": {"اندازه": "L"}, "in_stock": False},
                ],
                "specifications": {"جنس پارچه": "جین"},
            },
        ]


# Global instance
product_service = ProductService()
