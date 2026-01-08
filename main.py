from fastapi import FastAPI

from routers.health import router as health_router
from routers.documents import router as documents_router

app = FastAPI()

# Routers
app.include_router(health_router)
app.include_router(documents_router)
