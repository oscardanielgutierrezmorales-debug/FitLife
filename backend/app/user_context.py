"""Account-scoped context loaded only from authenticated database records."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import Plan, PlanDay, Profile, Progress, User, UserMemory


@dataclass(frozen=True)
class UserContext:
    user: User
    profile: Profile
    plan: Plan | None
    days: list[PlanDay]
    progress: list[Progress]
    memory: UserMemory | None


def get_user_context(db: Session, authenticated_user_id: str) -> UserContext:
    """Load one user's profile, plan, progress and compact memory together."""
    user = db.get(User, authenticated_user_id)
    profile = db.get(Profile, authenticated_user_id)
    if not user or not profile:
        raise LookupError("authenticated user context is incomplete")
    plan = db.scalar(select(Plan).where(Plan.user_id == authenticated_user_id))
    days = list(db.scalars(select(PlanDay).where(PlanDay.plan_id == plan.id).order_by(PlanDay.day_index))) if plan else []
    progress = list(db.scalars(select(Progress).where(Progress.user_id == authenticated_user_id).order_by(Progress.date)))
    memory = db.get(UserMemory, authenticated_user_id)
    return UserContext(user=user, profile=profile, plan=plan, days=days, progress=progress, memory=memory)
