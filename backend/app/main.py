import logging
import socket
import sys
import threading
import subprocess
import time
import os
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
import asyncio
from typing import IO, List, Optional
from app.core.logging_config import setup_logging
from app.core.config import settings
from app.core.firebase import init_firebase, _app as firebase_app
from app.core.database import connect_db, close_db, get_aura_modules_db, check_db_health
from app.routes import (
    auth,
    assessment,
    onboarding,
    medications,
    journal,
    relatives,
    sos,
    location,
    admin,
    ws,
    aura,
    user,
    notifications,
    suggestions,
    orito,
    reports,
    reminders,
    calls,
    aura_status,
)
from app.routes import settings as settings_router
from app.services.cleanup_task import cleanup_stale_modules
from app.services.reminder_scheduler import reminder_check_loop
from app.services.notifications import shutdown_executor as shutdown_fcm_executor

try:
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None


GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
CYAN = "\033[96m"
RESET = "\033[0m"
BOLD = "\033[1m"


#------This Function resolves backend update interval---------
def _get_update_interval_seconds() -> int:
    raw_value = os.getenv("BACKEND_UPDATE_CHECK_INTERVAL_SECONDS", "300")
    try:
        interval_seconds = int(raw_value)
    except ValueError:
        interval_seconds = 300
    return max(interval_seconds, 60)


UPDATE_CHECK_INTERVAL = _get_update_interval_seconds()
AUTO_UPDATE_ENABLED = os.getenv("BACKEND_AUTO_UPDATE_ENABLED", "true").lower() == "true"
AUTO_RESTART_ON_UPDATE = os.getenv("BACKEND_AUTO_RESTART_ON_UPDATE", "false").lower() == "true"
BACKEND_ROOT = Path(__file__).resolve().parents[1]
UPDATE_LOCK_PATH = Path("/tmp/aura_repo_update.lock")

setup_logging(debug=(settings.environment != "production"))
logger = logging.getLogger(__name__)
_update_monitor_thread: Optional[threading.Thread] = None
_update_monitor_stop_event = threading.Event()
_update_monitor_lock = threading.Lock()


#------This Function acquires process-level update lock-------
def _acquire_process_update_lock() -> Optional[IO[str]]:
    if fcntl is None:
        return None
    lock_file = open(UPDATE_LOCK_PATH, "w")
    try:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return lock_file
    except OSError:
        lock_file.close()
        return None


#------This Function releases process-level update lock-------
def _release_process_update_lock(lock_file: Optional[IO[str]]) -> None:
    if fcntl is None or lock_file is None:
        return
    try:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
    finally:
        lock_file.close()


#------This Function runs git commands for auto-update-------
def _run_git_command(args: List[str], timeout: int = 20) -> Optional[subprocess.CompletedProcess]:
    try:
        return subprocess.run(
            ["git"] + args,
            cwd=str(BACKEND_ROOT),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError:
        logger.warning("[UPDATE] git executable not found; disabling update checks")
    except subprocess.TimeoutExpired:
        logger.warning("[UPDATE] git command timed out: git %s", " ".join(args))
    except Exception as exc:
        logger.warning("[UPDATE] git command failed: git %s (%s)", " ".join(args), exc)
    return None


#------This Function checks whether backend runs inside a git repository-------
def _is_git_repository() -> bool:
    result = _run_git_command(["rev-parse", "--is-inside-work-tree"])
    if result is None or result.returncode != 0:
        return False
    return result.stdout.strip() == "true"


#------This Function resolves the upstream tracking branch-------
def _get_tracking_branch() -> Optional[str]:
    result = _run_git_command(["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"])
    if result is None or result.returncode != 0:
        return None
    branch = result.stdout.strip()
    return branch if branch else None


#------This Function checks whether local working tree is clean-------
def _is_work_tree_clean() -> bool:
    result = _run_git_command(["status", "--porcelain"])
    if result is None or result.returncode != 0:
        return False
    return result.stdout.strip() == ""


#------This Function checks for git updates-------
def check_for_updates() -> bool:
    tracking_branch = _get_tracking_branch()
    if tracking_branch is None:
        logger.debug("[UPDATE] Upstream tracking branch is not configured")
        return False

    fetch_result = _run_git_command(["fetch", "--prune", "--quiet"])
    if fetch_result is None or fetch_result.returncode != 0:
        error_text = fetch_result.stderr.strip() if fetch_result else "unknown fetch error"
        logger.warning("[UPDATE] Failed to fetch remote updates: %s", error_text)
        return False

    local_head_result = _run_git_command(["rev-parse", "HEAD"])
    remote_head_result = _run_git_command(["rev-parse", tracking_branch])
    if (
        local_head_result is None
        or remote_head_result is None
        or local_head_result.returncode != 0
        or remote_head_result.returncode != 0
    ):
        return False

    local_sha = local_head_result.stdout.strip()
    remote_sha = remote_head_result.stdout.strip()
    return bool(local_sha and remote_sha and local_sha != remote_sha)


#------This Function pulls updates-------
def pull_updates() -> bool:
    if not _is_work_tree_clean():
        logger.warning("[UPDATE] Local changes detected; skipping auto-pull to avoid merge conflicts")
        return False

    pull_result = _run_git_command(["pull", "--ff-only"], timeout=60)
    if pull_result is None:
        return False
    if pull_result.returncode != 0:
        error_text = pull_result.stderr.strip() or pull_result.stdout.strip() or "unknown pull error"
        logger.error("[UPDATE] Failed to pull updates: %s", error_text)
        return False

    return True


#------This Function restarts backend after successful update-------
def _restart_after_update() -> None:
    if not AUTO_RESTART_ON_UPDATE:
        logger.warning(
            "[UPDATE] Updates were pulled. Manual restart required. "
            "Set BACKEND_AUTO_RESTART_ON_UPDATE=true to enable self-restart."
        )
        return

    if os.getenv("UVICORN_FD"):
        logger.warning(
            "[UPDATE] Backend is running in a uvicorn managed worker; "
            "skipping self-restart to avoid duplicate server processes."
        )
        return

    bind_host, bind_port = _resolve_runtime_bind()
    restart_args = [
        sys.executable,
        "-m",
        "uvicorn",
        "app.main:app",
        "--host",
        bind_host,
        "--port",
        str(bind_port),
    ]
    if settings.environment != "production":
        restart_args.append("--reload")

    logger.info("[UPDATE] Restarting backend process to apply updates")
    os.execv(sys.executable, restart_args)


#------This Function monitors for updates in background-------
def update_monitor() -> None:
    while not _update_monitor_stop_event.wait(UPDATE_CHECK_INTERVAL):
        try:
            with _update_monitor_lock:
                lock_file = _acquire_process_update_lock()
                if fcntl is not None and lock_file is None:
                    logger.debug("[UPDATE] Another process is running an update cycle; skipping this interval")
                    continue
                try:
                    logger.info("[UPDATE] Checking for updates...")
                    if not check_for_updates():
                        continue

                    logger.info("[UPDATE] Updates found. Pulling latest changes...")
                    if pull_updates():
                        logger.info("[UPDATE] Updates pulled successfully")
                        _restart_after_update()
                finally:
                    _release_process_update_lock(lock_file)
        except Exception as exc:
            logger.warning("[UPDATE] Update monitor cycle failed: %s", exc)


#------This Function starts the background update monitor-------
def start_update_monitor() -> bool:
    global _update_monitor_thread

    if not AUTO_UPDATE_ENABLED:
        logger.info("[UPDATE] Auto-update monitor disabled (BACKEND_AUTO_UPDATE_ENABLED=false)")
        return False

    if not _is_git_repository():
        logger.warning("[UPDATE] Auto-update monitor disabled: backend is not inside a git repository")
        return False

    if _get_tracking_branch() is None:
        logger.warning("[UPDATE] Auto-update monitor disabled: no upstream tracking branch configured")
        return False

    if _update_monitor_thread and _update_monitor_thread.is_alive():
        return True

    _update_monitor_stop_event.clear()
    _update_monitor_thread = threading.Thread(
        target=update_monitor,
        name="backend-update-monitor",
        daemon=True,
    )
    _update_monitor_thread.start()
    return True


#------This Function stops the background update monitor-------
def stop_update_monitor() -> None:
    if _update_monitor_thread and _update_monitor_thread.is_alive():
        _update_monitor_stop_event.set()
        _update_monitor_thread.join(timeout=2)


_cleanup_task = None
_reminder_task = None


#------This Function handles the CLI arguments---------
def _get_cli_arg_value(flag: str) -> Optional[str]:
    for index, arg in enumerate(sys.argv):
        if arg == flag and index + 1 < len(sys.argv):
            return sys.argv[index + 1]
        if arg.startswith(f"{flag}="):
            return arg.split("=", 1)[1]
    return None


#------This Function resolves the runtime bind---------
def _resolve_runtime_bind() -> tuple[str, int]:
    host = _get_cli_arg_value("--host")
    port_value = _get_cli_arg_value("--port")
    launched_with_uvicorn = any("uvicorn" in arg for arg in sys.argv[:2])

    if host is None:
        host = "127.0.0.1" if launched_with_uvicorn else settings.server_host

    try:
        port = int(port_value) if port_value else settings.port
    except ValueError:
        port = settings.port

    return host, port


#------This Function gets the LAN IPv4---------
def _get_lan_ipv4() -> Optional[str]:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            ip = sock.getsockname()[0]
            if ip and not ip.startswith("127."):
                return ip
    except OSError:
        pass

    try:
        hostname_ip = socket.gethostbyname(socket.gethostname())
        if hostname_ip and not hostname_ip.startswith("127."):
            return hostname_ip
    except OSError:
        pass

    return None


#------This Function logs the access URLs---------
def _log_access_urls() -> None:
    bind_host, bind_port = _resolve_runtime_bind()
    lan_ip = _get_lan_ipv4()

    logger.info(f"Local API URL: http://127.0.0.1:{bind_port}")
    if lan_ip:
        logger.info(f"Network API URL: http://{lan_ip}:{bind_port}")
    else:
        logger.warning("Network API URL: could not determine LAN IP address")

    if bind_host in {"127.0.0.1", "localhost"}:
        logger.warning(
            "Server is bound to loopback only. Use: uvicorn app.main:app --reload --host 0.0.0.0 --port %s",
            bind_port,
        )


#------This Function handles the lifespan events---------
@asynccontextmanager
async def lifespan(app: FastAPI):
    global _cleanup_task, _reminder_task

    
    logger.info(f"Starting {settings.environment} environment")
    print(f"{BOLD}{BLUE}A.U.R.A Backend v1.0.0{RESET}")
    
    try:
        init_firebase()
        print(f"{GREEN}[OK] Firebase initialized{RESET}")
    except Exception as e:
        logger.error(f"Failed to initialize Firebase: {str(e)}")
        raise

    try:
        await connect_db()
        print(f"{GREEN}[OK] Database connected{RESET}")
    except Exception as e:
        logger.error(f"Failed to connect to database: {str(e)}")
        raise

    if start_update_monitor():
        print(f"{CYAN}[UPDATE] Auto-update monitor started{RESET}")
    else:
        print(f"{YELLOW}[UPDATE] Auto-update monitor disabled{RESET}")

    
    try:
        aura_modules_db = get_aura_modules_db()
        _cleanup_task = asyncio.create_task(cleanup_stale_modules(aura_modules_db))
        print(f"{GREEN}[OK] Background cleanup task started{RESET}")
    except Exception as e:
        logger.warning(f"Could not start cleanup task: {str(e)}")

    try:
        _reminder_task = asyncio.create_task(reminder_check_loop())
        print(f"{GREEN}[OK] Reminder scheduler started{RESET}")
    except Exception as e:
        logger.warning(f"Could not start reminder scheduler: {str(e)}")

    _log_access_urls()

    yield

    
    logger.info("Shutting down application...")
    print(f"{YELLOW}[SHUTDOWN] Stopping services...{RESET}")
    if _cleanup_task:
        _cleanup_task.cancel()
        try:
            await _cleanup_task
        except asyncio.CancelledError:
            pass
    if _reminder_task:
        _reminder_task.cancel()
        try:
            await _reminder_task
        except asyncio.CancelledError:
            pass
    stop_update_monitor()
    shutdown_fcm_executor()

    await close_db()
    print(f"{RED}[SHUTDOWN] Application shutdown complete{RESET}")


app = FastAPI(
    title="Aura API",
    description="Assistive User Reminder App — Backend",
    version="1.0.0",
    lifespan=lifespan,
)



#------This Function handles validation errors---------
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    logger.warning(f"Validation error for {request.method} {request.url}: {exc.errors()}")
    return JSONResponse(
        status_code=422,
        content={
            "detail": "Validation error",
            "errors": exc.errors(),
        },
    )


#------This Function handles value errors---------
@app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError):
    logger.warning(f"Value error for {request.method} {request.url}: {str(exc)}")
    return JSONResponse(
        status_code=400,
        content={"detail": str(exc)},
    )


#------This Function handles general exceptions---------
@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unexpected error for {request.method} {request.url}: {str(exc)}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error" if settings.environment == "production" else str(exc)},
    )


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_http_logger = logging.getLogger("aura.http")
_METHOD_COLOUR = {
    "GET":    "\033[38;5;39m",
    "POST":   "\033[38;5;82m",
    "PUT":    "\033[38;5;220m",
    "PATCH":  "\033[38;5;208m",
    "DELETE": "\033[38;5;196m",
}
_STATUS_COLOUR = {
    2: "\033[38;5;82m",   # 2xx green
    3: "\033[38;5;51m",   # 3xx cyan
    4: "\033[38;5;220m",  # 4xx yellow
    5: "\033[38;5;196m",  # 5xx red
}


#------This middleware logs each HTTP request with colours---------
@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    ms = (time.perf_counter() - start) * 1000
    method = request.method
    path = request.url.path
    status = response.status_code
    mc = _METHOD_COLOUR.get(method, "\033[0m")
    sc = _STATUS_COLOUR.get(status // 100, "\033[0m")
    _http_logger.info(
        f"{mc}{method:<7}\033[0m {path}  {sc}{status}\033[0m  \033[2m{ms:.0f}ms\033[0m"
    )
    return response


app.include_router(auth.router)
app.include_router(assessment.router)
app.include_router(user.router)
app.include_router(onboarding.router)
app.include_router(medications.router)
app.include_router(journal.router)
app.include_router(relatives.router)
app.include_router(sos.router)
app.include_router(location.router)
app.include_router(notifications.router)
app.include_router(settings_router.router)
app.include_router(suggestions.router)
app.include_router(admin.router)
app.include_router(ws.router)
app.include_router(aura.router)
app.include_router(orito.router)
app.include_router(reports.router)
app.include_router(reminders.router)
app.include_router(calls.router)
app.include_router(aura_status.router)


#------This Function returns health status---------
@app.get("/health")
async def health():
    return {"status": "alive", "service": "aura-backend", "environment": settings.environment}


#------This Function returns detailed health status---------
@app.get("/health/detailed")
async def health_detailed():
    db_health = await check_db_health()
    
    firebase_health = {"status": "healthy"}
    try:
        if firebase_app is None:
            firebase_health = {"status": "uninitialized"}
    except Exception as e:
        firebase_health = {"status": "unhealthy", "error": str(e)}
    
    aura_modules_health = {"total": 0, "online": 0, "offline": 0}
    try:
        aura_modules_db = get_aura_modules_db()
        all_modules = await aura_modules_db.list_modules(limit=1000)
        aura_modules_health = {
            "total": len(all_modules),
            "online": sum(1 for m in all_modules if m.get("status") == "online"),
            "offline": sum(1 for m in all_modules if m.get("status") != "online")
        }
    except Exception as e:
        aura_modules_health = {"error": str(e)}
    
    health_score = 100
    if db_health.get("status") != "healthy":
        health_score -= 40
    if firebase_health.get("status") not in ("healthy", "uninitialized"):
        health_score -= 30
    if aura_modules_health.get("total", 0) > 0 and aura_modules_health.get("online", 0) == 0:
        health_score -= 30
    
    health_score = max(0, health_score)
    
    return {
        "status": "alive",
        "service": "aura-backend",
        "environment": settings.environment,
        "database": db_health,
        "firebase": firebase_health,
        "aura_modules": aura_modules_health,
        "health_score": health_score
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.server_host,
        port=settings.port,
        reload=settings.environment != "production",
    )
