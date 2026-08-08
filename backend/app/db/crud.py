from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Generic, TypeVar

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Base


ModelT = TypeVar("ModelT", bound=Base)


class CRUDBase(Generic[ModelT]):
    def __init__(self, model: type[ModelT]) -> None:
        self.model = model

    def get(self, session: Session, object_id: Any) -> ModelT | None:
        return session.get(self.model, object_id)

    def list(self, session: Session, *, offset: int = 0, limit: int = 100) -> Sequence[ModelT]:
        statement = select(self.model).offset(offset).limit(limit)
        return session.scalars(statement).all()

    def create(self, session: Session, *, values: dict[str, Any], commit: bool = True) -> ModelT:
        instance = self.model(**values)
        session.add(instance)
        if commit:
            session.commit()
            session.refresh(instance)
        else:
            session.flush()
        return instance

    def update(
        self, session: Session, *, instance: ModelT, values: dict[str, Any], commit: bool = True
    ) -> ModelT:
        for field, value in values.items():
            if not hasattr(instance, field):
                raise ValueError(f"Unknown {self.model.__name__} field: {field}")
            setattr(instance, field, value)
        session.add(instance)
        if commit:
            session.commit()
            session.refresh(instance)
        else:
            session.flush()
        return instance

    def delete(self, session: Session, *, instance: ModelT, commit: bool = True) -> None:
        session.delete(instance)
        if commit:
            session.commit()
        else:
            session.flush()
