/* Presentation adapter for saved AI requests; uses the existing chat typography and theme. */
(function () {
    'use strict';

    window.initAiRequestUi = function (options) {
        const box = options.chatBox;
        let latest = null;
        let retryTimer = null;
        const objectUrls = new Map();
        const editImages = new Map();
        const notice = document.createElement('div');
        notice.className = 'ai-request-notice';
        notice.hidden = true;
        const noticeText = document.createElement('span');
        noticeText.textContent = 'An earlier request is still processing.';
        const viewButton = document.createElement('button');
        viewButton.type = 'button';
        viewButton.textContent = 'View request';
        notice.append(noticeText, viewButton);
        const composer = box.closest('.ai-main-chat').querySelector('.ai-input-area');
        const media = composer.querySelector('.ai-composer-media');
        composer.before(notice);
        const editNotice = document.createElement('div');
        editNotice.className = 'ai-reference-preview';
        editNotice.hidden = true;
        const editThumbnail = document.createElement('div');
        editThumbnail.className = 'ai-composer-thumbnail';
        const editImage = document.createElement('img');
        editImage.className = 'ai-pending-photo-thumb';
        editImage.alt = 'Selected image to edit';
        const editLabel = document.createElement('span');
        editLabel.textContent = 'Editing the selected design';
        const cancelEdit = document.createElement('button');
        cancelEdit.type = 'button';
        cancelEdit.className = 'ai-pending-photo-remove';
        cancelEdit.setAttribute('aria-label', 'Cancel image edit');
        cancelEdit.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="m6 6 12 12M6 18 18 6"/></svg>';
        editThumbnail.append(editImage, cancelEdit);
        editNotice.append(editThumbnail, editLabel);
        media.appendChild(editNotice);
        const briefNotice = document.createElement('div');
        briefNotice.className = 'ai-guide-draft';
        briefNotice.hidden = true;
        const briefLabel = document.createElement('span');
        briefLabel.textContent = 'Design details saved for this chat.';
        const clearBrief = document.createElement('button');
        clearBrief.type = 'button';
        clearBrief.textContent = 'Clear saved details';
        briefNotice.append(briefLabel, clearBrief);
        document.querySelector('#ai-design-guide .ai-guide-body')?.appendChild(briefNotice);
        clearBrief.addEventListener('click', async () => {
            const id = options.getSessionId();
            if (!id) return;
            clearBrief.disabled = true;
            try {
                const response = await fetch(`/api/ai/sessions/${id}/brief/`, {
                    method: 'DELETE', headers: { 'X-CSRFToken': options.csrfToken }
                });
                if (!response.ok) throw new Error('clear failed');
                if (String(id) === String(options.getSessionId())) {
                    briefNotice.hidden = true;
                    clearEdit();
                }
            } catch (_) { briefLabel.textContent = 'Could not clear saved details. Please try again.'; }
            finally { clearBrief.disabled = false; }
        });
        function clearEdit() {
            editNotice.hidden = true;
            media.hidden = !media.querySelector('#ai-pending-photo-chip');
            box.querySelectorAll('.ai-design-actions button').forEach(button => button.setAttribute('aria-pressed', 'false'));
            options.onClearEdit();
        }
        function selectEdit(id, focus = true, detail = {}) {
            id = String(id);
            detail = { ...editImages.get(id), ...detail };
            options.onEdit(id, { ...detail, focus });
            editNotice.hidden = false;
            media.hidden = false;
            editLabel.textContent = detail.sourcePhotoId ? 'Editing this photo' : 'Editing this design';
            const url = safeImageUrl(detail.url);
            editImage.hidden = !url;
            if (url) editImage.src = url;
            box.querySelectorAll('.ai-design-actions button').forEach(button => {
                button.setAttribute('aria-pressed', String(button.dataset.imageId === id));
            });
        }
        cancelEdit.addEventListener('click', clearEdit);

        function sameSession(job) {
            return String(options.getSessionId() || '') === String(job.session_id || '');
        }

        function bubble(job, role, create = true) {
            let element = box.querySelector(`[data-ai-request="${job.id}"][data-ai-role="${role}"]`);
            const messageId = role === 'user' ? job.user_message_id : job.assistant_message_id;
            const saved = messageId ? box.querySelector(`[data-message-id="${messageId}"]`) : null;
            if (saved && saved !== element) {
                if (element) element.remove();
                element = saved;
            }
            if (!element && create) {
                element = document.createElement('div');
                element.className = `ai-message-bubble ai-${role === 'user' ? 'user' : 'bot'}-msg ai-history-msg`;
                box.insertBefore(element, options.typingIndicator);
            }
            if (element) {
                element.dataset.aiRequest = job.id;
                element.dataset.aiRole = role;
                if (messageId) element.dataset.messageId = messageId;
            }
            return element;
        }

        function bindEditActions(element, images) {
            images?.forEach(image => editImages.set(String(image.id), { url: image.url }));
            if (!images?.length || element.querySelector('.ai-design-actions')) return;
            const actions = document.createElement('div');
            actions.className = 'ai-design-actions';
            images.forEach((image, index) => {
                const edit = document.createElement('button');
                edit.type = 'button';
                edit.dataset.imageId = image.id;
                edit.textContent = images.length > 1 ? `Edit option ${index + 1}` : 'Edit this design';
                edit.addEventListener('click', () => {
                    selectEdit(image.id);
                });
                edit.setAttribute('aria-pressed', 'false');
                actions.appendChild(edit);
            });
            let row = element.querySelector('.ai-feedback-row');
            if (!row) {
                row = document.createElement('div');
                row.className = 'ai-feedback-row';
                element.appendChild(row);
            }
            row.prepend(actions);
        }

        function safeImageUrl(value) {
            if (!value) return '';
            try {
                const url = new URL(value, location.origin);
                return ['http:', 'https:', 'blob:'].includes(url.protocol) ? url.href : '';
            } catch (_) { return ''; }
        }

        function renderUser(element, content, imageUrl, messageId) {
            element.replaceChildren();
            const url = safeImageUrl(imageUrl);
            element.classList.toggle('ai-has-photo', Boolean(url));
            if (url) {
                const photo = document.createElement('div');
                photo.className = 'ai-user-photo';
                const link = document.createElement('a');
                link.href = url;
                link.target = '_blank';
                link.rel = 'noopener';
                link.setAttribute('aria-label', 'View attached photo');
                const image = document.createElement('img');
                image.className = 'ai-user-photo-thumb';
                image.alt = 'Attached photo';
                image.src = url;
                link.appendChild(image);
                photo.appendChild(link);
                if (messageId) {
                    const edit = document.createElement('button');
                    edit.type = 'button';
                    edit.className = 'ai-edit-upload';
                    edit.textContent = 'Edit this photo';
                    edit.addEventListener('click', () => selectEdit(String(messageId), true, {
                        sourcePhotoId: messageId, url
                    }));
                    photo.appendChild(edit);
                }
                element.appendChild(photo);
            }
            if (content && !(url && content === 'Attached photo')) {
                const text = document.createElement('span');
                text.className = 'ai-user-text';
                text.textContent = content;
                element.appendChild(text);
            }
        }

        function bindGallery(element, cards) {
            if (!cards?.length || element.querySelector('.ai-gallery-results')) return;
            element.querySelector('.ai-copy-btn')?.closest('div')?.remove();
            const gallery = document.createElement('div');
            gallery.className = 'ai-gallery-results';
            cards.slice(0, 4).forEach(card => {
                let url;
                try { url = new URL(card.url, location.origin); } catch (_) { return; }
                if (!['http:', 'https:'].includes(url.protocol)) return;
                const figure = document.createElement('figure');
                const image = document.createElement('img');
                image.src = url.href;
                image.alt = card.caption || 'Actual Balloorina setup';
                image.loading = 'lazy';
                image.addEventListener('error', () => {
                    image.hidden = true;
                    const note = document.createElement('span');
                    note.textContent = 'This photo is unavailable.';
                    figure.prepend(note);
                }, { once: true });
                const label = document.createElement('small');
                label.textContent = 'Actual setup';
                const caption = document.createElement('figcaption');
                caption.textContent = card.caption || card.category || 'Gallery photo';
                figure.append(image, label, caption);
                gallery.appendChild(figure);
            });
            const link = document.createElement('a');
            link.href = options.galleryUrl || '/gallery/';
            link.className = 'ai-gallery-link';
            link.textContent = 'View gallery';
            element.append(gallery, link);
        }

        function addRetry(element, request, after = 0, retryAt = null) {
            const retry = document.createElement('button');
            retry.type = 'button';
            retry.className = 'ai-request-retry';
            const deadline = retryAt ? retryAt * 1000 : Date.now() + after * 1000;
            retry.dataset.retryAt = deadline;
            function updateLabel() {
                const seconds = Math.max(0, Math.ceil((deadline - Date.now()) / 1000));
                retry.disabled = client.busy || seconds > 0;
                retry.textContent = seconds ? `Try again in ${seconds}s` : 'Try again';
            }
            retry.addEventListener('click', () => {
                if (!retry.disabled) {
                    retry.disabled = true;
                    client.retry(request);
                }
            });
            element.appendChild(retry);
            updateLabel();
            clearInterval(retryTimer);
            if (deadline > Date.now()) {
                retryTimer = setInterval(() => {
                    updateLabel();
                    if (deadline <= Date.now()) clearInterval(retryTimer);
                }, 1000);
            }
        }

        function render(job, details = {}) {
            latest = job;
            notice.hidden = !(client.busy && !sameSession(job));
            if (!sameSession(job)) return;
            const shouldFollow = box.scrollHeight - box.scrollTop - box.clientHeight < 100;
            if (!job.retry_of) {
                const user = bubble(job, 'user');
                const imageUrl = job.input_image_url || objectUrls.get(job.id);
                if (!user.dataset.renderedInput || imageUrl !== user.dataset.imageUrl) {
                    renderUser(user, job.input_text, imageUrl, job.user_message_id);
                    user.dataset.renderedInput = '1';
                    user.dataset.imageUrl = imageUrl || '';
                }
            }
            const assistant = bubble(job, 'assistant');
            assistant.setAttribute('aria-busy', String(job.state === 'queued' || job.state === 'running'));
            if (job.state === 'succeeded' || job.state === 'failed') {
                if (assistant.dataset.finished !== job.id) {
                    options.finalize(assistant, job.result);
                    bindEditActions(assistant, job.result.images);
                    bindGallery(assistant, job.result.gallery);
                    briefNotice.hidden = !job.has_design_brief;
                    if (job.result.retry_available) addRetry(assistant, job, job.result.retry_after, job.result.retry_at);
                    assistant.dataset.finished = job.id;
                }
            } else if (job.partial_text) {
                if (assistant.dataset.partial !== job.partial_text) {
                    assistant.innerHTML = options.format(job.partial_text);
                    assistant.dataset.partial = job.partial_text;
                }
            } else {
                let status = assistant.querySelector('.ai-request-status');
                if (!status) {
                    assistant.replaceChildren();
                    status = document.createElement('span');
                    status.className = 'ai-request-status';
                    status.setAttribute('role', 'status');
                    status.setAttribute('aria-live', 'polite');
                    assistant.appendChild(status);
                }
                status.textContent = job.status || 'Waiting for the assistant…';
            }
            if (shouldFollow || details.optimistic) box.scrollTop = box.scrollHeight;
        }

        const client = new window.AiRequestClient({
            userId: options.userId, csrfToken: options.csrfToken,
            onBusy(value) {
                options.onBusy(value);
                if (!value) notice.hidden = true;
                box.querySelectorAll('.ai-request-retry').forEach(button => {
                    button.disabled = value || Number(button.dataset.retryAt || 0) > Date.now();
                });
            },
            onUpdate(job, details) {
                if (details?.file && !objectUrls.has(job.id)) objectUrls.set(job.id, URL.createObjectURL(details.file));
                if (job.input_image_url && objectUrls.has(job.id)) {
                    URL.revokeObjectURL(objectUrls.get(job.id));
                    objectUrls.delete(job.id);
                }
                render(job, details);
            },
            onAccepted(job) {
                const optimistic = bubble(job, 'assistant', false);
                if (optimistic || !options.getSessionId()) options.setSessionId(job.session_id);
                options.onAccepted?.(job);
                options.loadSessions();
            },
            onRecovered(record) {
                if (record.sessionId && !options.getSessionId()) options.setSessionId(record.sessionId);
                if (record.job) render(record.job);
                else {
                    noticeText.textContent = 'Reconnecting to your saved request…';
                    notice.hidden = false;
                    viewButton.hidden = !record.sessionId;
                }
            },
            onRejected(record, data) {
                const job = { id: record.id, session_id: record.sessionId, input_text: record.message };
                if (!sameSession(job)) return;
                const assistant = bubble(job, 'assistant');
                assistant.replaceChildren();
                const text = document.createElement('span');
                text.textContent = data.error || 'Your request could not be sent. Please try again.';
                assistant.appendChild(text);
                assistant.setAttribute('aria-busy', 'false');
                if (!data.active_request) addRetry(assistant, record, data.retry_after, record.retryAt ? record.retryAt/1000 : null);
                options.restoreMessage(record.message);
            },
            onConnection(message) {
                if (!latest || !sameSession(latest)) return;
                const assistant = bubble(latest, 'assistant');
                let status = assistant.querySelector('.ai-request-status');
                if (!status) { status = document.createElement('span'); status.className = 'ai-request-status'; assistant.appendChild(status); }
                status.textContent = message;
            },
            onFinished(job) { options.onFinished?.(job); }
        });

        viewButton.addEventListener('click', async () => {
            if (!latest?.session_id) return;
            options.setSessionId(latest.session_id);
            await options.loadHistory(latest.session_id);
            render(latest);
        });

        return {
            send: payload => client.send(payload),
            recover: () => client.recover(),
            attach() { if (latest) render(latest); },
            bindHistory(element, images, gallery) { bindEditActions(element, images); bindGallery(element, gallery); },
            renderUser,
            setHasBrief(value) { briefNotice.hidden = !value; },
            clearEdit,
            selectEdit,
            get busy() { return client.busy; }
        };
    };
})();
