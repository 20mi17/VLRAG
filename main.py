from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from routers.documents import router as documents_router
from routers.health import router as health_router
from routers.rag import router as rag_router
from routers.search import router as search_router
from routers.uploads import router as uploads_router

app = FastAPI()

# Routers
app.include_router(health_router)
app.include_router(documents_router)
app.include_router(search_router)
app.include_router(rag_router)
app.include_router(uploads_router)

app.mount("/", StaticFiles(directory="static", html=True), name="static")