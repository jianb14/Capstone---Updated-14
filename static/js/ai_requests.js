/* Durable AI requests: reconnect to the same UUID; never fall back to a new generation. */
(function () {
    'use strict';

    class AiRequestClient {
        constructor(options) {
            this.options = options;
            this.key = `balloorina-ai-pending:${options.userId}`;
            this.current = null;
            this.busy = false;
            this.timer = null;
            this.polling = false;
            window.addEventListener('online', () => this.schedule(0));
            document.addEventListener('visibilitychange', () => {
                if (!document.hidden && this.busy) this.schedule(0);
            });
        }

        async fileStore(action, id, file) {
            if (!window.indexedDB) return null;
            return new Promise(resolve => {
                let settled = false;
                const finish = value => { if (!settled) { settled = true; resolve(value); } };
                const request = indexedDB.open(`balloorina-ai-outbox:${this.options.userId}`, 1);
                request.onupgradeneeded = () => request.result.createObjectStore('files');
                request.onerror = () => finish(null);
                request.onblocked = () => finish(null);
                request.onsuccess = () => {
                    const db = request.result;
                    try {
                        const tx = db.transaction('files', action === 'get' ? 'readonly' : 'readwrite');
                        const store = tx.objectStore('files');
                        const operation = action === 'get' ? store.get(id) : action === 'put' ? store.put(file, id) : store.delete(id);
                        let result = null;
                        operation.onsuccess = () => { result = operation.result || null; };
                        tx.oncomplete = () => { db.close(); finish(result); };
                        tx.onerror = () => { db.close(); finish(null); };
                    } catch (_) { db.close(); finish(null); }
                };
                setTimeout(() => finish(null), 3000);
            });
        }

        remember(record) {
            this.current = record;
            try { localStorage.setItem(this.key, JSON.stringify(record)); } catch (_) { /* Server history still persists. */ }
        }

        setBusy(value) {
            this.busy = value;
            this.options.onBusy?.(value);
        }

        async fetchJson(url, options = {}) {
            const controller = new AbortController();
            const timeout = setTimeout(() => controller.abort(), options.method === 'POST' ? 20000 : 12000);
            try {
                const response = await fetch(url, { ...options, credentials: 'same-origin', signal: controller.signal });
                let data;
                try { data = await response.json(); }
                catch (_) {
                    data = { error: response.status === 403 ? 'Please refresh the page and sign in again.'
                        : 'The assistant could not respond. Please try again shortly.' };
                }
                return { response, data };
            } finally { clearTimeout(timeout); }
        }

        async send({ message = '', sessionId = null, file = null, referenceId = null, sourcePhotoId = null, intent = 'auto', retryOf = null } = {}) {
            if (this.busy) return false;
            const record = {
                id: crypto.randomUUID(), message, sessionId, referenceId, sourcePhotoId, intent, retryOf,
                hasFile: Boolean(file), fileName: file?.name || '', createdAt: Date.now(), phase: 'submitting'
            };
            this.remember(record);
            this.setBusy(true);
            if (file) await this.fileStore('put', record.id, file);
            this.options.onUpdate?.({ id: record.id, state: 'queued', stage: 'queued', status: 'Sending your request…',
                session_id: sessionId, input_text: message, retry_of: retryOf }, { optimistic: true, file });
            await this.submit(record, file);
            return true;
        }

        async submit(record, file = null) {
            if (this.current?.id !== record.id) return;
            const payload = { request_id: record.id, message: record.message, session_id: record.sessionId,
                intent: record.intent, reference_id: record.referenceId, source_photo_id: record.sourcePhotoId, retry_of: record.retryOf };
            let body, headers = { 'X-CSRFToken': this.options.csrfToken, 'Accept': 'application/json' };
            if (record.hasFile) {
                file = file || await this.fileStore('get', record.id);
                if (!file) {
                    this.reject(record, { error: 'Please attach your photo again. Your description is still available.' });
                    return;
                }
                body = new FormData();
                Object.entries(payload).forEach(([key, value]) => { if (value !== null && value !== undefined) body.append(key, value); });
                body.append('image', file, record.fileName || 'inspiration.png');
            } else {
                body = JSON.stringify(payload);
                headers['Content-Type'] = 'application/json';
            }
            try {
                const { response, data } = await this.fetchJson('/api/ai/requests/', { method: 'POST', headers, body });
                if (!response.ok) {
                    if (data.active_request) {
                        this.options.onRejected?.(record, data);
                        this.adopt(data.active_request);
                    } else {
                        this.reject(record, data);
                    }
                    return;
                }
                this.accept(data);
            } catch (_) {
                // The server may already have accepted the POST. Look up its UUID first.
                this.reconnecting();
                this.schedule(1500);
            }
        }

        reject(record, data) {
            record.phase = 'rejected';
            record.error = data.error || 'Your request could not be sent. Please try again.';
            record.retryAfter = Number(data.retry_after) || 0;
            record.retryAt = Date.now() + record.retryAfter * 1000;
            this.remember(record);
            this.setBusy(false);
            this.options.onRejected?.(record, data);
        }

        adopt(job) {
            const record = { id: job.id, message: job.input_text, sessionId: job.session_id,
                intent: 'auto', hasFile: Boolean(job.input_image_url), createdAt: Date.now(), phase: 'accepted' };
            this.remember(record);
            this.setBusy(true);
            this.accept(job);
        }

        accept(job) {
            if (!job?.id || this.current?.id !== job.id) return;
            const first = this.current.phase !== 'accepted';
            this.current.phase = 'accepted';
            this.current.sessionId = job.session_id;
            this.current.job = job;
            this.remember(this.current);
            if (first) this.options.onAccepted?.(job);
            this.options.onUpdate?.(job);
            if (job.state === 'succeeded' || job.state === 'failed') {
                const record = this.current;
                this.setBusy(false);
                clearTimeout(this.timer);
                try {
                    if (JSON.parse(localStorage.getItem(this.key) || 'null')?.id === job.id) localStorage.removeItem(this.key);
                } catch (_) { /* Storage is optional. */ }
                this.fileStore('delete', job.id);
                this.options.onFinished?.(job, record);
            } else {
                this.setBusy(true);
                this.schedule(document.hidden ? 4000 : 900);
            }
        }

        schedule(delay) {
            clearTimeout(this.timer);
            if (!this.current || !this.busy) return;
            this.timer = setTimeout(() => this.poll(), delay);
        }

        reconnecting() {
            this.options.onConnection?.('Your request is saved on this device. Reconnecting…');
        }

        async poll() {
            if (!this.current || !this.busy || this.polling) return;
            if (!navigator.onLine) { this.reconnecting(); this.schedule(2000); return; }
            this.polling = true;
            const record = this.current;
            try {
                const { response, data } = await this.fetchJson(`/api/ai/requests/${record.id}/`);
                if (this.current?.id !== record.id) return;
                if (response.ok) {
                    this.accept(data);
                } else if (response.status === 404 && record.phase === 'submitting') {
                    // Safe to send again: same UUID, same payload, no fallback generation.
                    await this.submit(record);
                } else if (response.status === 404 || response.status === 403) {
                    this.reject(record, data);
                } else {
                    this.reconnecting();
                    this.schedule(2500);
                }
            } catch (_) {
                this.reconnecting();
                this.schedule(2500);
            } finally { this.polling = false; }
        }

        async recover() {
            if (this.busy) return;
            let record = null;
            try { record = JSON.parse(localStorage.getItem(this.key) || 'null'); } catch (_) { /* optional */ }
            if (record?.id && /^[a-f0-9-]{36}$/i.test(record.id)) {
                this.current = record;
                if (record.phase === 'rejected') {
                    this.options.onRejected?.(record, { error: record.error, retry_after: Math.max(0, (record.retryAt-Date.now())/1000) });
                    return;
                }
                this.setBusy(true);
                this.options.onRecovered?.(record);
                await this.poll();
                return;
            }
            try {
                const { response, data } = await this.fetchJson('/api/ai/requests/active/');
                if (response.ok && data.request) {
                    this.options.onRecovered?.({ id: data.request.id, sessionId: data.request.session_id });
                    this.adopt(data.request);
                }
            } catch (_) { /* Opening chat again can recover an active server request. */ }
        }

        async retry(jobOrRecord) {
            if (this.busy) return;
            if (jobOrRecord.phase === 'rejected') {
                if (jobOrRecord.retryAt > Date.now()) return;
                this.remember({ ...jobOrRecord, phase: 'submitting' });
                this.setBusy(true);
                await this.submit(this.current);
            } else {
                await this.send({ retryOf: jobOrRecord.id, sessionId: jobOrRecord.session_id });
            }
        }
    }

    window.AiRequestClient = AiRequestClient;
})();
