"""
AdminLog repository — append + query the audit trail.

Every state-changing admin action goes through `record()`.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, List, Optional

from sqlalchemy.orm import Session

from ..logging_config import get_logger
from ..models import AdminLog

logger = get_logger("app.repositories.log")


class LogRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def record(
        self,
        action: str,
        username: Optional[str] = None,
        target: Optional[str] = None,
        payload: Optional[Any] = None,
        ip: Optional[str] = None,
    ) -> AdminLog:
        entry = AdminLog(
            ts=datetime.utcnow(),
            username=username,
            action=action,
            target=target,
            payload_json=json.dumps(payload, ensure_ascii=False, default=str) if payload else None,
            ip=ip,
        )
        self.session.add(entry)
        logger.info(f"audit {action} user={username or '-'} target={target or '-'}")
        return entry

    def recent(self, limit: int = 100, action: Optional[str] = None) -> List[AdminLog]:
        q = self.session.query(AdminLog)
        if action:
            q = q.filter(AdminLog.action == action)
        return q.order_by(AdminLog.ts.desc()).limit(limit).all()
