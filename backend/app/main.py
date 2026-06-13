import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import chat, lifelogs, privacy, sync

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

app = FastAPI(title="Limitless Lifelog Query System", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat.router, prefix="/api")
app.include_router(sync.router, prefix="/api")
app.include_router(lifelogs.router, prefix="/api")
app.include_router(privacy.router, prefix="/api")


@app.get("/api/health")
def health():
    return {"status": "ok"}
