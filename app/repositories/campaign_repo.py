"""
Campaign repository — queries on `campaigns` and `campaign_matches`.

Used by:
  - admin pages (list / create / edit campaigns)
  - public render endpoint /r/{slug}.png (Phase 4)
"""

from __future__ import annotations

from datetime import datetime
from typing import Iterable, List, Optional

from sqlalchemy import delete
from sqlalchemy.orm import Session

from ..logging_config import get_logger
from ..models import Campaign, CampaignMatch, Match

logger = get_logger("app.repositories.campaign")


class CampaignRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    # ─── campaigns ────────────────────────────────────────────────────
    def find_by_slug(self, slug: str) -> Optional[Campaign]:
        return self.session.get(Campaign, slug)

    def list_all(self, enabled_only: bool = False) -> List[Campaign]:
        q = self.session.query(Campaign)
        if enabled_only:
            q = q.filter(Campaign.enabled.is_(True))
        return q.order_by(Campaign.created_at.desc()).all()

    def create(
        self,
        slug: str,
        title: str,
        sport: str,
        mode: str = "manual",
        league: Optional[str] = None,
        created_by: Optional[str] = None,
        vip: bool = False,
    ) -> Campaign:
        c = Campaign(
            slug=slug,
            title=title,
            sport=sport,
            mode=mode,
            league=league,
            vip=vip,
            enabled=True,
            created_by=created_by,
        )
        self.session.add(c)
        logger.info(f"campaign.create slug={slug} sport={sport} mode={mode} by={created_by}")
        return c

    def update(self, slug: str, **fields) -> Optional[Campaign]:
        c = self.find_by_slug(slug)
        if c is None:
            return None
        for k, v in fields.items():
            if hasattr(c, k):
                setattr(c, k, v)
        c.updated_at = datetime.utcnow()
        return c

    def delete(self, slug: str) -> bool:
        c = self.find_by_slug(slug)
        if c is None:
            return False
        self.session.delete(c)
        logger.info(f"campaign.delete slug={slug}")
        return True

    def count(self, enabled_only: bool = False) -> int:
        q = self.session.query(Campaign)
        if enabled_only:
            q = q.filter(Campaign.enabled.is_(True))
        return q.count()

    # ─── campaign_matches ────────────────────────────────────────────
    def get_matches(self, slug: str) -> List[Match]:
        """Return the Match rows attached to a campaign, ordered by position.

        BUG-03: previously used INNER JOIN, which silently dropped
        campaign_match rows whose Match was hard-deleted. Switched to
        LEFT OUTER JOIN with explicit NULL filter so missing rows are
        observable via `get_orphan_event_ids` instead of vanishing.
        """
        rows = (
            self.session.query(Match, CampaignMatch)
            .select_from(CampaignMatch)
            .outerjoin(Match, Match.event_id == CampaignMatch.event_id)
            .filter(CampaignMatch.campaign_slug == slug)
            .filter(Match.event_id.is_not(None))
            .order_by(CampaignMatch.position.asc())
            .all()
        )
        return [m for m, _ in rows]

    def get_orphan_event_ids(self, slug: str) -> List[str]:
        """Return event_ids attached to this campaign whose Match no longer
        exists. Used by the admin UI to surface a "selected match was
        deleted — re-pick or remove" warning instead of silently
        rendering an empty campaign.
        """
        rows = (
            self.session.query(CampaignMatch.event_id)
            .select_from(CampaignMatch)
            .outerjoin(Match, Match.event_id == CampaignMatch.event_id)
            .filter(CampaignMatch.campaign_slug == slug)
            .filter(Match.event_id.is_(None))
            .all()
        )
        return [r[0] for r in rows]

    def get_match_rows(self, slug: str) -> List[CampaignMatch]:
        return (
            self.session.query(CampaignMatch)
            .filter(CampaignMatch.campaign_slug == slug)
            .order_by(CampaignMatch.position.asc())
            .all()
        )

    def set_matches(self, slug: str, event_ids: Iterable[str]) -> int:
        """Replace the campaign's match list with the given ordered list of event_ids."""
        # Clear existing
        self.session.execute(
            delete(CampaignMatch).where(CampaignMatch.campaign_slug == slug)
        )
        n = 0
        for position, event_id in enumerate(event_ids):
            self.session.add(
                CampaignMatch(
                    campaign_slug=slug,
                    event_id=str(event_id),
                    position=position,
                    pinned=False,
                )
            )
            n += 1
        logger.info(f"campaign.set_matches slug={slug} n={n}")
        return n

    def add_match(self, slug: str, event_id: str, pinned: bool = False) -> bool:
        existing = (
            self.session.query(CampaignMatch)
            .filter_by(campaign_slug=slug, event_id=str(event_id))
            .first()
        )
        if existing:
            existing.pinned = pinned
            return False
        # Append at the end
        max_pos = (
            self.session.query(CampaignMatch)
            .filter(CampaignMatch.campaign_slug == slug)
            .count()
        )
        self.session.add(
            CampaignMatch(
                campaign_slug=slug,
                event_id=str(event_id),
                position=max_pos,
                pinned=pinned,
            )
        )
        return True

    def remove_match(self, slug: str, event_id: str) -> bool:
        result = self.session.execute(
            delete(CampaignMatch)
            .where(CampaignMatch.campaign_slug == slug)
            .where(CampaignMatch.event_id == str(event_id))
        )
        return (result.rowcount or 0) > 0
