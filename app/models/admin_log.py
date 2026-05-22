"""
Audit log of every state-changing admin action.

action examples:
  - "login.success", "login.failed"
  - "campaign.create", "campaign.update", "campaign.delete"
  - "match.pin", "match.unpin"
  - "user.create", "user.role_change"
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String, Text

from .base import Base


class AdminLog(Base):
    __tablename__ = "admin_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ts = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    username = Column(String, nullable=True, index=True)
    action = Column(String, nullable=False, index=True)
    target = Column(String, nullable=True)
    payload_json = Column(Text, nullable=True)
    ip = Column(String, nullable=True)

    def __repr__(self) -> str:
        return f"<AdminLog {self.ts.isoformat()} {self.username or '-'} {self.action}>"
