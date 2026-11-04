from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.core.database import Base, engine, get_db
from app.modules.domain import VideoProject  # Ensure domain tables are registered.
from .service import get_dashboard

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("")
def dashboard(db: Session = Depends(get_db)):
    Base.metadata.create_all(bind=engine)
    return get_dashboard(db)
