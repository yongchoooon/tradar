"""SQLAlchemy base model placeholder."""

try:  # pragma: no cover
    from sqlalchemy.orm import declarative_base
except Exception:  # SQLAlchemy isn't installed
    def declarative_base():  # type: ignore
        class Base:  # minimal stub
            pass
        return Base

Base = declarative_base()
