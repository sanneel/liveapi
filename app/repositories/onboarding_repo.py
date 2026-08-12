"""Onboarding progress repository — which practice tasks an operator finished."""

from __future__ import annotations

from typing import List

from sqlalchemy.orm import Session

from ..logging_config import get_logger
from ..models import OnboardingProgress

logger = get_logger("app.repositories.onboarding")


class OnboardingRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def done_for(self, username: str) -> List[str]:
        """Task keys this operator has completed, oldest first."""
        rows = (
            self.session.query(OnboardingProgress)
            .filter(OnboardingProgress.username == username)
            .order_by(OnboardingProgress.created_at.asc())
            .all()
        )
        return [r.task_key for r in rows]

    def mark(self, username: str, task_key: str) -> None:
        """Record a finished task. Finishing it twice is not an error."""
        if self.session.get(OnboardingProgress, (username, task_key)) is not None:
            return
        self.session.add(OnboardingProgress(username=username, task_key=task_key))
        self.session.flush()
        logger.info(f"onboarding task done: {username} {task_key}")

    def unmark(self, username: str, task_key: str) -> None:
        """Clear one task, so an operator can redo it from scratch."""
        row = self.session.get(OnboardingProgress, (username, task_key))
        if row is None:
            return
        self.session.delete(row)
        self.session.flush()
        logger.info(f"onboarding task cleared: {username} {task_key}")
