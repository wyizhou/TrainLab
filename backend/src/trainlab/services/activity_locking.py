import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from trainlab.db.models.user import User


def lock_activity_owner(db: Session, user_id: uuid.UUID) -> User | None:
    """First lock for user-owned activity mutations: User -> Import -> Activity."""
    return db.scalar(
        select(User)
        .where(User.id == user_id)
        .execution_options(populate_existing=True)
        .with_for_update()
    )
