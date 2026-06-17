"""Tutorial repository — CRUD over the help-center video library."""

from __future__ import annotations

from typing import List, Optional

from sqlalchemy.orm import Session

from ..logging_config import get_logger
from ..models import Tutorial

logger = get_logger("app.repositories.tutorial")


class TutorialRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list_all(self) -> List[Tutorial]:
        """Newest first."""
        return (
            self.session.query(Tutorial)
            .order_by(Tutorial.created_at.desc(), Tutorial.id.desc())
            .all()
        )

    def get(self, tutorial_id: int) -> Optional[Tutorial]:
        return self.session.get(Tutorial, tutorial_id)

    def create(
        self,
        *,
        title: str,
        filename: str,
        original_name: Optional[str],
        content_type: Optional[str],
        size_bytes: Optional[int],
        uploaded_by: Optional[str],
    ) -> Tutorial:
        tutorial = Tutorial(
            title=title,
            filename=filename,
            original_name=original_name,
            content_type=content_type,
            size_bytes=size_bytes,
            uploaded_by=uploaded_by,
        )
        self.session.add(tutorial)
        self.session.flush()  # assign id
        logger.info(f"tutorial.create id={tutorial.id} title={title!r} by={uploaded_by}")
        return tutorial

    def delete(self, tutorial: Tutorial) -> None:
        logger.info(f"tutorial.delete id={tutorial.id} title={tutorial.title!r}")
        self.session.delete(tutorial)
