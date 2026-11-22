# Asset background removal

New uploads in canvas asset categories automatically request a cutout preview. The user can choose **Use original**, retry **Remove background**, cancel, or save the reviewed image. Balloon photos keep their per-photo color declarations. The Background tab and historical uploads are unchanged.

Processing runs locally with rembg's isnet-general-use CPU model. No uploaded photo is sent to an external service. Existing transparent images keep their alpha channel. Results use private PNG storage through the existing upload endpoint only after confirmation.

The detailed model uses a 1024-pixel working mask. Low-confidence near-transparent residue is cleared and confident foreground made opaque, with intermediate alpha retained for soft edges. It uses more memory than the original small model; the local benchmark took about five seconds for inference on a 987×1481 test photo. Actual timing varies by server and image. This affects newly selected opaque photos, not previously saved cutouts.

## Server preparation

Use Python 3.11–3.13 and install `requirements.txt`. Before starting the application on a new server, run:

```powershell
.venv/Scripts/python.exe manage.py prepare_background_remover
```

This downloads and verifies the roughly 179 MB isnet-general-use model. Default model directory: `.background_models/` under the project root (ignored by Git). Set `U2NET_HOME` to a persistent writable directory if needed; use the same directory for preparation and the web server. Each web worker caches one CPU session, using two inference threads. A worker processes one opaque image at a time; concurrent requests receive a retry/original choice. Deploy with enough memory for the CPU dependencies and cached session.

Requests accept JPEG/PNG/WebP up to 10 MB and 32 megapixels, then normalize to a maximum 2048-pixel dimension. Generated PNGs that exceed the existing 10 MB save limit are resized further with alpha retained; the preview displays that exact result. The preview endpoint creates no stored library item and returns `Cache-Control: private, no-store`. The client aborts preview requests on cancel and times out after 60 seconds; processing may finish server-side after an aborted request. A missing model or inference error leaves saving disabled until the user retries or explicitly chooses the original.

Cutouts are estimates: white/transparent balloons, thin ribbons and busy scenes can need the original image. Review the checkerboard preview. Existing library images are not retroactively processed. Color edits retain their existing immutable image revisions.

Reference implementation and model documentation: [rembg](https://github.com/danielgatis/rembg).
