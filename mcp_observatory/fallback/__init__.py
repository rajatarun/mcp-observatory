"""Fallback routing interfaces."""

from .router import FallbackRouter
from .templates import block_response_template, review_response_template

__all__ = ["FallbackRouter", "block_response_template", "review_response_template"]
