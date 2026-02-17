"""
Context builder for the chat system.

Builds rich context prompts including:
- User body measurements
- User preferences
- Product information
- Chat history
"""
import logging
from typing import Optional
from datetime import datetime

from app.schemas.chat import UserPreferences, ChatMessage, MessageRole

logger = logging.getLogger(__name__)


# Persian translations for measurements
MEASUREMENT_TRANSLATIONS = {
    "height": "قد",
    "weight": "وزن",
    "chest": "دور سینه",
    "waist": "دور کمر",
    "hips": "دور باسن",
    "shoulder_width": "عرض شانه",
    "arm_length": "طول دست",
    "inseam": "طول فاق",
    "neck": "دور گردن",
    "thigh": "دور ران",
    "calf": "دور ساق پا",
    "upper_arm": "دور بازو",
    "wrist": "دور مچ دست",
    "torso_length": "طول تنه",
    "back_width": "عرض پشت",
    "bmi": "شاخص توده بدنی",
}

# Persian translations for clothing styles
STYLE_TRANSLATIONS = {
    "casual": "کژوال",
    "formal": "رسمی",
    "sport": "ورزشی",
    "classic": "کلاسیک",
    "modern": "مدرن",
    "traditional": "سنتی",
}

# Persian translations for fabrics
FABRIC_TRANSLATIONS = {
    "cotton": "پنبه",
    "wool": "پشم",
    "silk": "ابریشم",
    "linen": "کتان",
    "polyester": "پلی‌استر",
    "denim": "جین",
    "leather": "چرم",
    "velvet": "مخمل",
}


class ContextBuilder:
    """
    Builds context-rich prompts for the chatbot.
    """

    def __init__(self, language: str = "fa"):
        """
        Initialize the context builder.

        Args:
            language: Language code ("fa" for Farsi, "en" for English)
        """
        self.language = language

    def build_system_prompt(
        self,
        measurements: Optional[dict] = None,
        preferences: Optional[UserPreferences] = None,
        include_product_context: bool = True,
    ) -> str:
        """
        Build the system prompt with user context.

        Args:
            measurements: User's body measurements
            preferences: User's clothing preferences
            include_product_context: Whether to include product recommendation capability

        Returns:
            System prompt string
        """
        if self.language == "fa":
            return self._build_persian_system_prompt(
                measurements, preferences, include_product_context
            )
        else:
            return self._build_english_system_prompt(
                measurements, preferences, include_product_context
            )

    def _build_persian_system_prompt(
        self,
        measurements: Optional[dict],
        preferences: Optional[UserPreferences],
        include_product_context: bool,
    ) -> str:
        """Build Persian system prompt."""
        parts = [
            "شما یک دستیار هوشمند خیاطی هستید که به کاربران در انتخاب لباس و پارچه مناسب کمک می‌کنید.",
            "شما می‌توانید بر اساس اندازه‌های بدن، سلیقه و نیاز کاربر، بهترین پیشنهادات را ارائه دهید.",
            "",
        ]

        # Add measurements context
        if measurements:
            parts.append("اندازه‌های بدن کاربر:")
            for key, value in measurements.items():
                if value is not None:
                    persian_name = MEASUREMENT_TRANSLATIONS.get(key, key)
                    if key in ["height", "arm_length", "inseam", "torso_length"]:
                        parts.append(f"  - {persian_name}: {value} سانتی‌متر")
                    elif key == "weight":
                        parts.append(f"  - {persian_name}: {value} کیلوگرم")
                    elif key == "bmi":
                        parts.append(f"  - {persian_name}: {value:.1f}")
                    else:
                        parts.append(f"  - {persian_name}: {value} سانتی‌متر")
            parts.append("")

        # Add preferences context
        if preferences:
            parts.append("ترجیحات کاربر:")
            if preferences.preferred_colors:
                parts.append(f"  - رنگ‌های مورد علاقه: {', '.join(preferences.preferred_colors)}")
            if preferences.preferred_fabrics:
                fabrics = [FABRIC_TRANSLATIONS.get(f, f) for f in preferences.preferred_fabrics]
                parts.append(f"  - پارچه‌های مورد علاقه: {', '.join(fabrics)}")
            if preferences.preferred_styles:
                styles = [STYLE_TRANSLATIONS.get(s, s) for s in preferences.preferred_styles]
                parts.append(f"  - سبک‌های مورد علاقه: {', '.join(styles)}")
            if preferences.size_preference:
                parts.append(f"  - سایز ترجیحی: {preferences.size_preference}")
            if preferences.budget_range:
                parts.append(f"  - محدوده بودجه: {preferences.budget_range[0]:,.0f} تا {preferences.budget_range[1]:,.0f} تومان")
            parts.append("")

        # Add product recommendation capability
        if include_product_context:
            parts.extend([
                "قابلیت‌های شما:",
                "  - پاسخ به سوالات درباره اندازه‌گیری بدن و سایزبندی",
                "  - پیشنهاد نوع لباس مناسب بر اساس اندام کاربر",
                "  - راهنمایی در انتخاب پارچه و رنگ",
                "  - پیشنهاد محصولات از فروشگاه",
                "",
            ])

        parts.extend([
            "نکات مهم:",
            "  - همیشه مودبانه و حرفه‌ای پاسخ دهید",
            "  - پاسخ‌ها باید مختصر و مفید باشند",
            "  - اگر اطلاعات کافی ندارید، از کاربر سوال کنید",
            "  - از اصطلاحات تخصصی خیاطی به زبان ساده استفاده کنید",
        ])

        return "\n".join(parts)

    def _build_english_system_prompt(
        self,
        measurements: Optional[dict],
        preferences: Optional[UserPreferences],
        include_product_context: bool,
    ) -> str:
        """Build English system prompt."""
        parts = [
            "You are an intelligent tailoring assistant helping users choose appropriate clothing and fabric.",
            "You can provide recommendations based on body measurements, preferences, and needs.",
            "",
        ]

        if measurements:
            parts.append("User's body measurements:")
            for key, value in measurements.items():
                if value is not None:
                    if key in ["height", "arm_length", "inseam", "torso_length"]:
                        parts.append(f"  - {key.replace('_', ' ').title()}: {value} cm")
                    elif key == "weight":
                        parts.append(f"  - Weight: {value} kg")
                    elif key == "bmi":
                        parts.append(f"  - BMI: {value:.1f}")
                    else:
                        parts.append(f"  - {key.replace('_', ' ').title()}: {value} cm")
            parts.append("")

        if preferences:
            parts.append("User preferences:")
            if preferences.preferred_colors:
                parts.append(f"  - Favorite colors: {', '.join(preferences.preferred_colors)}")
            if preferences.preferred_fabrics:
                parts.append(f"  - Favorite fabrics: {', '.join(preferences.preferred_fabrics)}")
            if preferences.preferred_styles:
                parts.append(f"  - Favorite styles: {', '.join(preferences.preferred_styles)}")
            if preferences.size_preference:
                parts.append(f"  - Size preference: {preferences.size_preference}")
            parts.append("")

        if include_product_context:
            parts.extend([
                "Your capabilities:",
                "  - Answer questions about body measurements and sizing",
                "  - Suggest suitable clothing types based on body shape",
                "  - Guide in selecting fabric and color",
                "  - Recommend products from the shop",
                "",
            ])

        parts.extend([
            "Important notes:",
            "  - Always respond politely and professionally",
            "  - Keep responses concise and helpful",
            "  - Ask clarifying questions when needed",
            "  - Explain tailoring terms in simple language",
        ])

        return "\n".join(parts)

    def format_measurements_summary(self, measurements: dict) -> str:
        """
        Format measurements as a readable summary.

        Args:
            measurements: Dictionary of measurements

        Returns:
            Formatted string summary
        """
        if self.language == "fa":
            lines = ["خلاصه اندازه‌های شما:"]
            for key, value in measurements.items():
                if value is not None:
                    persian_name = MEASUREMENT_TRANSLATIONS.get(key, key)
                    if key == "weight":
                        lines.append(f"• {persian_name}: {value} کیلوگرم")
                    elif key == "bmi":
                        lines.append(f"• {persian_name}: {value:.1f}")
                    else:
                        lines.append(f"• {persian_name}: {value} سانتی‌متر")
            return "\n".join(lines)
        else:
            lines = ["Your measurements summary:"]
            for key, value in measurements.items():
                if value is not None:
                    name = key.replace("_", " ").title()
                    if key == "weight":
                        lines.append(f"• {name}: {value} kg")
                    elif key == "bmi":
                        lines.append(f"• {name}: {value:.1f}")
                    else:
                        lines.append(f"• {name}: {value} cm")
            return "\n".join(lines)

    def build_product_context(self, products: list[dict]) -> str:
        """
        Build context string for available products.

        Args:
            products: List of product dictionaries

        Returns:
            Formatted product context string
        """
        if not products:
            return ""

        if self.language == "fa":
            lines = ["محصولات موجود در فروشگاه:"]
            for p in products[:10]:  # Limit to 10 products in context
                name = p.get("name_fa") or p.get("name", "")
                price = p.get("price", 0)
                category = p.get("category", "")
                lines.append(f"• {name} - {category} - {price:,.0f} تومان")
            return "\n".join(lines)
        else:
            lines = ["Available products:"]
            for p in products[:10]:
                name = p.get("name", "")
                price = p.get("price", 0)
                category = p.get("category", "")
                lines.append(f"• {name} - {category} - ${price:.2f}")
            return "\n".join(lines)

    def format_chat_history(
        self,
        messages: list[ChatMessage],
        max_messages: int = 10
    ) -> list[dict]:
        """
        Format chat history for the LLM.

        Args:
            messages: List of ChatMessage objects
            max_messages: Maximum number of messages to include

        Returns:
            List of message dictionaries
        """
        # Take only recent messages
        recent = messages[-max_messages:] if len(messages) > max_messages else messages

        return [
            {"role": msg.role.value, "content": msg.content}
            for msg in recent
            if msg.role != MessageRole.SYSTEM
        ]
