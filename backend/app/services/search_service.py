"""
Search service — safe AST query parser and parameterized SQLAlchemy execution.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import or_, and_, text

from app.models import EmailMessage


def parse_search_query(raw_query: str) -> tuple[dict[str, Any], list[str]]:
    """Parse search query into structured filter tokens and free-text keywords.

    Examples:
        'from:john priority:high after:2026-09-01 invoice'
        -> filters={'from': 'john', 'priority': 'high', 'after': '2026-09-01'}, keywords=['invoice']
    """
    filters: dict[str, Any] = {}
    keywords: list[str] = []

    # Pattern matches key:value or key:"quoted value"
    pattern = re.compile(r'(\b[a-zA-Z_]+):(?:"([^"]+)"|(\S+))')

    remaining = raw_query.strip()
    matches = pattern.findall(remaining)

    for key, val_quoted, val_plain in matches:
        k = key.lower()
        v = (val_quoted or val_plain).strip()
        filters[k] = v

    # Remove matched tokens from the query string to get remaining free-text keywords
    cleaned_query = pattern.sub(" ", remaining)
    kw_pattern = re.compile(r'"([^"]+)"|(\S+)')
    for phrase, word in kw_pattern.findall(cleaned_query):
        val = (phrase or word).strip()
        if val:
            keywords.append(val)

    return filters, keywords


def execute_advanced_search(
    user_id: str,
    query_str: Optional[str] = None,
    explicit_filters: Optional[dict[str, Any]] = None,
    page: int = 1,
    per_page: int = 20,
) -> dict[str, Any]:
    """Execute parameterized search over user emails with combined query syntax and parameters."""
    query = EmailMessage.query.filter(EmailMessage.user_id == user_id)

    filters: dict[str, Any] = {}
    keywords: list[str] = []

    if query_str:
        filters, keywords = parse_search_query(query_str)

    # Merge explicit parameters if provided
    if explicit_filters:
        for k, v in explicit_filters.items():
            if v is not None and str(v).strip():
                filters[k.lower()] = str(v).strip()

    filters_applied: dict[str, Any] = {}

    # 1. Free-text keywords
    if keywords:
        kw_str = " ".join(keywords)
        term = f"%{kw_str}%"
        filters_applied["keywords"] = kw_str
        query = query.filter(
            or_(
                EmailMessage.subject.ilike(term),
                EmailMessage.body_text.ilike(term),
                EmailMessage.ai_summary.ilike(term),
                EmailMessage.summary.ilike(term),
                EmailMessage.from_address.ilike(term),
                EmailMessage.to_address.ilike(term),
            )
        )

    # 2. Sender filter (from:... or sender:...)
    sender_val = filters.get("from") or filters.get("sender")
    if sender_val:
        filters_applied["sender"] = sender_val
        query = query.filter(EmailMessage.from_address.ilike(f"%{sender_val}%"))

    # 3. Recipient filter (to:... or recipient:...)
    to_val = filters.get("to") or filters.get("recipient")
    if to_val:
        filters_applied["recipient"] = to_val
        query = query.filter(EmailMessage.to_address.ilike(f"%{to_val}%"))

    # 4. Subject filter
    subject_val = filters.get("subject")
    if subject_val:
        filters_applied["subject"] = subject_val
        query = query.filter(EmailMessage.subject.ilike(f"%{subject_val}%"))

    # 5. Category filter
    cat_val = filters.get("category")
    if cat_val:
        filters_applied["category"] = cat_val.lower()
        query = query.filter(
            or_(
                EmailMessage.ai_category.ilike(cat_val),
                EmailMessage.category.ilike(cat_val),
            )
        )

    # 6. Priority filter
    prio_val = filters.get("priority")
    if prio_val:
        filters_applied["priority"] = prio_val.lower()
        query = query.filter(
            or_(
                EmailMessage.ai_priority.ilike(prio_val),
                EmailMessage.priority.ilike(prio_val),
            )
        )

    # 7. Importance filter (importance:>70, importance:high, etc.)
    imp_val = filters.get("importance")
    if imp_val:
        filters_applied["importance"] = imp_val
        if imp_val.startswith(">"):
            try:
                min_score = int(imp_val[1:])
                query = query.filter(EmailMessage.ai_importance_score >= min_score)
            except ValueError:
                pass
        elif imp_val.startswith("<"):
            try:
                max_score = int(imp_val[1:])
                query = query.filter(EmailMessage.ai_importance_score <= max_score)
            except ValueError:
                pass
        elif imp_val.lower() == "urgent":
            query = query.filter(EmailMessage.ai_importance_score >= 81)
        elif imp_val.lower() == "high":
            query = query.filter(EmailMessage.ai_importance_score >= 61)
        else:
            try:
                score = int(imp_val)
                query = query.filter(EmailMessage.ai_importance_score >= score)
            except ValueError:
                pass

    # 8. Attachment filter (has:attachment or attachment:true)
    has_val = filters.get("has", "").lower()
    att_val = filters.get("attachment", "").lower()
    if has_val == "attachment" or att_val in ("true", "1", "yes"):
        filters_applied["has_attachment"] = True
        query = query.filter(EmailMessage.has_attachments == True)

    # 9. Action required filter (action:true or action:required)
    act_val = filters.get("action", "").lower()
    if act_val in ("true", "1", "required", "yes"):
        filters_applied["action_required"] = True
        query = query.filter(EmailMessage.ai_action_required == True)
    elif act_val in ("false", "0", "no"):
        filters_applied["action_required"] = False
        query = query.filter(EmailMessage.ai_action_required == False)

    # 10. Waiting-for filter (waiting:true or waiting:for)
    wait_val = filters.get("waiting", "").lower()
    if wait_val in ("true", "1", "yes", "for"):
        filters_applied["waiting"] = True
        query = query.filter(
            EmailMessage.ai_waiting_for.isnot(None),
            EmailMessage.ai_waiting_for != "",
        )

    # 11. Date range filters (after:YYYY-MM-DD, before:YYYY-MM-DD, date_from, date_to)
    after_str = filters.get("after") or filters.get("date_from")
    if after_str:
        try:
            dt_after = datetime.fromisoformat(after_str.replace("Z", "+00:00"))
            filters_applied["after"] = after_str
            query = query.filter(EmailMessage.received_at >= dt_after)
        except Exception:
            pass

    before_str = filters.get("before") or filters.get("date_to")
    if before_str:
        try:
            dt_before = datetime.fromisoformat(before_str.replace("Z", "+00:00"))
            filters_applied["before"] = before_str
            query = query.filter(EmailMessage.received_at <= dt_before)
        except Exception:
            pass

    # 12. AI Status filter (status:... or ai:...)
    status_val = filters.get("status") or filters.get("ai")
    if status_val:
        filters_applied["ai_status"] = status_val.lower()
        query = query.filter(EmailMessage.ai_status == status_val.lower())

    # Execute ordering and pagination
    query = query.order_by(EmailMessage.received_at.desc())
    page = max(int(page), 1)
    per_page = min(max(int(per_page), 1), 100)
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    return {
        "items": [e.to_dict() for e in pagination.items],
        "emails": [e.to_dict() for e in pagination.items],  # frontend & API compat
        "results": [e.to_dict() for e in pagination.items],  # backward compat
        "total": pagination.total,
        "page": pagination.page,
        "page_size": pagination.per_page,
        "pages": pagination.pages,
        "has_next": pagination.has_next,
        "has_prev": pagination.has_prev,
        "filters_applied": filters_applied,
    }
