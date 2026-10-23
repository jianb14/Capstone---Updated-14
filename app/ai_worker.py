"""Small database-coordinated worker; durable jobs survive HTTP disconnects."""
import atexit
import logging
import threading
from datetime import timedelta

from django.conf import settings
from django.db import close_old_connections, connections
from django.utils import timezone

logger = logging.getLogger(__name__)
_guard = threading.Lock()
_stop = threading.Event()
_thread = None


def run_once(*, heartbeat=True):
    from .ai_jobs import claim_request, execute_request, expire_interrupted_requests
    from .models import AiRequest
    expire_interrupted_requests()
    claimed = claim_request()
    if not claimed:
        return False
    job_id, token = claimed
    finished = threading.Event()

    def renew():
        while not finished.wait(10):
            try:
                close_old_connections()
                updated = AiRequest.objects.filter(pk=job_id, state='running', lease_token=token).update(
                    lease_expires_at=timezone.now() + timedelta(seconds=max(30, settings.AI_JOB_LEASE_SECONDS)))
                if not updated:
                    return
            except Exception:
                logger.exception('Could not renew AI request lease: %s', job_id)
            finally:
                connections.close_all()

    lease_thread = threading.Thread(target=renew, name='ai-lease', daemon=True) if heartbeat else None
    if lease_thread:
        lease_thread.start()
    try:
        execute_request(job_id, token)
    finally:
        finished.set()
        if lease_thread:
            lease_thread.join(timeout=2)
    return True


def worker_loop(stop):
    while not stop.is_set():
        try:
            close_old_connections()
            worked = run_once()
        except Exception:
            logger.exception('AI worker could not process a request; retrying shortly')
            worked = False
        finally:
            connections.close_all()
        if not worked:
            stop.wait(1)


def start_ai_worker():
    global _thread
    if not settings.AI_WORKER_AUTOSTART:
        return
    with _guard:
        if _thread and _thread.is_alive():
            return
        _stop.clear()
        _thread = threading.Thread(target=worker_loop, args=(_stop,), name='ai-worker', daemon=True)
        _thread.start()
        atexit.register(_stop.set)
