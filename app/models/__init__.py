"""All ORM models — imported here so Alembic autogenerate sees them."""

from .admin_log import AdminLog
from .base import Base
from .campaign import Campaign
from .campaign_hit import CampaignHit
from .campaign_match import CampaignMatch
from .club import Club
from .hot_boost import HotBoost
from .hot_override import HotOverrideConfig, HotOverrideMatch
from .match import Match
from .user import User

__all__ = [
    "AdminLog",
    "Base",
    "Campaign",
    "CampaignHit",
    "CampaignMatch",
    "Club",
    "HotBoost",
    "HotOverrideConfig",
    "HotOverrideMatch",
    "Match",
    "User",
]
