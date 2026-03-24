
import asyncio
import json
import logging
import socket
import time
from typing import Optional, Set, Dict, Any, List
from aiohttp import web
import aiohttp
from app.services.camera import camera_service
from app.services.face_recognition import identify_person, detect_and_crop_faces
from app.services.speech import transcribe_audio
from app.services.conversation import analyze_conversation, streaming_chat
from app.services.microphone import mic_service
from app.services.discovery import _get_local_ip
from app.services.backend_client import get_backend_client
from app.core.config import settings
from app.core.pairing_store import normalize_backend_url, save_pairing_config

logger = logging.getLogger(__name__)


_connected_clients: Set[web.WebSocketResponse] = set()
_client_last_activity: Dict[web.WebSocketResponse, float] = {}


_session_auth: Dict[web.WebSocketResponse, Dict[str, Any]] = {}


_shutting_down = False
_active_video_streams: Set[web.StreamResponse] = set()
_latest_transcript: Dict[str, Any] = {
    "text": "",
    "timestamp": None,
    "analysis": {},
}

_streaming_service = None

_conversation_history: Dict[str, List[Dict[str, str]]] = {}

_auto_face_recognition_enabled = False
_auto_face_recognition_task: Optional[asyncio.Task] = None
_last_known_people: Dict[str, Dict[str, Any]] = {}
_auto_face_candidate_hits: Dict[str, int] = {}
_last_face_broadcast: Dict[str, float] = {}
_last_detection_time: float = 0
_last_auth_token: str = ""
_last_patient_uid: str = ""


CONNECTION_TIMEOUT = settings.websocket_timeout

PING_INTERVAL = 30.0


#------This Function checks if auto face recognition should run----------
def _should_run_auto_recognition() -> bool:
    return (
        _auto_face_recognition_enabled 
        and not _shutting_down 
        and camera_service.is_running
    )


#------This Function runs the background auto face recognition----------
async def _run_auto_face_recognition():
    global _last_detection_time, _last_auth_token, _last_patient_uid
    
    logger.info("[AUTO-FACE] Background task started")
    
    while not _shutting_down:
        try:
            await asyncio.sleep(settings.auto_face_recognition_interval)
            
            if not _should_run_auto_recognition():
                continue
            
            if not _connected_clients:
                logger.debug("[AUTO-FACE] No clients connected, skipping detection")
                continue
            
            current_time = time.time()
            if current_time - _last_detection_time < settings.auto_face_recognition_interval:
                continue
            
            auth_info = None
            for ws in _connected_clients:
                auth = _session_auth.get(ws)
                if auth and auth.get("auth_token") and auth.get("patient_uid"):
                    auth_info = auth
                    break
            
            if not auth_info:
                continue
            
            patient_uid = auth_info.get("patient_uid", "")
            auth_token = auth_info.get("auth_token", "")
            
            _last_auth_token = auth_token
            _last_patient_uid = patient_uid
            
            frame = camera_service.get_frame()
            if frame is None:
                logger.debug("[AUTO-FACE] No frame available")
                continue
            
            try:
                results = await identify_person(frame, patient_uid, auth_token)
            except Exception as e:
                logger.error(f"[AUTO-FACE] Identification error: {e}")
                continue
            
            if not results:
                continue
            
            known_keys_in_frame = set()
            for person in results:
                if person.get("name") and person.get("name") != "unknown":
                    person_name = person.get("name", "")
                    person_id = person.get("person_id", "")
                    confidence = float(person.get("confidence", 0.0))
                    person_key = f"{person_id}:{person_name}"
                    known_keys_in_frame.add(person_key)

                    hit_count = _auto_face_candidate_hits.get(person_key, 0) + 1
                    _auto_face_candidate_hits[person_key] = hit_count

                    _last_known_people[person_name] = {
                        "name": person_name,
                        "relationship": person.get("relationship", ""),
                        "confidence": confidence,
                        "last_seen": current_time,
                        "person_id": person_id,
                        "match_margin": person.get("match_margin", 0.0),
                        "hit_count": hit_count,
                    }

                    broadcast_ready = hit_count >= settings.auto_face_confirmation_count
                    last_broadcast_at = _last_face_broadcast.get(person_key, 0.0)
                    cooldown_ok = (
                        current_time - last_broadcast_at
                        >= settings.auto_face_broadcast_cooldown_seconds
                    )
                    if broadcast_ready and cooldown_ok:
                        notification = {
                            "type": "face_detected",
                            "person": {
                                "name": person_name,
                                "relationship": person.get("relationship", ""),
                                "confidence": confidence,
                                "match_margin": person.get("match_margin", 0.0),
                            },
                            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(current_time)),
                        }

                        await broadcast(notification)
                        _last_face_broadcast[person_key] = current_time
                        logger.info(
                            "[AUTO-FACE] Broadcast: %s identified "
                            "(confidence=%.3f hits=%s)",
                            person_name,
                            confidence,
                            hit_count,
                        )

            stale_candidate_keys = [
                candidate_key for candidate_key in _auto_face_candidate_hits.keys()
                if candidate_key not in known_keys_in_frame
            ]
            for candidate_key in stale_candidate_keys:
                _auto_face_candidate_hits[candidate_key] = max(
                    0,
                    _auto_face_candidate_hits.get(candidate_key, 0) - 1,
                )
                if _auto_face_candidate_hits[candidate_key] == 0:
                    _auto_face_candidate_hits.pop(candidate_key, None)
            
            _last_detection_time = current_time
            
            if _last_known_people:
                visible_people = []
                for name, data in _last_known_people.items():
                    if (
                        current_time - data.get("last_seen", 0)
                        < settings.auto_face_presence_ttl_seconds
                    ):
                        visible_people.append(data)
                
                if visible_people:
                    status_update = {
                        "type": "visible_people",
                        "people": visible_people,
                        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(current_time)),
                    }
                    await broadcast(status_update)
                    
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"[AUTO-FACE] Background task error: {e}")
            await asyncio.sleep(5)
    
    logger.info("[AUTO-FACE] Background task stopped")


#------This Function starts the auto face recognition background task----------
async def _start_auto_face_recognition_task():
    global _auto_face_recognition_task
    
    if _auto_face_recognition_task is not None and not _auto_face_recognition_task.done():
        return
    
    _auto_face_recognition_task = asyncio.create_task(_run_auto_face_recognition())
    logger.info("[AUTO-FACE] Background task created")


#------This Function stops the auto face recognition background task----------
async def _stop_auto_face_recognition_task():
    global _auto_face_recognition_task
    
    if _auto_face_recognition_task is not None and not _auto_face_recognition_task.done():
        _auto_face_recognition_task.cancel()
        try:
            await _auto_face_recognition_task
        except asyncio.CancelledError:
            pass
        _auto_face_recognition_task = None
        _auto_face_candidate_hits.clear()
        _last_face_broadcast.clear()
        logger.info("[AUTO-FACE] Background task cancelled")


#------This Function validates WebSocket messages----------
def _validate_message(msg: dict) -> tuple[bool, Optional[str]]:
    if not isinstance(msg, dict):
        return False, "Message must be a JSON object"
    
    cmd = msg.get("command", "")
    if not cmd:
        return False, "Missing 'command' field"
    
    if not isinstance(cmd, str):
        return False, "'command' must be a string"
    
    if cmd == "connect":
        if "auth_token" not in msg:
            return False, "Missing 'auth_token' for connect command"
        if "patient_uid" in msg and not isinstance(msg.get("patient_uid"), str):
            return False, "'patient_uid' must be a string"
        if "backend_url" in msg and not isinstance(msg.get("backend_url"), str):
            return False, "'backend_url' must be a string"
    
    return True, None


#------This Function resolves patient UID from auth token----------
async def _resolve_patient_uid_from_token(auth_token: str, backend_url: str) -> str:
    token = (auth_token or "").strip()
    normalized_backend_url = normalize_backend_url(backend_url)
    if token.lower().startswith("bearer "):
        token = token[7:].strip()

    if not token or not normalized_backend_url:
        return ""

    timeout = aiohttp.ClientTimeout(total=8)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(
                f"{normalized_backend_url}/auth/me",
                headers={"Authorization": f"Bearer {token}"},
            ) as response:
                if response.status != 200:
                    logger.warning(
                        "[PAIRING] Failed to resolve patient UID from token: /auth/me returned %s",
                        response.status,
                    )
                    return ""
                payload = await response.json()
                resolved_uid = str(payload.get("firebase_uid", "")).strip()
                return resolved_uid
    except Exception as exc:
        logger.warning("[PAIRING] Token-based patient UID resolution failed: %s", exc)
        return ""


#------This Function applies pairing config from connected client----------
async def _apply_pairing_runtime_config(
    patient_uid: str,
    backend_url: str,
    backend_auth_token: str,
):
    try:
        backend_client = get_backend_client()
    except RuntimeError:
        logger.debug("[PAIRING] Backend client not initialized yet")
        return

    try:
        success = await backend_client.apply_pairing_config(
            patient_uid,
            backend_url,
            backend_auth_token,
        )
        if success:
            logger.info("[PAIRING] Runtime pairing config synced to backend client")
        else:
            logger.warning("[PAIRING] Runtime pairing config received but backend registration failed")
    except Exception as exc:
        logger.error("[PAIRING] Failed to apply runtime pairing config: %s", exc)


async def _cleanup_stale_connections():
    current_time = time.time()
    stale_clients = []
    
    for ws in list(_connected_clients):
        last_activity = _client_last_activity.get(ws, current_time)
        if current_time - last_activity > CONNECTION_TIMEOUT:
            stale_clients.append(ws)
    
    for ws in stale_clients:
        logger.warning(f"[WS] Closing stale connection (no activity for {CONNECTION_TIMEOUT}s)")
        try:
            await ws.close(code=aiohttp.WSCloseCode.GOING_AWAY, message=b"Connection timeout")
        except Exception:
            pass
        _connected_clients.discard(ws)
        _client_last_activity.pop(ws, None)
        _session_auth.pop(ws, None)


async def _ws_handler(request):
    ws = web.WebSocketResponse(
        heartbeat=PING_INTERVAL,
        timeout=CONNECTION_TIMEOUT,
    )
    await ws.prepare(request)
    
    _connected_clients.add(ws)
    _client_last_activity[ws] = time.time()
    _session_auth[ws] = {}

    client_ip = request.remote
    logger.info("=" * 60)
    logger.info(f"[WS] CLIENT CONNECTED from {client_ip}")
    logger.info(f"[WS] Total connected clients: {len(_connected_clients)}")
    logger.info("=" * 60)

    try:
        async for raw_msg in ws:
            
            _client_last_activity[ws] = time.time()
            
            
            if _shutting_down:
                await ws.send_json(
                    {"type": "shutdown", "message": "Server shutting down"}
                )
                break

            if raw_msg.type == aiohttp.WSMsgType.TEXT:
                try:
                    msg = json.loads(raw_msg.data)
                except json.JSONDecodeError as e:
                    logger.warning(f"[WS] Invalid JSON received: {e}")
                    await ws.send_json({
                        "type": "error",
                        "error": "invalid_json",
                        "message": "Message must be valid JSON"
                    })
                    continue
                
                
                is_valid, error_msg = _validate_message(msg)
                if not is_valid:
                    logger.warning(f"[WS] Message validation failed: {error_msg}")
                    await ws.send_json({
                        "type": "error",
                        "error": "validation_error",
                        "message": error_msg
                    })
                    continue
                
                cmd = msg.get("command", "")

                if cmd == "connect":
                    
                    token = str(msg.get("auth_token", "")).strip()
                    patient = str(msg.get("patient_uid", "")).strip()
                    incoming_backend_url = msg.get("backend_url", "")
                    normalized_backend_url = normalize_backend_url(incoming_backend_url)
                    if token.lower().startswith("bearer "):
                        token = token[7:].strip()
                    
                    if not token or len(token) < 10:
                        logger.warning("[WS] Invalid auth token rejected")
                        await ws.send_json({
                            "type": "connected", 
                            "status": "error", 
                            "error": "invalid_token"
                        })
                        continue

                    existing_backend_url = normalize_backend_url(settings.backend_url or "")
                    pairing_backend_url = normalized_backend_url or existing_backend_url or ""
                    pairing_sync_started = False

                    if not patient and pairing_backend_url:
                        patient = await _resolve_patient_uid_from_token(token, pairing_backend_url)
                        if patient:
                            logger.info("[PAIRING] Resolved patient_uid from auth token")

                    if not patient:
                        logger.warning("[WS] Missing patient_uid and token resolution failed")
                        await ws.send_json({
                            "type": "connected",
                            "status": "error",
                            "error": "missing_patient_uid",
                        })
                        continue

                    
                    _session_auth[ws] = {
                        "patient_uid": patient,
                        "auth_token": token,
                        "mic_authorized": False,
                    }
                    settings.patient_uid = patient
                    settings.backend_auth_token = token

                    if pairing_backend_url:
                        settings.backend_url = pairing_backend_url
                        save_pairing_config(patient, pairing_backend_url, token)
                        pairing_sync_started = True
                        asyncio.create_task(
                            _apply_pairing_runtime_config(patient, pairing_backend_url, token)
                        )

                    logger.info(f"[WS] Client authenticated: patient_uid={patient[:8]}...")
                    if normalized_backend_url:
                        logger.info("[PAIRING] Received backend_url from paired client: %s", normalized_backend_url)
                    elif incoming_backend_url:
                        logger.warning("[PAIRING] Ignoring invalid backend_url from paired client: %s", incoming_backend_url)
                    elif pairing_backend_url:
                        logger.info("[PAIRING] Using existing backend_url: %s", pairing_backend_url)
                    
                    if settings.auto_face_recognition_enabled and len(_connected_clients) == 1:
                        _auto_face_recognition_enabled = True
                        await _start_auto_face_recognition_task()
                        logger.info("[AUTO-FACE] Started on first client connection")
                    
                    await ws.send_json(
                        {
                            "type": "connected",
                            "status": "ok",
                            "pairing_config_applied": pairing_sync_started,
                            "backend_url": pairing_backend_url,
                            "patient_uid": patient,
                        }
                    )

                elif cmd == "identify":
                    
                    auth = _session_auth.get(ws, {})
                    if not auth:
                        await ws.send_json({
                            "type": "identify_result",
                            "error": "not_authenticated"
                        })
                        continue
                    
                    frame = camera_service.get_frame()
                    if frame is None:
                        await ws.send_json(
                            {"type": "identify_result", "error": "no_frame"}
                        )
                        continue
                    
                    try:
                        results = await identify_person(
                            frame, auth.get("patient_uid", ""), auth.get("auth_token", "")
                        )
                        mic_started = any(
                            person.get("name") not in (None, "", "unknown")
                            for person in results
                        )
                        auth["mic_authorized"] = mic_started
                        if mic_started:
                            mic_service.start()
                        await ws.send_json(
                            {
                                "type": "identify_result",
                                "faces": results,
                                "mic_started": mic_started,
                            }
                        )
                    except Exception as e:
                        logger.error(f"[WS] Face identification error: {e}")
                        await ws.send_json({
                            "type": "identify_result",
                            "error": "identification_failed",
                            "message": str(e)
                        })

                elif cmd == "start_listening":
                    auth = _session_auth.get(ws, {})
                    if not auth.get("mic_authorized"):
                        await ws.send_json({
                            "type": "listening",
                            "status": "denied",
                            "error": "face_not_recognized",
                        })
                        continue
                    mic_service.start()
                    await ws.send_json({"type": "listening", "status": "started"})

                elif cmd == "stop_listening":
                    mic_service.stop()
                    await ws.send_json({"type": "listening", "status": "stopped"})

                elif cmd == "get_transcript":
                    
                    auth = _session_auth.get(ws, {})
                    if not auth:
                        await ws.send_json({
                            "type": "transcript",
                            "error": "not_authenticated"
                        })
                        continue
                    
                    chunk = mic_service.get_latest_chunk()
                    if chunk:
                        try:
                            
                            transcript = await transcribe_audio(chunk)
                            if transcript:
                                analysis = await analyze_conversation(
                                    transcript,
                                    [],  
                                    auth.get("patient_uid", ""),
                                    auth.get("auth_token", ""),
                                )
                                _latest_transcript["text"] = transcript
                                _latest_transcript["timestamp"] = time.time()
                                _latest_transcript["analysis"] = analysis or {}
                                await ws.send_json(
                                    {
                                        "type": "transcript",
                                        "text": transcript,
                                        "speakers": [],
                                        "analysis": analysis,
                                    }
                                )
                            else:
                                await ws.send_json(
                                    {"type": "transcript", "text": "", "speakers": []}
                                )
                        except Exception as e:
                            logger.error(f"[WS] Transcription error: {e}")
                            await ws.send_json({
                                "type": "transcript",
                                "error": "transcription_failed",
                                "message": str(e)
                            })
                    else:
                        await ws.send_json({"type": "transcript", "text": ""})

                elif cmd == "status":
                    await ws.send_json(
                        {
                            "type": "status",
                            "camera": camera_service.is_running,
                            "mic": mic_service.is_running,
                            "authenticated": bool(_session_auth.get(ws)),
                        }
                    )

                elif cmd == "ping":
                    await ws.send_json({"type": "pong"})

                elif cmd == "auto_face_recognition":
                    action = msg.get("action", "")
                    
                    if action == "start":
                        _auto_face_recognition_enabled = True
                        await _start_auto_face_recognition_task()
                        await ws.send_json({
                            "type": "auto_face_recognition",
                            "status": "started",
                            "interval": settings.auto_face_recognition_interval,
                        })
                    elif action == "stop":
                        _auto_face_recognition_enabled = False
                        await ws.send_json({
                            "type": "auto_face_recognition",
                            "status": "stopped",
                        })
                    elif action == "status":
                        await ws.send_json({
                            "type": "auto_face_recognition",
                            "enabled": _auto_face_recognition_enabled,
                            "interval": settings.auto_face_recognition_interval,
                            "last_detection": _last_detection_time,
                            "known_people": list(_last_known_people.values()),
                        })
                    else:
                        await ws.send_json({
                            "type": "error",
                            "error": "invalid_action",
                            "message": "action must be 'start', 'stop', or 'status'"
                        })

                elif cmd == "get_known_people":
                    current_time = time.time()
                    recent_people = {
                        name: data for name, data in _last_known_people.items()
                        if current_time - data.get("last_seen", 0) < 300
                    }
                    await ws.send_json({
                        "type": "known_people",
                        "people": list(recent_people.values()),
                        "count": len(recent_people),
                    })

                elif cmd == "streaming_chat":
                    auth = _session_auth.get(ws, {})
                    if not auth:
                        await ws.send_json({
                            "type": "streaming_chat",
                            "error": "not_authenticated"
                        })
                        continue
                    
                    message = msg.get("message", "")
                    enable_tools = msg.get("enable_tools", False)
                    clear_history = msg.get("clear_history", False)
                    
                    if not message:
                        await ws.send_json({
                            "type": "streaming_chat",
                            "error": "empty_message"
                        })
                        continue
                    
                    patient_uid = auth.get("patient_uid", "")
                    
                    if clear_history:
                        _conversation_history[patient_uid] = []
                    
                    history = _conversation_history.get(patient_uid, [])
                    full_response = ""

                    async def _send_token(token: str):
                        try:
                            await ws.send_json({
                                "type": "streaming_token",
                                "content": token,
                            })
                        except Exception:
                            pass

                    def on_token(token: str):
                        nonlocal full_response
                        full_response += token
                        asyncio.create_task(_send_token(token))

                    try:
                        backend_client = get_backend_client()
                        result = await backend_client.chat_with_orito(
                            user_message=message,
                            conversation_history=history,
                            on_token=on_token,
                            stream=True,
                        )
                    except RuntimeError:
                        result = await streaming_chat(
                            user_message=message,
                            conversation_history=history,
                            enable_tools=enable_tools,
                            on_token=on_token,
                        )

                    if result.get("success"):
                        history.append({"role": "user", "content": message})
                        history.append({"role": "assistant", "content": result.get("content", "")})
                        _conversation_history[patient_uid] = history[-20:]

                        await ws.send_json({
                            "type": "streaming_chat_done",
                            "content": result.get("content", ""),
                        })
                    else:
                        await ws.send_json({
                            "type": "streaming_chat_error",
                            "error": result.get("error", "Unknown error"),
                        })

                elif cmd == "get_conversation_history":
                    auth = _session_auth.get(ws, {})
                    if not auth:
                        await ws.send_json({
                            "type": "conversation_history",
                            "error": "not_authenticated"
                        })
                        continue
                    
                    patient_uid = auth.get("patient_uid", "")
                    history = _conversation_history.get(patient_uid, [])
                    await ws.send_json({
                        "type": "conversation_history",
                        "history": history,
                        "count": len(history),
                    })

                elif cmd == "clear_conversation_history":
                    auth = _session_auth.get(ws, {})
                    if not auth:
                        await ws.send_json({
                            "type": "conversation_history_cleared",
                            "error": "not_authenticated"
                        })
                        continue
                    
                    patient_uid = auth.get("patient_uid", "")
                    _conversation_history[patient_uid] = []
                    await ws.send_json({
                        "type": "conversation_history_cleared",
                    })

                elif cmd == "live_transcription_start":
                    auth = _session_auth.get(ws, {})
                    if not auth.get("mic_authorized"):
                        await ws.send_json({
                            "type": "live_transcription",
                            "status": "denied",
                            "error": "face_not_recognized",
                        })
                        continue
                    
                    mic_service.start()
                    await ws.send_json({
                        "type": "live_transcription",
                        "status": "started",
                    })

                elif cmd == "live_transcription_stop":
                    mic_service.stop()
                    await ws.send_json({
                        "type": "live_transcription",
                        "status": "stopped",
                    })

                else:
                    logger.warning(f"[WS] Unknown command: {cmd}")
                    await ws.send_json({
                        "type": "error",
                        "error": "unknown_command",
                        "command": cmd
                    })

            elif raw_msg.type == aiohttp.WSMsgType.PING:
                
                await ws.pong()
                
            elif raw_msg.type == aiohttp.WSMsgType.PONG:
                
                pass
                
            elif raw_msg.type in (aiohttp.WSMsgType.ERROR, aiohttp.WSMsgType.CLOSE):
                logger.warning(f"[WS] Connection error/close from {client_ip}: {raw_msg}")
                break
                
    except asyncio.CancelledError:
        logger.info(f"[WS] Connection cancelled for {client_ip}")
    except Exception as e:
        logger.error(f"[WS] Unexpected error for {client_ip}: {e}")
    finally:
        _connected_clients.discard(ws)
        _client_last_activity.pop(ws, None)
        _session_auth.pop(ws, None)
        
        if not _connected_clients and _auto_face_recognition_enabled:
            await _stop_auto_face_recognition_task()
            logger.info("[AUTO-FACE] Stopped - no clients remaining")
        
        logger.info("=" * 60)
        logger.info(f"[WS] CLIENT DISCONNECTED from {client_ip}")
        logger.info(f"[WS] Total connected clients: {len(_connected_clients)}")
        logger.info("=" * 60)

    return ws


async def broadcast(message: dict):
    if _connected_clients:
        payload = json.dumps(message)
        stale_clients = []
        for ws in list(_connected_clients):
            try:
                await ws.send_str(payload)
            except Exception as e:
                logger.warning(f"[WS] Failed to broadcast to client: {e}")
                stale_clients.append(ws)
        
        
        for ws in stale_clients:
            _connected_clients.discard(ws)
            _client_last_activity.pop(ws, None)
            _session_auth.pop(ws, None)






async def _health_handler(request):
    local_ip = _get_local_ip()
    return web.json_response(
        {
            "service": "AURA_MODULE",
            "status": "alive",
            "ip": local_ip,
            "hostname": socket.gethostname(),
            "ws_port": settings.ws_port,
            "http_port": settings.http_port,
            "version": "1.0.0",
            "camera": camera_service.is_running,
            "mic": mic_service.is_running,
            "connected_clients": len(_connected_clients),
            "streaming_enabled": settings.ollama_streaming,
            "vad_enabled": settings.enable_vad,
            "llm_model": settings.ollama_model,
        }
    )


async def _status_handler(request):
    camera_info = camera_service.get_camera_info()

    return web.json_response(
        {
            "service": "AURA_MODULE",
            "version": "1.0.0",
            "camera": {
                "running": camera_service.is_running,
                "resolution": camera_info.get("resolution", "unknown"),
                "fps": camera_info.get("current_fps", 0),
                "backend": camera_info.get("backend", "unknown"),
                "format": camera_info.get("format", "unknown"),
            },
            "microphone": {"running": mic_service.is_running},
            "connected_clients": len(_connected_clients),
            "models": {
                "face_recognition": "buffalo_l",
                "speech": settings.whisper_model,
                "whisper_size": settings.whisper_model_size,
                "llm": settings.ollama_model,
            },
            "streaming": {
                "enabled": settings.ollama_streaming,
                "vad_enabled": settings.enable_vad,
                "buffer_seconds": settings.audio_buffer_seconds,
            },
            "backend_url": settings.backend_url,
        }
    )


async def _extract_face_handler(request):
    try:
        data = await request.json()
        image_b64 = data.get("image_b64", "")

        if not image_b64:
            return web.json_response({"error": "missing_image"}, status=400)

        import base64
        import cv2
        import numpy as np

        try:
            img_bytes = base64.b64decode(image_b64)
        except Exception:
            return web.json_response({"error": "invalid_base64"}, status=400)
        
        nparr = np.frombuffer(img_bytes, np.uint8)
        frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

        if frame is None:
            return web.json_response({"error": "invalid_image"}, status=400)

        try:
            faces = detect_and_crop_faces(frame)
        except Exception as e:
            logger.error(f"[API] Face detection error: {e}")
            return web.json_response({"error": "face_detection_failed"}, status=500)

        if not faces:
            return web.json_response({"error": "no_faces_detected"}, status=404)

        embeddings = [face["embedding"].tolist() for face in faces]

        return web.json_response(
            {"embeddings": embeddings, "faces_detected": len(embeddings)}
        )

    except json.JSONDecodeError:
        return web.json_response({"error": "invalid_json"}, status=400)
    except Exception as e:
        logger.error(f"[API] Extract face error: {e}")
        return web.json_response({"error": "internal_error"}, status=500)


async def _identify_person_handler(request):
    logger.info("[API] POST /identify_person - Face Recognition Request")

    try:
        data = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"success": False, "error": "invalid_json"}, status=400)
    
    patient_uid = data.get("patient_uid", "")
    image_b64 = data.get("image_base64", "")
    auth_token = data.get("auth_token", "")
    if isinstance(auth_token, str) and auth_token.lower().startswith("bearer "):
        auth_token = auth_token[7:].strip()

    logger.debug(f"[API] Patient UID: {patient_uid}")

    import base64
    import cv2
    import numpy as np

    frame = None
    
    
    if not image_b64:
        logger.debug("[API] No image provided - using local camera")
        frame = camera_service.get_frame()
        if frame is None:
            logger.warning("[API] Camera frame not available")
            return web.json_response(
                {"success": False, "error": "no_camera_frame"}, status=503
            )
        logger.debug(f"[API] Captured frame from camera: {frame.shape}")
    else:
        logger.debug("[API] Using provided base64 image")
        
        try:
            img_bytes = base64.b64decode(image_b64)
        except Exception:
            return web.json_response(
                {"success": False, "error": "invalid_base64"}, status=400
            )
        
        nparr = np.frombuffer(img_bytes, np.uint8)
        frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

        if frame is None:
            logger.warning("[API] Invalid image format")
            return web.json_response(
                {"success": False, "error": "invalid_image"}, status=400
            )
        logger.debug(f"[API] Decoded image: {frame.shape}")

    
    try:
        results = await identify_person(frame, patient_uid, auth_token)
    except Exception as e:
        logger.error(f"[API] Face identification error: {e}")
        return web.json_response(
            {"success": False, "error": "identification_failed", "message": str(e)}, 
            status=500
        )

    if not results:
        logger.info("[API] No faces detected or identified")
        return web.json_response(
            {
                "success": False,
                "error": "no_face_detected",
                "identified_faces": [],
            }
        )

    first_error = next((r.get("error") for r in results if r.get("error")), None)
    if first_error:
        return web.json_response(
            {
                "success": False,
                "error": "relatives_fetch_failed",
                "message": first_error,
                "identified_faces": results,
                "num_faces": len(results),
            },
            status=502,
        )

    
    identified_count = sum(1 for r in results if r.get("name") != "unknown")
    unknown_count = len(results) - identified_count
    logger.info(f"[API] Results: {identified_count} identified, {unknown_count} unknown")

    return web.json_response(
        {
            "success": True,
            "identified_faces": results,
            "num_faces": len(results),
        }
    )


async def _video_feed_handler(request):
    import cv2

    client_ip = request.remote
    logger.info("=" * 60)
    logger.info(f"[STREAM] VIDEO CLIENT CONNECTED from {client_ip}")
    logger.info(f"[STREAM] Starting MJPEG stream at ~30 FPS")
    logger.info(f"[STREAM] Camera running: {camera_service.is_running}")
    logger.info("=" * 60)

    response = web.StreamResponse(
        status=200,
        reason="OK",
        headers={
            "Content-Type": "multipart/x-mixed-replace; boundary=frame",
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type",
        },
    )
    await response.prepare(request)

    
    _active_video_streams.add(response)

    frame_count = 0
    try:
        no_frame_count = 0
        max_no_frame_wait = 100  

        while not _shutting_down:
            frame = camera_service.get_frame()
            if frame is None:
                no_frame_count += 1
                if no_frame_count == 1:
                    logger.warning("[STREAM] No frame available from camera (waiting...)")
                elif no_frame_count % 50 == 0:
                    logger.warning(f"[STREAM] Still waiting for frames... ({no_frame_count} attempts)")
                
                if no_frame_count >= max_no_frame_wait:
                    logger.error("[STREAM] Max wait time exceeded, closing stream")
                    break
                    
                await asyncio.sleep(0.1)
                continue

            if no_frame_count > 0:
                logger.info("[STREAM] Camera frames available again")
                no_frame_count = 0

            
            ret, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
            if not ret:
                logger.warning("[STREAM] Failed to encode frame as JPEG")
                continue

            frame_bytes = jpeg.tobytes()

            
            try:
                await response.write(
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n"
                    b"Content-Length: " + str(len(frame_bytes)).encode() + b"\r\n"
                    b"\r\n" + frame_bytes + b"\r\n"
                )
            except (
                ConnectionResetError,
                aiohttp.ClientConnectionResetError,
                BrokenPipeError,
            ):
                
                logger.info("=" * 60)
                logger.info(f"[STREAM] VIDEO CLIENT DISCONNECTED from {client_ip}")
                logger.info(f"[STREAM] Total frames streamed: {frame_count}")
                logger.info("=" * 60)
                break

            frame_count += 1
            if frame_count == 1:
                logger.info(f"[STREAM] First frame sent to {client_ip}")
            elif frame_count % 100 == 0:
                logger.debug(f"[STREAM] Streamed {frame_count} frames to {client_ip}")

            await asyncio.sleep(0.033)  

    except asyncio.CancelledError:
        logger.info("=" * 60)
        logger.info(f"[STREAM] VIDEO CLIENT DISCONNECTED from {client_ip} (cancelled)")
        logger.info(f"[STREAM] Total frames streamed: {frame_count}")
        logger.info("=" * 60)
    except Exception as e:
        
        if not isinstance(
            e,
            (ConnectionResetError, aiohttp.ClientConnectionResetError, BrokenPipeError),
        ):
            logger.error(f"[STREAM] Unexpected error streaming to {client_ip}: {e}")
            logger.error(f"[STREAM] Frames streamed before error: {frame_count}")
            import traceback
            traceback.print_exc()
    finally:
        
        _active_video_streams.discard(response)

        
        try:
            if not response._eof_sent:
                await response.write_eof()
        except Exception:
            pass  

    return response


async def _snapshot_handler(request):
    import cv2

    frame = camera_service.get_frame()
    if frame is None:
        return web.json_response({"error": "No frame available"}, status=503)

    
    ret, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
    if not ret:
        return web.json_response({"error": "Failed to encode frame"}, status=500)

    return web.Response(
        body=jpeg.tobytes(),
        status=200,
        content_type="image/jpeg",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
            "Access-Control-Allow-Origin": "*",
        },
    )


async def _latest_transcript_handler(request):
    return web.json_response(
        {
            "text": _latest_transcript.get("text", ""),
            "timestamp": _latest_transcript.get("timestamp"),
            "analysis": _latest_transcript.get("analysis") or {},
        }
    )


def create_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/health", _health_handler)
    app.router.add_get("/status", _status_handler)
    app.router.add_get("/latest_transcript", _latest_transcript_handler)
    app.router.add_get("/video_feed", _video_feed_handler)  
    app.router.add_get("/snapshot", _snapshot_handler)  
    app.router.add_post("/extract_face", _extract_face_handler)
    app.router.add_post("/identify_person", _identify_person_handler)
    app.router.add_get("/ws", _ws_handler)
    return app


async def start_server():
    app = create_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", settings.http_port)
    await site.start()
    logger.info(f"[AURA] Server running on 0.0.0.0:{settings.http_port}")
    logger.info(f"[AURA]   HTTP health: http://0.0.0.0:{settings.http_port}/health")
    logger.info(f"[AURA]   Video stream: http://0.0.0.0:{settings.http_port}/video_feed")
    logger.info(f"[AURA]   WebSocket:   ws://0.0.0.0:{settings.http_port}/ws")
    return runner


async def shutdown_streams():
    global _shutting_down

    logger.info("[AURA] Shutting down video streams...")
    _shutting_down = True
    
    await _stop_auto_face_recognition_task()
    
    await asyncio.sleep(2)

    
    for ws in list(_connected_clients):
        try:
            await ws.close(code=aiohttp.WSCloseCode.GOING_AWAY, message=b"Server shutting down")
        except Exception:
            pass
    _connected_clients.clear()
    _client_last_activity.clear()
    _session_auth.clear()

    
    for response in list(_active_video_streams):
        try:
            if not response._eof_sent:
                await response.write_eof()
        except Exception:
            pass

    _active_video_streams.clear()
    logger.info("[AURA] All streams closed")
