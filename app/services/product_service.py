"""
Product service for fetching and recommending products.

This service interfaces with the external PHP shop API
to fetch products and generate recommendations.
"""
import logging
from typing import Optional
import httpx

from app.config import settings
from app.schemas.chat import ProductRecommendation, UserPreferences

logger = logging.getLogger(__name__)


class ProductService:
    """
    Service for product operations.

    Handles:
    - Fetching products from external PHP API
    - Filtering products based on criteria
    - Generating product recommendations
    """

    def __init__(self):
        self.api_base_url = getattr(settings, "shop_api_url", "") or getattr(settings, "SHOP_API_URL", "")
        self.api_key = getattr(settings, "shop_api_key", "") or getattr(settings, "SHOP_API_KEY", "")
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None:
            headers = {}
            if self.api_key:
                headers["x-api-key"] = self.api_key
            self._client = httpx.AsyncClient(
                base_url=self.api_base_url or "",
                headers=headers,
                timeout=30.0
            )
        return self._client

    async def close(self):
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def fetch_products(
        self,
        category: Optional[str] = None,
        search_query: Optional[str] = None,
        min_price: Optional[float] = None,
        max_price: Optional[float] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[dict]:
        """
        Fetch products from the PHP shop API.

        Args:
            category: Filter by category
            search_query: Search in product names/descriptions
            min_price: Minimum price filter
            max_price: Maximum price filter
            limit: Number of products to fetch
            offset: Pagination offset

        Returns:
            List of product dictionaries
        """
        if not self.api_base_url:
            logger.warning("SHOP_API_URL not configured, returning mock data")
            return self._get_mock_products()

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
            return data.get("products", data) if isinstance(data, dict) else data

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
        Fetch products filtered by questionnaire answers from the Laravel API.

        Returns (products, source) where source is one of:
          - "shop"    – real catalog response from the CMS
          - "mock"    – mock fallback (CMS unreachable / unconfigured / empty)
        """
        if not self.api_base_url:
            logger.warning("SHOP_API_URL not configured, returning mock data")
            return self._get_mock_products(), "mock"

        try:
            client = await self._get_client()

            params: dict = {"limit": 20}

            # Map category answer
            category = answers.get("category", "").lower()
            if category in ("garment", "پوشاک"):
                params["category"] = "garment"
            elif category in ("fabric", "پارچه"):
                params["category"] = "fabric"

            # Map type answer to search
            search = (
                answers.get("garmentType")
                or answers.get("fabricType")
                or answers.get("type")
                or ""
            )
            if search:
                params["search"] = search

            # Gender filter
            if gender:
                params["gender"] = gender

            # Garment type filter from questionnaire
            garment_type = answers.get("garmentType") or ""
            if garment_type:
                params["garment_type"] = garment_type

            # Size filter — try with size first, fall back without if empty
            if calculated_size:
                params["size"] = calculated_size

            # Style / Occasion / Season filters
            for key in ("style", "occasion", "season"):
                val = answers.get(key, "")
                if val:
                    # If it's a list (checkbox), send first value for filter
                    if isinstance(val, list):
                        params[key] = val[0] if val else ""
                    else:
                        params[key] = val

            # Price filters
            if answers.get("minPrice"):
                params["min_price"] = answers["minPrice"]
            if answers.get("maxPrice"):
                params["max_price"] = answers["maxPrice"]

            response = await client.get(
                "/api/v1/products/for-recommendation", params=params
            )
            response.raise_for_status()

            data = response.json()
            products = data.get("data", data) if isinstance(data, dict) else data
            if isinstance(products, list) and products:
                return products, "shop"

            # Smart fallback: progressively relax filters until products are found
            relaxable = ["size", "style", "occasion", "season"]
            while not (isinstance(products, list) and products) and any(k in params for k in relaxable):
                # Remove the most specific filter first
                for key in relaxable:
                    if key in params:
                        logger.info("No products found, retrying without %s=%s", key, params[key])
                        params.pop(key)
                        break
                response = await client.get(
                    "/api/v1/products/for-recommendation", params=params
                )
                response.raise_for_status()
                data = response.json()
                products = data.get("data", data) if isinstance(data, dict) else data
                if isinstance(products, list) and products:
                    return products, "shop"

            logger.warning("Laravel returned empty products, falling back to mocks")
            return self._get_mock_products(), "mock"

        except httpx.HTTPError as e:
            logger.error("Error fetching recommendation products: %s", e)
            return self._get_mock_products(), "mock"
        except Exception as e:
            logger.error("Unexpected error fetching recommendation products: %s", e)
            return self._get_mock_products(), "mock"

    async def get_product_by_id(self, product_id: str) -> Optional[dict]:
        """
        Get a single product by ID.

        Args:
            product_id: The product ID

        Returns:
            Product dictionary or None
        """
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

    async def get_recommendations(
        self,
        measurements: Optional[dict] = None,
        preferences: Optional[UserPreferences] = None,
        conversation_context: Optional[str] = None,
        limit: int = 5,
    ) -> list[ProductRecommendation]:
        """
        Get product recommendations based on user context.

        Args:
            measurements: User's body measurements
            preferences: User's preferences
            conversation_context: Context from the conversation
            limit: Maximum recommendations to return

        Returns:
            List of ProductRecommendation objects
        """
        # Fetch products (filtered by preferences if available)
        filter_params = {}

        if preferences:
            if preferences.budget_range:
                filter_params["min_price"] = preferences.budget_range[0]
                filter_params["max_price"] = preferences.budget_range[1]

        products = await self.fetch_products(limit=50, **filter_params)

        if not products:
            return []

        # Score and rank products
        scored_products = []
        for product in products:
            score, reasons = self._calculate_match_score(
                product, measurements, preferences
            )
            scored_products.append((product, score, reasons))

        # Sort by score descending
        scored_products.sort(key=lambda x: x[1], reverse=True)

        # Convert to recommendations
        recommendations = []
        for product, score, reasons in scored_products[:limit]:
            recommendations.append(ProductRecommendation(
                product_id=str(product.get("id", "")),
                name=product.get("name", ""),
                name_fa=product.get("name_fa"),
                description=product.get("description"),
                price=float(product.get("price", 0)),
                category=product.get("category", ""),
                image_url=product.get("image_url"),
                match_score=score,
                match_reasons=reasons,
            ))

        return recommendations

    def _calculate_match_score(
        self,
        product: dict,
        measurements: Optional[dict],
        preferences: Optional[UserPreferences],
    ) -> tuple[float, list[str]]:
        """
        Calculate how well a product matches user criteria.

        Returns:
            Tuple of (score 0-1, list of match reasons)
        """
        score = 0.5  # Base score
        reasons = []

        if not preferences:
            return score, reasons

        # Color matching
        product_colors = product.get("colors", [])
        if preferences.preferred_colors and product_colors:
            matching_colors = set(preferences.preferred_colors) & set(product_colors)
            if matching_colors:
                score += 0.15
                reasons.append(f"رنگ مورد علاقه: {', '.join(matching_colors)}")

        # Fabric matching
        product_fabric = product.get("fabric", "").lower()
        if preferences.preferred_fabrics and product_fabric:
            if any(f.lower() in product_fabric for f in preferences.preferred_fabrics):
                score += 0.15
                reasons.append(f"پارچه مورد علاقه: {product_fabric}")

        # Style matching
        product_style = product.get("style", "").lower()
        if preferences.preferred_styles and product_style:
            if any(s.lower() in product_style for s in preferences.preferred_styles):
                score += 0.1
                reasons.append(f"سبک مورد علاقه: {product_style}")

        # Budget matching
        product_price = float(product.get("price", 0))
        if preferences.budget_range:
            min_budget, max_budget = preferences.budget_range
            if min_budget <= product_price <= max_budget:
                score += 0.1
                reasons.append("در محدوده بودجه")

        # Size matching based on measurements
        if measurements:
            # This would need product size data to work properly
            # For now, we'll add a placeholder
            pass

        # Normalize score to 0-1
        score = min(1.0, max(0.0, score))

        return score, reasons

    def _get_mock_products(self) -> list[dict]:
        """
        Return mock products for development/testing.
        Remove this when the real API is connected.
        """
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
