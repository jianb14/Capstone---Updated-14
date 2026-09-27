"""app.views package -- split from the former single-file app/views.py.

Importing ``app.views`` exposes the same public API as before, so
``app/urls.py`` (``from .views import ...``) keeps working unchanged.
"""
from .common import *  # noqa: F401,F403
from .auth import *  # noqa: F401,F403
from .public import *  # noqa: F401,F403
from .profiles import *  # noqa: F401,F403
from .bookings import *  # noqa: F401,F403
from .payments import *  # noqa: F401,F403
from .chat import *  # noqa: F401,F403
from .designs import *  # noqa: F401,F403
from .notifications import *  # noqa: F401,F403
from .admin import *  # noqa: F401,F403

# Underscore names are skipped by ``import *`` -- re-export explicitly
# (app/context_processors.py imports _abandoned_paymongo_payment_query).
from .payments import _abandoned_paymongo_payment_query  # noqa: F401
