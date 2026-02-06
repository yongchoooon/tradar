from __future__ import annotations

import json
import logging
import time

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.services.worker_registry import worker_registry
from app.services.worker_settings import get_worker_settings


logger = logging.getLogger(__name__)

router = APIRouter()


@router.websocket("/ws/worker")
async def worker_socket(websocket: WebSocket) -> None:
    await websocket.accept()
    worker_id = None
    try:
        raw = await websocket.receive_text()
        try:
            message = json.loads(raw)
        except json.JSONDecodeError:
            await websocket.close(code=1008)
            return

        if (message.get("type") or "").lower() != "register":
            await websocket.close(code=1008)
            return

        worker_id = str(message.get("worker_id") or "").strip()
        token = str(message.get("token") or "").strip()
        settings = get_worker_settings()

        if not worker_id or not token or token != settings.token:
            await websocket.close(code=1008)
            return

        if settings.allowlist and worker_id not in settings.allowlist:
            await websocket.close(code=1008)
            return

        await worker_registry.register(worker_id, websocket)
        await websocket.send_json({"type": "registered", "worker_id": worker_id})

        while True:
            payload = await websocket.receive_text()
            try:
                data = json.loads(payload)
            except json.JSONDecodeError:
                continue

            msg_type = (data.get("type") or "").lower()
            if msg_type == "ping":
                await websocket.send_json({"type": "pong", "ts": time.time()})
                continue

            await worker_registry.handle_message(worker_id, data)
    except WebSocketDisconnect:
        pass
    except Exception as exc:  # pragma: no cover - safety net
        logger.warning("Worker socket error worker_id=%s err=%s", worker_id, exc)
    finally:
        if worker_id:
            await worker_registry.unregister(worker_id)
