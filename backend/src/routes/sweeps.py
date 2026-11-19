from fastapi import APIRouter,Depends
from src.middlewares.auth import current,writer
from src.schemas.business import SweepInput
from src.services import sweeps
from src.controllers.business import start_sweep,resume_sweep
router=APIRouter()
@router.get('/sweeps')
def listing(u=Depends(current)):return sweeps.list_items()
@router.post('/sweeps')
def create(data:SweepInput,u=Depends(writer)):return start_sweep(data,u)
@router.get('/sweeps/{item_id}')
def detail(item_id:int,u=Depends(current)):return sweeps.detail(item_id)
@router.post('/sweeps/{item_id}/resume')
def resume(item_id:int,u=Depends(writer)):return resume_sweep(item_id,u)
