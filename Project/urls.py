from django.contrib import admin
from django.urls import path, include, re_path
from django.conf import settings
from django.conf.urls.static import static
from django.views.static import serve
import os

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('app.urls'))
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
elif not os.getenv("CLOUDINARY_CLOUD_NAME"):
    # Production without Cloudinary: MEDIA_ROOT is the repo's committed media/
    # folder, but WhiteNoise only serves /static/, so every /media/... request
    # used to fall through to a 404 (broken gallery, review and booking images).
    # Serve it here as a fallback; once CLOUDINARY_CLOUD_NAME is set every
    # FileField.url points at Cloudinary and this route is simply never used.
    urlpatterns += [
        re_path(
            r"^media/(?P<path>.*)$",
            serve,
            {"document_root": settings.MEDIA_ROOT},
        ),
    ]



