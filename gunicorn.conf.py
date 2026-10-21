def post_worker_init(worker):
    # Start after Gunicorn forks and Django initializes. Database row locks and
    # unique notices make multiple workers safe; no visitor is needed for expiry.
    from app.deadline_worker import start_deadline_worker
    start_deadline_worker()
