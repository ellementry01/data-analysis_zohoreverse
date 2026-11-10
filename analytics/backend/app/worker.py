"""Run the background job queue on its own (services/jobs.py): `python -m app.worker`.

The app already runs the queue every 30 seconds inside its scheduler. Use this when the work should move to a separate
process or container (set ENABLE_WORKER=false on the app then); several workers can run at once, each job runs once.
"""
import logging
import signal
import time

from .services import jobs

from .logsafe import install as _install_logging  # noqa: E402

_install_logging()  # no secrets or customer personal data in logs
_stop = False


def _halt(*_):
    global _stop
    _stop = True


def main(poll_seconds: float = 5.0) -> None:
    signal.signal(signal.SIGINT, _halt)
    signal.signal(signal.SIGTERM, _halt)
    logging.getLogger("worker").info("worker started")
    while not _stop:
        try:
            ran = jobs.run_pending()
        except Exception:  # noqa: BLE001
            logging.getLogger("worker").exception("job run failed")
            ran = 0
        if not ran:
            time.sleep(poll_seconds)


if __name__ == "__main__":
    main()
