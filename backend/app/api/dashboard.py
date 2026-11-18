from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.auth import User
from app.models.debate import Debate
from app.models.knowledge import ResearchJob, TopicDossier

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

@router.get("/summary")
def summary(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    jobs = db.query(ResearchJob).order_by(ResearchJob.updated_at.desc()).limit(8).all()
    return {
      "user": {"id": user.id, "display_name": user.display_name, "email": user.email},
      "counts": {"debates": db.query(Debate).count(), "dossiers": db.query(TopicDossier).count(), "research_jobs": db.query(ResearchJob).count()},
      "debates": [{"id": d.id, "title": d.title, "fixed_question": d.fixed_question, "status": d.status.value} for d in db.query(Debate).order_by(Debate.created_at.desc()).limit(12)],
      "jobs": [{"id": j.id, "query": j.query, "status": j.status.value, "progress_percent": j.progress_percent, "current_step": j.current_step} for j in jobs]
    }
