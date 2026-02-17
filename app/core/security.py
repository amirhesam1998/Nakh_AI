"""
Security utilities for password hashing and token generation.
"""
import secrets

from passlib.context import CryptContext

# Password hashing context using bcrypt
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    """
    Hash a password using bcrypt.

    Args:
        password: Plain text password

    Returns:
        Hashed password string
    """
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verify a password against its hash.

    Args:
        plain_password: Plain text password to verify
        hashed_password: Hashed password to compare against

    Returns:
        True if password matches, False otherwise
    """
    return pwd_context.verify(plain_password, hashed_password)


def generate_token() -> str:
    """
    Generate a secure random token.

    Returns:
        40-character hex string (same format as Django REST Framework tokens)
    """
    return secrets.token_hex(20)


def validate_password_strength(password: str) -> list[str]:
    """
    Validate password strength and return list of issues.

    Args:
        password: Password to validate

    Returns:
        List of validation error messages (empty if valid)
    """
    errors = []

    if len(password) < 8:
        errors.append("Password must be at least 8 characters long")

    if not any(c.isdigit() for c in password):
        errors.append("Password must contain at least one digit")

    if not any(c.isalpha() for c in password):
        errors.append("Password must contain at least one letter")

    if not any(c.isupper() for c in password):
        errors.append("Password should contain at least one uppercase letter")

    if not any(c.islower() for c in password):
        errors.append("Password should contain at least one lowercase letter")

    return errors
