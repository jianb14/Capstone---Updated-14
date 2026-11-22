"""Local CPU cutouts for normalized asset previews; original images stay untouched."""
import io
import os
import math
from functools import lru_cache
from pathlib import Path
from threading import BoundedSemaphore

from django.conf import settings
from PIL import Image

_processing = BoundedSemaphore(1)
MODEL_NAME = 'isnet-general-use'


class BackgroundRemovalUnavailable(Exception):
    pass


def model_directory():
    return Path(os.environ.get('U2NET_HOME', settings.BASE_DIR / '.background_models'))


@lru_cache(maxsize=1)
def _session():
    if not (model_directory() / f'{MODEL_NAME}.onnx').is_file():
        raise BackgroundRemovalUnavailable('Background model has not been prepared.')
    os.environ.setdefault('U2NET_HOME', str(model_directory()))
    import onnxruntime as ort
    from rembg.sessions.dis_general_use import DisSession
    options = ort.SessionOptions()
    options.intra_op_num_threads = 2
    options.inter_op_num_threads = 1
    return DisSession(MODEL_NAME, options, providers=['CPUExecutionProvider'])


def _clean_mask(mask):
    # Clear faint residue and solidify confident foreground without hard-cutting edges.
    return mask.point([max(0, min(255, round((value - 8) * 255 / 237))) for value in range(256)])


def _remove(image):
    mask = _session().predict(image)[0]
    result = image.convert('RGBA')
    result.putalpha(_clean_mask(mask))
    return result


def remove_image_background(content):
    with Image.open(io.BytesIO(content)) as source:
        image = source.convert('RGBA')
    if image.getchannel('A').getextrema()[0] < 255:
        result = image
    else:
        if not _processing.acquire(blocking=False):
            raise BackgroundRemovalUnavailable('Another image is processing.')
        try:
            result = _remove(image).convert('RGBA')
            if result.size != image.size or result.getchannel('A').getbbox() is None:
                raise BackgroundRemovalUnavailable('No foreground could be retained.')
        except Exception as error:
            raise BackgroundRemovalUnavailable('Background removal is unavailable.') from error
        finally:
            _processing.release()
    output = io.BytesIO()
    result.save(output, format='PNG')
    # Transparent PNGs can be larger than their JPEG inputs; keep the save contract.
    limit = 10 * 1024**2
    while output.tell() > limit:
        ratio = min(0.9, math.sqrt(limit / output.tell()) * 0.95)
        result = result.resize((max(1, int(result.width * ratio)), max(1, int(result.height * ratio))), Image.Resampling.LANCZOS)
        output = io.BytesIO()
        result.save(output, format='PNG')
    return output.getvalue()
