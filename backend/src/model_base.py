"""Single SQLAlchemy metadata registry shared by all HMS models."""
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
