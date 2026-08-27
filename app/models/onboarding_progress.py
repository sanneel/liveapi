"""
Which onboarding practice tasks an operator has finished.

One row per (operator, task) pair, written the first time the playground's
validator accepts that task. Progress therefore follows the person rather than
the browser they happened to use, which is the point: a new joiner who starts
the tour on a laptop and finishes it on a shared machine still sees their ticks.

Rows are keyed by username with a cascade, so removing a user takes their
progress with them. The task key is a short slug owned by
app/routes/onboarding.py (KNOWN_TASKS), not free text from the client.
"""

from __future__ import annotations

from sqlalchemy import Column, ForeignKey, PrimaryKeyConstraint, String

from .base import Base, TimestampMixin


class OnboardingProgress(Base, TimestampMixin):
    __tablename__ = "onboarding_progress"
    __table_args__ = (PrimaryKeyConstraint("username", "task_key"),)

    username = Column(
        String,
        ForeignKey("users.username", ondelete="CASCADE"),
        nullable=False,
    )
    task_key = Column(String, nullable=False)

    def __repr__(self) -> str:
        return f"<OnboardingProgress {self.username} {self.task_key!r}>"
