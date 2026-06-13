import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import chat, lifelogs, privacy, sync
from app.config import get_settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

app = FastAPI(title="Limitless Lifelog Query System", version="0.1.0")

_settings = get_settings()
_cors_kwargs = dict(
    allow_origins=_settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
if _settings.cors_origin_regex:
    _cors_kwargs["allow_origin_regex"] = _settings.cors_origin_regex

app.add_middleware(CORSMiddleware, **_cors_kwargs)

app.include_router(chat.router, prefix="/api")
app.include_router(sync.router, prefix="/api")
app.include_router(lifelogs.router, prefix="/api")
app.include_router(privacy.router, prefix="/api")


@app.get("/api/health")
def health():
    return {"status": "ok"}
