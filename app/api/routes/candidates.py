from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.core.security import get_current_user_id
from app.models.candidate import Candidate, CandidateStatus

router = APIRouter(
    prefix="/candidates", tags=["candidates"], dependencies=[Depends(get_current_user_id)]
)


class StatusIn(BaseModel):
    status: CandidateStatus


async def get_candidate_or_404(candidate_id: str) -> Candidate:
    candidate = await Candidate.get(candidate_id)
    if candidate is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Candidate not found")
    return candidate


@router.get("/")
async def list_candidates(status_filter: str | None = None, search: str | None = None) -> list[Candidate]:
    query: dict = {}
    if status_filter and status_filter != "all":
        query["status"] = status_filter
    if search:
        query["$or"] = [
            {"name": {"$regex": search, "$options": "i"}},
            {"email": {"$regex": search, "$options": "i"}},
            {"position": {"$regex": search, "$options": "i"}},
        ]
    return await Candidate.find(query).sort(-Candidate.invited_at).to_list()


@router.get("/{candidate_id}")
async def get_candidate(candidate_id: str) -> Candidate:
    return await get_candidate_or_404(candidate_id)


@router.patch("/{candidate_id}/status")
async def update_status(candidate_id: str, payload: StatusIn) -> Candidate:
    candidate = await get_candidate_or_404(candidate_id)
    candidate.status = payload.status
    await candidate.save()
    return candidate


@router.post("/{candidate_id}/analyze", status_code=status.HTTP_501_NOT_IMPLEMENTED)
async def analyze_candidate(candidate_id: str) -> dict:
    return {
        "detail": "Not implemented: run AI analysis over submitted files and replay, store ai_report"
    }
