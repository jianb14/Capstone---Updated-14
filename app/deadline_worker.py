"""Minute-based deadline processing while the development or production server runs."""
import atexit
import logging
import threading

from django.db import close_old_connections, connections

logger = logging.getLogger(__name__)
_thread = None
_guard = threading.Lock()
_stop = threading.Event()


def start_deadline_worker():
    global _thread
    with _guard:
        if _thread is not None and _thread.is_alive():
            return
        _stop.clear()
        def run():
            from .booking_lifecycle import process_booking_deadlines
            from .signup_lifecycle import process_signup_cleanup
            while not _stop.is_set():
                try:
                    close_old_connections()
                    process_booking_deadlines()
                except Exception:
                    logger.exception('Booking deadline worker failed; retrying in one minute')
                finally:
                    connections.close_all()
                try:
                    close_old_connections()
                    process_signup_cleanup()
                except Exception:
                    logger.exception('Pending signup cleanup failed; retrying on a later interval')
                finally:
                    connections.close_all()
                _stop.wait(60)
        _thread = threading.Thread(target=run, name='booking-deadlines', daemon=True)
        _thread.start()
        atexit.register(_stop.set)
