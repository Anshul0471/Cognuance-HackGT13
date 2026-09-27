from fastapi import APIRouter

from app.api.v1 import auth, doctor, patient_assessments, status

api_router = APIRouter()
api_router.include_router(status.router)
api_router.include_router(auth.router)
api_router.include_router(patient_assessments.router)
api_router.include_router(doctor.router)
