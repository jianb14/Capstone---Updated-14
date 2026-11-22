# Improve Cutout Quality

**User intent:** Improve automatic transparency quality after initial background-removal implementation.

**Evidence:** Existing u2netp predicts at320px; installed rembg DisSession uses1024px. Benchmarked isnet-general-use with the same public plant image; inference5.05s, session creation1.41s. Visually retained more foreground detail. Both remain estimates, so Use original stays available.

- [x] Add failing real-model selection and soft-mask cleanup tests.
- [x] Replace default session/preparation with the verified detailed model; keep CPU concurrency/cache and size bounds.
- [x] Clean only near-transparent/near-opaque mask values, retaining soft edges. Existing alpha is unchanged.
- [x] Prepare model, run real endpoint and upload/browser regressions; update deployment documentation and review.

**Scope:** Newly selected opaque asset images only. Saved images, existing transparent images, color metadata, upgrade logic and Background uploads remain unchanged. No alpha matting dependency or new user setting.

**Verification:** RED reproduced old u2netp selection and missing cleanup. GREEN:14 targeted tests passed in112.313 seconds, including the actual detailed-model endpoint, alpha preservation, resource/size/error bounds, upload preview/original/retry/cancel, upgrade and save/reopen/mobile browser cases. Three JS behavior scripts, Django checks and diff whitespace checks passed. Fresh read-only review found no issues. Model preparation succeeded locally; no new dependencies or migrations.

**Artifacts:** `.booking-followup-check/transparency-quality-comparison.png` compares the same public sample before/after on a checkerboard. Improved sample retains more foreground detail but remains an estimate. The detailed model is179MB and uses more cached memory per worker; observed inference5.05 seconds. No full-system suite was repeated.
