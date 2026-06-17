"""
Help-center tutorial videos. Uploaded by an admin, listed by title in the
Help modal for every operator to watch.

The actual video file lives under app/static/tutorials/<filename>; only the
metadata (title, stored filename, uploader) is kept here.
"""

from __future__ import annotations

from sqlalchemy import Column, Integer, String

from .base import Base, TimestampMixin


class Tutorial(Base, TimestampMixin):
    __tablename__ = "tutorials"

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String, nullable=False)
    filename = Column(String, nullable=False)        # stored name under static/tutorials/
    original_name = Column(String, nullable=True)     # name as uploaded (display only)
    content_type = Column(String, nullable=True)
    size_bytes = Column(Integer, nullable=True)
    uploaded_by = Column(String, nullable=True)

    def __repr__(self) -> str:
        return f"<Tutorial {self.id} {self.title!r}>"
