"""Server-side paging: list endpoints accept offset/limit and report the full count in the X-Total-Count header."""
from fastapi import Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session


def page(db: Session, stmt, response: Response, offset: int = 0, limit: int = 50):
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery()))
    response.headers["X-Total-Count"] = str(total or 0)
    return db.scalars(stmt.offset(max(offset, 0)).limit(max(min(limit, 5000), 1))).all()
