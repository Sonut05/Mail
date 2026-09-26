"""
Pydantic schemas and validation decorator for JSON request payloads.
"""

from __future__ import annotations
from functools import wraps
from typing import Any, List, Optional
from flask import request, jsonify, g
from pydantic import BaseModel, Field, ValidationError, EmailStr


class LoginPayload(BaseModel):
    email: str = Field(..., max_length=255)
    password: str = Field(..., min_length=1, max_length=128)


class RegisterPayload(BaseModel):
    email: str = Field(..., max_length=255)
    password: str = Field(..., min_length=10, max_length=128)
    name: Optional[str] = Field(None, max_length=255)
    contact_no: Optional[str] = Field(None, max_length=50)


class GenerateReplyPayload(BaseModel):
    email_body: str = Field(..., min_length=1, max_length=50000)
    tone: Optional[str] = Field("Professional", max_length=50)
    custom_instructions: Optional[str] = Field(None, max_length=5000)


class AnalyzeBatchPayload(BaseModel):
    email_ids: Optional[List[str]] = Field(default_factory=list)
    limit: Optional[int] = Field(20, ge=1, le=50)
    force: Optional[bool] = Field(False)


class TaskCreatePayload(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=5000)
    priority: Optional[str] = Field("Medium", max_length=50)
    status: Optional[str] = Field("pending", max_length=50)
    email_id: Optional[str] = Field(None, max_length=36)


class CalendarEventCreatePayload(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    start: str = Field(..., min_length=1, max_length=50)
    end: Optional[str] = Field(None, max_length=50)
    description: Optional[str] = Field(None, max_length=5000)
    email_id: Optional[str] = Field(None, max_length=36)


def validate_schema(schema_cls: type[BaseModel]):
    """Decorator to validate JSON request bodies against a Pydantic model."""
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            raw_data = request.get_json(silent=True)
            if raw_data is None:
                if request.content_length and request.content_length > 0:
                    return jsonify({"error": "Invalid JSON format in request body."}), 400
                raw_data = {}
            try:
                validated = schema_cls(**raw_data)
                g.validated_data = validated
            except ValidationError as err:
                first_err = err.errors()[0]
                field_name = ".".join(str(loc) for loc in first_err.get("loc", []))
                err_msg = first_err.get("msg", "Invalid input")
                return jsonify({
                    "error": f"Invalid field '{field_name}': {err_msg}",
                    "details": err.errors(),
                }), 400
            return f(*args, **kwargs)
        return wrapper
    return decorator
