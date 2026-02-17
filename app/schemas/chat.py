"""
Chat schemas for the Persian chatbot system.
"""
from datetime import datetime
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class MessageRole(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class ChatMessage(BaseModel):
    """A single chat message."""
    role: MessageRole
    content: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class ChatSessionCreate(BaseModel):
    """Request to create a new chat session."""
    include_measurements: bool = Field(
        default=True,
        description="Include user's body measurements in context"
    )
    preferred_language: str = Field(
        default="fa",
        description="Preferred language (fa=Farsi, en=English)"
    )


class ChatSessionResponse(BaseModel):
    """Chat session info."""
    session_id: str
    user_id: str
    created_at: datetime
    message_count: int
    include_measurements: bool
    preferred_language: str


class ChatMessageRequest(BaseModel):
    """Request to send a message."""
    message: str = Field(..., min_length=1, max_length=2000)
    session_id: Optional[str] = Field(
        default=None,
        description="Session ID. If not provided, uses or creates default session"
    )


class ChatMessageResponse(BaseModel):
    """Response from the chatbot."""
    session_id: str
    user_message: ChatMessage
    assistant_message: ChatMessage
    recommended_products: list["ProductRecommendation"] = Field(default_factory=list)


class ChatHistoryResponse(BaseModel):
    """Chat history for a session."""
    session_id: str
    messages: list[ChatMessage]
    created_at: datetime
    updated_at: datetime


class UserPreferences(BaseModel):
    """User preferences for clothing and fabric."""
    preferred_colors: list[str] = Field(default_factory=list)
    preferred_fabrics: list[str] = Field(default_factory=list)
    preferred_styles: list[str] = Field(default_factory=list)
    size_preference: Optional[str] = None
    budget_range: Optional[tuple[float, float]] = None
    notes: Optional[str] = None


class UserPreferencesUpdate(BaseModel):
    """Update user preferences."""
    preferred_colors: Optional[list[str]] = None
    preferred_fabrics: Optional[list[str]] = None
    preferred_styles: Optional[list[str]] = None
    size_preference: Optional[str] = None
    budget_min: Optional[float] = None
    budget_max: Optional[float] = None
    notes: Optional[str] = None


class ProductRecommendation(BaseModel):
    """A product recommendation from the shop."""
    product_id: str
    name: str
    name_fa: Optional[str] = None
    description: Optional[str] = None
    price: float
    category: str
    image_url: Optional[str] = None
    match_score: float = Field(
        ...,
        ge=0,
        le=1,
        description="How well this product matches user preferences (0-1)"
    )
    match_reasons: list[str] = Field(
        default_factory=list,
        description="Reasons why this product was recommended"
    )


class LLMConfig(BaseModel):
    """Configuration for the LLM."""
    model_path: str
    model_type: str = "causal_lm"  # causal_lm, seq2seq, gguf
    max_new_tokens: int = 512
    temperature: float = 0.7
    top_p: float = 0.9
    top_k: int = 50
    repetition_penalty: float = 1.1
    device: str = "auto"  # auto, cpu, cuda, cuda:0, etc.


# Update forward references
ChatMessageResponse.model_rebuild()
