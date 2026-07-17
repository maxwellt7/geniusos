import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from fastapi import Depends

from contextlib import asynccontextmanager

from app.api import chat, chats, lifelogs, privacy, sync
from app.api.sync import start_sync_scheduler
from app.auth.clerk import require_clerk_user
from app.config import get_settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    start_sync_scheduler()
    yield


app = FastAPI(title="Limitless Lifelog Query System", version="0.1.0", lifespan=lifespan)

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

# All data/API routers require a valid Clerk session when REQUIRE_CLERK_AUTH is
# on (the dependency is a no-op otherwise). /api/health stays open for Railway.
_auth = [Depends(require_clerk_user)]
app.include_router(chat.router, prefix="/api", dependencies=_auth)
app.include_router(chats.router, prefix="/api", dependencies=_auth)
app.include_router(sync.router, prefix="/api", dependencies=_auth)
app.include_router(lifelogs.router, prefix="/api", dependencies=_auth)
app.include_router(privacy.router, prefix="/api", dependencies=_auth)


@app.get("/api/health")
def health():
    return {"status": "ok"}
