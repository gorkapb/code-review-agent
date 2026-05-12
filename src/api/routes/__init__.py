from fastapi import APIRouter

from src.api.routes.health import router as health_router
from src.api.routes.reviews import router as reviews_router

router = APIRouter()
router.include_router(health_router)
router.include_router(reviews_router)
