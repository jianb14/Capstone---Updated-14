/* Shared support inbox and customer widget. AI assistant uses its own controller. */
(() => {
    'use strict';
    const svgNS = 'http://www.w3.org/2000/svg';
    function node(tag, cls, text) {
        const el = document.createElement(tag);
        if (cls) el.className = cls;
        if (text !== undefined) el.textContent = text;
        return el;
    }
    function icon(name) {
        const svg = document.createElementNS(svgNS, 'svg');
        svg.setAttribute('aria-hidden', 'true');
        const use = document.createElementNS(svgNS, 'use');
        use.setAttribute('href', '#sc-' + name); svg.append(use); return svg;
    }
    function button(label, cls, handler, symbol) {
        const b = node('button', cls, symbol ? undefined : label); b.type = 'button';
        if (symbol) { b.append(icon(symbol)); b.setAttribute('aria-label', label); b.title = label; }
        if (handler) b.addEventListener('click', handler);
        return b;
    }
    function empty(title, description, symbol = 'chat') {
        const wrap = node('div', 'sc-empty');
        const glyph = node('span', 'sc-empty-icon'); glyph.append(icon(symbol));
        wrap.append(glyph, node('h2', '', title), node('p', '', description)); return wrap;
    }

    class SupportChat {
        constructor(root) {
            this.root = root; this.admin = root.dataset.mode === 'admin';
            this.$ = selector => root.querySelector(selector);
            this.sessionId = Number(root.dataset.session) || null;
            this.messages = new Map(); this.drafts = new Map(); this.files = [];
            this.inboxRows = new Map(); this.inboxPage = 1; this.filter = 'all'; this.inboxVersion = 0;
            this.epoch = 0; this.loading = false; this.sending = false; this.open = this.admin;
            this.hasMore = false; this.reply = null; this.edit = null; this.retry = null; this.messageBusy = new Set();
            this.input = this.$('[data-input]'); this.history = this.$('[data-history]');
            this.list = this.$('[data-messages]'); this.dialog = this.$('[data-dialog]');
            this.form = this.$('[data-composer]'); this.threadQuery = '';
            this.bind(); this.sizeInput();
            if (this.admin) {
                this.loadInbox();
                if (this.sessionId) this.select(this.sessionId, false);
            } else {
                window.BalloorinaSupport = {open: () => this.toggle(true)};
                this.loadSummary();
                if (new URL(location.href).searchParams.get('support') === '1') this.toggle(true);
            }
            this.pollTimer = setTimeout(() => this.poll(), 4500);
        }
        async request(url, options = {}) {
            const controller = new AbortController();
            const timer = setTimeout(() => controller.abort(), 25000);
            try {
                const response = await fetch(url, {...options, signal: controller.signal,
                    credentials: 'same-origin', cache: 'no-store', headers: {
                        Accept: 'application/json', 'X-Requested-With': 'XMLHttpRequest',
                        'X-CSRFToken': this.root.dataset.csrf, ...options.headers}});
                const json = response.headers.get('content-type')?.includes('application/json');
                if (!json) throw new Error(response.status === 403 ? 'Your session has expired. Reload this page and sign in again.' : 'Support is unavailable right now. Please try again.');
                const data = await response.json();
                if (!response.ok || data.error) throw new Error(data.error || 'The request could not be completed. Please try again.');
                return data;
            } catch (error) {
                if (error.name === 'AbortError') throw new Error('The connection timed out. Your draft is kept. Try again.');
                if (error instanceof TypeError) throw new Error('Could not connect. Check your connection and try again.');
                throw error;
            } finally { clearTimeout(timer); }
        }
        async action(action, data = {}) {
            return this.request(this.root.dataset.actionUrl, {method: 'POST',
                headers: {'Content-Type': 'application/json'}, body: JSON.stringify({session_id: this.sessionId, action, ...data})});
        }
        setError(message = '') {
            const box = this.$('[data-error]'); box.textContent = message; box.hidden = !message;
            this.input.setAttribute('aria-invalid', message ? 'true' : 'false');
        }
        feedback(message) {
            if (window.AdminConfigurationFeedback) window.AdminConfigurationFeedback.show(message, 'success');
            else this.$('[data-send-status]').textContent = message;
        }
        bind() {
            this.form.addEventListener('submit', event => { event.preventDefault(); this.send(); });
            this.input.addEventListener('input', () => {
                this.setError(); this.retry = null; this.sizeInput(); this.saveDraft();
                if (!this.activityAt || Date.now() - this.activityAt > 3000) this.activity(true);
                clearTimeout(this.typingTimer); this.typingTimer = setTimeout(() => this.activity(false), 4000);
            });
            this.input.addEventListener('keydown', event => {
                if (event.key === 'Enter' && !event.shiftKey && !event.isComposing && matchMedia('(pointer:fine)').matches) {
                    event.preventDefault(); this.form.requestSubmit();
                }
            });
            this.$('[data-attach]').addEventListener('click', () => this.$('[data-file]').click());
            this.$('[data-file]').addEventListener('change', event => { this.addFiles(event.target.files); event.target.value = ''; });
            this.form.addEventListener('dragover', event => { event.preventDefault(); });
            this.form.addEventListener('drop', event => { event.preventDefault(); this.addFiles(event.dataTransfer.files); });
            this.input.addEventListener('paste', event => {
                const files = Array.from(event.clipboardData?.files || []);
                if (files.length) { event.preventDefault(); this.addFiles(files); }
            });
            this.$('[data-cancel-context]').addEventListener('click', () => this.cancelContext());
            this.$('[data-older]').addEventListener('click', () => this.loadState({older: true}));
            this.history.addEventListener('scroll', () => {
                if (this.atBottom()) { this.$('[data-jump-bottom]').hidden = true; this.activity(false); }
            }, {passive: true});
            this.$('[data-jump-bottom]').addEventListener('click', () => { this.bottom(true); this.activity(false); });
            this.$('[data-info]').addEventListener('click', () => this.showInfo());
            this.$('[data-pins]').addEventListener('click', () => this.showInfo());
            this.$('[data-dialog-close]').addEventListener('click', () => this.dialog.close());
            this.dialog.addEventListener('click', event => { if (event.target === this.dialog) { const r = this.dialog.getBoundingClientRect(); if (event.clientX < r.left || event.clientX > r.right || event.clientY < r.top || event.clientY > r.bottom) this.dialog.close(); } });
            this.dialog.addEventListener('close', () => {
                this.$('[data-dialog-body]').replaceChildren(); this.$('[data-dialog-footer]').replaceChildren();
                this.dialog.classList.remove('sc-image-dialog');
            });
            this.$('[data-toggle-search]').addEventListener('click', () => {
                const panel = this.$('[data-thread-search]'); panel.hidden = !panel.hidden;
                this.$('[data-toggle-search]').setAttribute('aria-expanded', String(!panel.hidden));
                if (!panel.hidden) this.$('[data-message-search]').focus();
                else this.searchMessages('');
            });
            this.$('[data-thread-search]').addEventListener('submit', event => {event.preventDefault(); this.searchMessages(this.$('[data-message-search]').value);});
            this.$('[data-message-search]').addEventListener('input', event => {
                clearTimeout(this.searchTimer); this.searchTimer = setTimeout(() => this.searchMessages(event.target.value), 280);
            });
            this.$('[data-clear-search]').addEventListener('click', () => { clearTimeout(this.searchTimer); this.searchMessages(''); this.$('[data-message-search]').focus(); });
            document.addEventListener('click', event => {
                if (!event.target.closest('.sc-message-actions')) this.root.querySelectorAll('.sc-message-menu').forEach(menu => menu.remove());
            });
            document.addEventListener('keydown', event => {
                if (event.key === 'Escape' && !this.dialog.open) {
                    const menus = this.root.querySelectorAll('.sc-message-menu');
                    if (menus.length) {
                        menus.forEach(menu => menu.remove()); event.preventDefault(); return;
                    }
                    if (!this.admin && this.open) this.toggle(false);
                }
            });
            document.addEventListener('visibilitychange', () => { if (!document.hidden) this.poll(true); });
            if (!this.admin) {
                this.$('#adminChatToggle').addEventListener('click', () => this.toggle(!this.open));
                this.$('[data-close]').addEventListener('click', () => this.toggle(false));
                document.addEventListener('open-admin-chat', () => this.toggle(true));
            } else {
                this.$('[data-expand-chat]').addEventListener('click', () => this.toggleFullscreen());
                const search = this.$('[data-inbox-search]');
                search.addEventListener('input', () => {
                    this.$('[data-clear-inbox]').hidden = !search.value;
                    clearTimeout(this.inboxSearchTimer); this.inboxVersion++;
                    this.inboxSearchTimer = setTimeout(() => this.loadInbox(), 280);
                });
                this.$('[data-clear-inbox]').addEventListener('click', () => {
                    clearTimeout(this.inboxSearchTimer); search.value = ''; this.$('[data-clear-inbox]').hidden = true; this.loadInbox(); search.focus();
                });
                this.root.querySelectorAll('[data-filter]').forEach(tab => tab.addEventListener('click', () => {
                    this.filter = tab.dataset.filter;
                    this.root.querySelectorAll('[data-filter]').forEach(el => el.setAttribute('aria-pressed', String(el === tab)));
                    this.loadInbox();
                }));
                this.$('[data-more-inbox]').addEventListener('click', () => this.loadInbox(true));
                this.$('[data-back]').addEventListener('click', () => this.select(null));
                window.addEventListener('popstate', () => {
                    const match = location.pathname.match(/\/chat\/(\d+)\/?$/);
                    this.select(match ? Number(match[1]) : null, false);
                });
            }
        }
        captureView() {
            const bounds = this.history.getBoundingClientRect();
            const row = this.history.clientHeight ? Array.from(this.list.querySelectorAll('[data-message]'))
                .find(message => message.getBoundingClientRect().bottom > bounds.top) : null;
            return {bottom: this.atBottom(), top: this.history.scrollTop,
                message: row?.dataset.message, offset: row ? row.getBoundingClientRect().top - bounds.top : 0,
                inboxTop: this.$('[data-inbox-list]').scrollTop};
        }
        restoreView(view) {
            this.sizeInput();
            const row = view.message && this.list.querySelector('[data-message="' + Number(view.message) + '"]');
            if (view.bottom) this.history.scrollTop = this.history.scrollHeight;
            else if (row) this.history.scrollTop += row.getBoundingClientRect().top - this.history.getBoundingClientRect().top - view.offset;
            else this.history.scrollTop = view.top;
            this.$('[data-inbox-list]').scrollTop = view.inboxTop;
        }
        toggleFullscreen() {
            if (this.fullscreenShell) {
                this.fullscreenView = this.captureView(); this.fullscreenShell.close(); return;
            }
            const view = this.captureView();
            const toggle = this.$('[data-expand-chat]');
            const marker = document.createComment('Support inbox position');
            const shell = node('dialog', 'sc-fullscreen-dialog');
            const pageScroll = {left: window.scrollX, top: window.scrollY};
            shell.setAttribute('aria-label', 'Full-screen support inbox');
            shell.setAttribute('aria-modal', 'true');
            // Reparenting must not replay existing message entrances and shift the reading position.
            this.list.querySelectorAll('[data-message]').forEach(row => row.classList.add('sc-message-settled'));
            this.root.before(marker); document.body.append(shell); shell.append(this.root);
            this.fullscreenShell = shell; this.root.classList.add('sc-fullscreen');
            document.documentElement.classList.add('sc-chat-expanded');
            toggle.setAttribute('aria-pressed', 'true'); toggle.setAttribute('aria-label', 'Exit full screen');
            toggle.title = 'Exit full screen (Esc)';
            toggle.querySelector('use').setAttribute('href', '#sc-restore');
            this.$('[data-expand-label]').textContent = 'Exit full screen';
            shell.addEventListener('cancel', event => {
                if (event.target !== shell) return;
                event.preventDefault(); this.fullscreenView = this.captureView(); shell.close();
            });
            shell.addEventListener('close', event => {
                // Nested image/details dialogs must not close the full-screen workspace.
                if (event.target !== shell) return;
                const currentView = this.fullscreenView || view; this.fullscreenView = null;
                this.list.querySelectorAll('[data-message]').forEach(row => row.classList.add('sc-message-settled'));
                this.root.classList.remove('sc-fullscreen'); marker.replaceWith(this.root);
                document.documentElement.classList.remove('sc-chat-expanded');
                this.fullscreenShell = null; shell.remove();
                toggle.setAttribute('aria-pressed', 'false'); toggle.setAttribute('aria-label', 'Enter full screen');
                toggle.title = 'Enter full screen'; toggle.querySelector('use').setAttribute('href', '#sc-expand');
                this.$('[data-expand-label]').textContent = 'Full screen';
                this.restoreView(currentView);
                toggle.focus({preventScroll: true}); window.scrollTo({...pageScroll, behavior: 'instant'});
            });
            shell.showModal(); toggle.focus({preventScroll: true}); this.restoreView(view);
        }
        sizeInput() {
            this.input.style.height = 'auto'; this.input.style.height = Math.min(126, this.input.scrollHeight || 38) + 'px';
            this.$('[data-length]').textContent = this.input.value.length.toLocaleString() + ' / 4,000';
        }
        saveDraft() {
            this.drafts.set(this.sessionId || 'new', {text: this.input.value, files: this.files.slice(), reply: this.reply, edit: this.edit, retry: this.retry, beforeEdit: this.beforeEdit});
        }
        async select(id, updateURL = true) {
            if (this.sending) { this.setError('Your message is sending. Please wait before switching conversations.'); return; }
            this.saveDraft(); this.epoch++; this.loading = false;
            this.sessionId = id; this.session = null; this.messages.clear(); this.cursor = null; this.messageSignature = null; this.threadQuery = ''; this.hasMore = false;
            this.$('[data-message-search]').value = ''; this.$('[data-thread-search]').hidden = true;
            this.$('[data-toggle-search]').setAttribute('aria-expanded', 'false');
            this.$('[data-welcome]').hidden = !!id; this.$('[data-conversation]').hidden = !id;
            this.root.classList.toggle('sc-has-session', !!id); this.$('[data-older]').hidden = true;
            this.$('[data-pins]').hidden = true; this.$('[data-jump-bottom]').hidden = true;
            const draft = this.drafts.get(id || 'new') || {};
            this.input.value = draft.text || ''; this.files = draft.files || []; this.reply = draft.reply || null; this.edit = draft.edit || null; this.retry = draft.retry || null;
            this.beforeEdit = draft.beforeEdit || null;
            this.context(); this.attachments(); this.setError(); this.sizeInput(); this.highlightInbox();
            if (updateURL) history.pushState({}, '', id ? this.root.dataset.homeUrl + id + '/' : this.root.dataset.homeUrl);
            if (!id) return;
            this.$('[data-name]').textContent = this.inboxRows.get(id)?.name || 'Customer';
            this.$('[data-presence]').textContent = 'Loading conversation…';
            this.list.replaceChildren(empty('Loading conversation', 'Your messages will appear in a moment.'));
            await this.loadState({initial: true});
        }
        highlightInbox() {
            this.root.querySelectorAll('[data-session-link]').forEach(link => link.setAttribute('aria-current', String(Number(link.dataset.sessionLink) === this.sessionId)));
        }
        async loadInbox(more = false, quiet = false) {
            if (!this.admin) return;
            const version = ++this.inboxVersion;
            const page = more ? this.inboxPage + 1 : (quiet ? this.inboxPage : 1);
            const url = new URL(this.root.dataset.inboxUrl, location.origin);
            url.searchParams.set('q', this.$('[data-inbox-search]').value.trim()); url.searchParams.set('status', this.filter);
            const list = this.$('[data-inbox-list]');
            this.$('[data-more-inbox]').disabled = true;
            try {
                // Refresh all already loaded pages so older conversations are not dropped.
                const batches = [];
                for (let n = (more ? page : 1); n <= page; n++) {
                    url.searchParams.set('page', n); batches.push(await this.request(url));
                }
                if (version !== this.inboxVersion) return;
                if (!more) this.inboxRows.clear();
                batches.flatMap(data => data.sessions).forEach(row => this.inboxRows.set(row.id, row));
                const data = batches[batches.length - 1]; this.inboxPage = page;
                this.$('[data-inbox-total]').textContent = data.stats.all || 0;
                this.root.querySelectorAll('[data-filter]').forEach(tab => {tab.querySelector('span').textContent = data.stats[tab.dataset.filter] || 0;});
                const fragment = document.createDocumentFragment();
                this.inboxRows.forEach(row => {
                    const link = node('a', 'sc-session'); link.href = row.url; link.dataset.sessionLink = row.id;
                    link.setAttribute('aria-label', row.name + (row.unread ? ', unread messages' : ''));
                    const avatar = node('span', 'sc-avatar', row.name.charAt(0).toUpperCase());
                    const info = node('span', 'sc-session-info');
                    info.append(node('span', 'sc-session-name', row.name), node('span', 'sc-session-preview', row.preview), node('span', 'sc-session-time', row.time));
                    link.append(avatar, info); if (row.unread) link.append(node('span', 'sc-unread-dot'));
                    link.addEventListener('click', event => {
                        if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
                        event.preventDefault(); if (row.id !== this.sessionId) this.select(row.id);
                    }); fragment.append(link);
                });
                if (!this.inboxRows.size) fragment.append(empty(this.filter === 'all' && !this.$('[data-inbox-search]').value ? 'No conversations yet' : 'No matching conversations', 'Customer messages appear here. Try another search or filter.'));
                // Do not replace focused links on a background refresh.
                const sig = JSON.stringify(Array.from(this.inboxRows.values()));
                if (sig !== this.inboxSignature) {list.replaceChildren(fragment); this.inboxSignature = sig;}
                this.$('[data-more-inbox]').hidden = !data.has_more; this.$('[data-inbox-error]').hidden = true;
                this.highlightInbox(); this.$('[data-sync]').textContent = 'Messages stay up to date';
            } catch (error) {
                if (version !== this.inboxVersion) return;
                const box = this.$('[data-inbox-error]'); box.hidden = false; box.textContent = error.message + ' Retrying automatically.';
                this.$('[data-sync]').textContent = 'Reconnecting…';
            } finally {if (version === this.inboxVersion) this.$('[data-more-inbox]').disabled = false;}
        }
        async loadSummary() {
            if (this.open) return;
            try {
                const url = new URL(this.root.dataset.stateUrl, location.origin); url.searchParams.set('summary', '1');
                const data = await this.request(url); if (!this.open) this.badge(data.unread);
            } catch (_) { /* Opening the widget provides a visible retry/error state. */ }
        }
        badge(count = 0) {
            const badge = this.$('[data-unread-badge]'); if (!badge) return;
            badge.textContent = count > 99 ? '99+' : count; badge.hidden = !count;
        }
        async toggle(show) {
            this.open = show; this.$('[data-room]').hidden = !show; this.root.classList.toggle('open', show);
            this.$('#adminChatToggle').setAttribute('aria-expanded', String(show));
            if (show) {
                this.$('[data-welcome]').hidden = true; this.$('[data-conversation]').hidden = false;
                await this.loadState({initial: !this.messages.size}); this.input.focus();
            } else { this.saveDraft(); this.$('#adminChatToggle').focus(); }
        }
        atBottom() { return this.history.scrollHeight - this.history.scrollTop - this.history.clientHeight < 90; }
        bottom(smooth = false) {
            this.history.scrollTo({top: this.history.scrollHeight, behavior: smooth && !matchMedia('(prefers-reduced-motion:reduce)').matches ? 'smooth' : 'instant'});
            this.$('[data-jump-bottom]').hidden = true;
        }
        async searchMessages(query) {
            this.threadQuery = query.trim(); this.$('[data-message-search]').value = query;
            this.epoch++; this.loading = false; this.messages.clear(); this.cursor = null; this.messageSignature = null; this.hasMore = false;
            await this.loadState({initial: true});
        }
        async loadState({initial = false, older = false, before = null} = {}) {
            if (this.loading || !this.open || this.admin && !this.sessionId) return;
            const epoch = this.epoch; this.loading = true;
            const url = new URL(this.root.dataset.stateUrl, location.origin);
            if (this.sessionId) url.searchParams.set('session_id', this.sessionId);
            if (this.threadQuery) url.searchParams.set('q', this.threadQuery);
            if (!initial && !older && !before && !this.threadQuery) {
                if (this.cursor) url.searchParams.set('after', this.cursor);
                const viewport = this.history.getBoundingClientRect();
                const visible = Array.from(this.list.querySelectorAll('[data-message]')).filter(row => {
                    const rect = row.getBoundingClientRect(); return rect.bottom >= viewport.top && rect.top <= viewport.bottom;
                }).slice(0, 50).map(row => row.dataset.message);
                if (visible.length) url.searchParams.set('watch', visible.join(','));
            }
            if (older && this.messages.size) url.searchParams.set('before', Math.min(...this.messages.keys()));
            if (before) url.searchParams.set('before', before);
            this.$('[data-older]').disabled = true;
            try {
                const data = await this.request(url); if (epoch !== this.epoch) return;
                const atBottom = this.atBottom(); const oldHeight = this.history.scrollHeight; const scroll = this.history.scrollTop;
                this.badge(data.unread); this.session = data.session;
                if (data.session) { this.sessionId = data.session.id; this.updateHeader(data.session); }
                if (initial || older) this.hasMore = data.has_more;
                const oldMax = Math.max(0, ...this.messages.keys());
                data.messages.forEach(message => this.messages.set(message.id, message));
                (data.updates || []).forEach(message => this.messages.set(message.id, message));
                if (!older && !before && data.messages.length) this.cursor = data.messages[data.messages.length - 1].id;
                this.pins = data.pinned || []; this.updatePins();
                this.renderMessages(); this.$('[data-older]').hidden = !this.hasMore;
                if (initial || atBottom && !older && !before) this.bottom();
                else if (older) this.history.scrollTop = scroll + this.history.scrollHeight - oldHeight;
                else if (data.messages.some(message => message.id > oldMax)) this.$('[data-jump-bottom]').hidden = false;
                if (!this.threadQuery && !older && !before) this.activity(false);
                if (data.more_new) setTimeout(() => {if (epoch === this.epoch) this.loadState();}, 50);
                if (this.stateFailed) { this.stateFailed = false; this.setError(); }
            } catch (error) {
                if (epoch !== this.epoch) return;
                this.stateFailed = true; this.setError(error.message);
                if (!this.messages.size) {
                    const placeholder = empty('Could not load messages', 'Your conversation is safe. Check your connection and try again.');
                    placeholder.append(button('Try again', 'sc-button', () => this.loadState({initial: true}))); this.list.replaceChildren(placeholder);
                }
            } finally { if (epoch === this.epoch) {this.loading = false; this.$('[data-older]').disabled = false;} }
        }
        updateHeader(session) {
            this.$('[data-name]').textContent = session.name;
            if (this.admin) this.$('[data-avatar]').textContent = session.name.charAt(0).toUpperCase();
            const status = this.$('[data-presence]'); status.classList.toggle('sc-online', session.online);
            status.textContent = session.status === 'closed' ? 'Conversation closed' : session.online ? 'Online now' : 'Offline · Leave a message';
            this.$('[data-closed]').hidden = session.status !== 'closed';
            this.$('[data-typing]').hidden = !session.typing;
            this.$('[data-typing-text]').textContent = this.admin ? session.name.split(' ')[0] + ' is typing…' : 'Support is typing…';
        }
        updatePins() {
            const pins = this.$('[data-pins]'); pins.hidden = !this.pins?.length;
            pins.querySelector('span').textContent = (this.pins?.length || 0) + ' pinned · ' + (this.pins?.[0]?.snippet || 'Photo attachment');
        }
        renderMessages() {
            const rows = Array.from(this.messages.values()).sort((a, b) => a.id - b.id);
            const sig = JSON.stringify(rows); if (sig === this.messageSignature) return;
            this.messageSignature = sig;
            const existing = new Map(Array.from(this.list.querySelectorAll('[data-message]')).map(row => [Number(row.dataset.message), row]));
            const days = new Map(Array.from(this.list.querySelectorAll('[data-day]')).map(row => [row.dataset.day, row]));
            const desired = []; let day = '';
            for (const message of rows) {
                if (day !== message.day) {
                    const separator = days.get(message.day) || node('div', 'sc-day', message.day);
                    separator.dataset.day = message.day; desired.push(separator); day = message.day;
                }
                const old = existing.get(message.id);
                const signature = JSON.stringify([message.content, message.is_deleted, message.is_edited, message.is_pinned,
                    message.image_url, message.image_name, message.reply_to, message.reactions, message.my_reactions,
                    message.time, message.sent_iso, message.day, message.own, message.own && message.seen,
                    message.own && message.delivered]);
                let element = old;
                if (!old || old.messageSignature !== signature) {
                    element = this.messageNode(message); element.messageSignature = signature;
                    if (old) element.style.animation = 'none';
                }
                desired.push(element);
            }
            if (!rows.length) desired.push(empty(this.threadQuery ? 'No matching messages' : 'How can we help?', this.threadQuery ? 'Try another keyword to search this conversation.' : this.admin ? 'Send a reply to start the conversation.' : 'Ask about your booking, payments or event setup. Our team will reply here.'));
            const wanted = new Set(desired);
            Array.from(this.list.children).forEach(element => {if (!wanted.has(element)) element.remove();});
            let cursor = this.list.firstElementChild;
            desired.forEach(element => {
                if (element === cursor) cursor = cursor.nextElementSibling;
                else this.list.insertBefore(element, cursor);
            });
        }
        messageNode(message) {
            const row = node('article', 'sc-message' + (message.own ? ' sc-own' : '') + (message.is_deleted ? ' sc-deleted' : ''));
            row.dataset.message = message.id;
            if (message.reply_to) row.append(button((message.reply_to.is_deleted ? 'Message deleted' : message.reply_to.text || 'Photo attachment').slice(0, 100), 'sc-reply-snippet', () => this.jump(message.reply_to.id)));
            const bubble = node('div', 'sc-bubble');
            if (message.is_deleted || message.content) bubble.append(node('p', 'sc-message-text', message.is_deleted ? 'This message was deleted' : message.content));
            if (message.image_url && !message.is_deleted) {
                const photo = button('View attachment', 'sc-message-photo', () => this.showImage(message.image_url, message.image_name));
                const img = node('img'); img.src = message.image_url; img.alt = message.image_name || 'Chat attachment'; img.loading = 'lazy';
                img.addEventListener('load', () => { if (this.atBottom()) this.bottom(); });
                photo.replaceChildren(img); photo.setAttribute('aria-label', 'View attachment'); bubble.append(photo);
            }
            const meta = node('div', 'sc-message-meta');
            if (this.admin && message.is_from_admin && !message.own) meta.append(node('span', '', message.sender_name + ' · Team'));
            const time = node('time', '', message.time); time.dateTime = message.sent_iso || ''; time.title = message.sent_at;
            meta.append(time);
            if (message.is_edited && !message.is_deleted) meta.append(node('span', '', 'Edited'));
            if (message.is_pinned && !message.is_deleted) {meta.append(icon('pin'), node('span', '', 'Pinned'));}
            if (message.own && !message.is_deleted) meta.append(node('span', '', message.seen ? 'Seen' : message.delivered ? 'Delivered' : 'Sent'));
            row.append(bubble, meta);
            if (!message.is_deleted) {
                const actions = node('div', 'sc-message-actions');
                Object.entries(message.reactions || {}).forEach(([emoji, count]) => {
                    const b = button(emoji + ' ' + count, 'sc-reaction-chip', () => this.messageAction('react', message, {emoji}));
                    b.setAttribute('aria-label', 'React ' + emoji); b.setAttribute('aria-pressed', String((message.my_reactions || []).includes(emoji))); actions.append(b);
                });
                actions.append(button('Reply', 'sc-icon', () => this.startReply(message), 'reply'),
                    button('React', 'sc-icon', event => this.menu(message, row, event.currentTarget, true), 'smile'),
                    button('Message options', 'sc-icon', event => this.menu(message, row, event.currentTarget), 'more'));
                row.append(actions);
            }
            return row;
        }
        menu(message, row, trigger, reactions = false) {
            const wasOpen = row.querySelector('.sc-message-menu');
            this.root.querySelectorAll('.sc-message-menu').forEach(el => el.remove()); if (wasOpen) return;
            const menu = node('div', 'sc-message-menu'); menu.setAttribute('role', 'group'); menu.setAttribute('aria-label', reactions ? 'Choose a reaction' : 'Message actions');
            if (reactions) {
                const choices = node('div', 'sc-reaction-options');
                for (const emoji of ['👍', '❤️', '😮', '😂', '😢']) choices.append(button(emoji, '', () => {menu.remove(); this.messageAction('react', message, {emoji});}));
                menu.append(choices);
            } else {
                const item = (label, symbol, handler, danger = false) => {
                    const b = button(label, 'sc-menu-item' + (danger ? ' sc-danger' : ''), () => {menu.remove(); handler();}); b.prepend(icon(symbol)); menu.append(b);
                };
                item(message.is_pinned ? 'Unpin message' : 'Pin message', 'pin', () => this.messageAction('pin', message));
                if (message.own) {
                    if (message.content) item('Edit message', 'edit', () => this.startEdit(message));
                    item('Delete message', 'trash', () => this.confirmDelete(message), true);
                }
            }
            row.querySelector('.sc-message-actions').append(menu);
            menu.querySelector('button')?.focus({preventScroll: true});
        }
        async messageAction(action, message, extra = {}) {
            if (this.messageBusy.has(message.id)) return false;
            this.messageBusy.add(message.id);
            const epoch = this.epoch;
            try {
                const data = await this.action(action, {message_id: message.id, ...extra});
                if (epoch !== this.epoch) return;
                this.messages.set(data.updated.id, data.updated); this.pins = data.pinned; this.updatePins(); this.renderMessages();
                if (action === 'delete') this.feedback('Message deleted.');
                if (action === 'pin') this.feedback(data.updated.is_pinned ? 'Message pinned.' : 'Message unpinned.');
                return true;
            } catch (error) {if (epoch === this.epoch) this.setError(error.message); return false;}
            finally {this.messageBusy.delete(message.id);}
        }
        startReply(message) {
            if (this.sending) return;
            if (this.edit) this.cancelContext(); this.reply = message; this.retry = null; this.context(); this.input.focus(); this.saveDraft();
        }
        startEdit(message) {
            if (this.sending) return;
            if (!this.edit) this.beforeEdit = {text: this.input.value, files: this.files.slice(), reply: this.reply};
            this.reply = null; this.edit = message; this.files = []; this.input.value = message.content;
            this.retry = null; this.context(); this.attachments(); this.sizeInput(); this.input.focus(); this.saveDraft();
        }
        cancelContext() {
            if (this.sending) return;
            if (this.edit) {
                this.input.value = this.beforeEdit?.text || ''; this.files = this.beforeEdit?.files || []; this.reply = this.beforeEdit?.reply || null; this.edit = null;
            } else this.reply = null;
            this.retry = null; this.context(); this.attachments(); this.sizeInput(); this.saveDraft();
        }
        context() {
            const box = this.$('[data-context]'); const message = this.edit || this.reply;
            box.hidden = !message;
            this.$('[data-context-label]').textContent = this.edit ? 'Editing your message' : 'Replying to ' + (message?.sender_name || 'message');
            this.$('[data-context-text]').textContent = message?.content || 'Photo attachment';
        }
        addFiles(files) {
            if (this.sending) return;
            if (this.edit) {this.setError('Finish editing before attaching photos.'); return;}
            const added = Array.from(files);
            if (this.files.length + added.length > 4) {this.setError('You can attach up to 4 images per message.'); return;}
            for (const file of added) {
                if (!['image/jpeg', 'image/png', 'image/gif', 'image/webp'].includes(file.type)) {this.setError('Choose JPG, PNG, GIF or WEBP images.'); return;}
                if (file.size > 5 * 1024 * 1024) {this.setError('Each image must be 5 MB or smaller.'); return;}
            }
            this.files.push(...added); this.retry = null; this.setError(); this.attachments(); this.saveDraft();
        }
        attachments() {
            (this.previewURLs || []).forEach(url => URL.revokeObjectURL(url)); this.previewURLs = [];
            const list = this.$('[data-attachments]'); list.replaceChildren(); list.hidden = !this.files.length;
            this.files.forEach((file, index) => {
                const wrap = node('div', 'sc-attachment'); const img = node('img');
                img.src = URL.createObjectURL(file); this.previewURLs.push(img.src); img.alt = file.name;
                wrap.append(img, button('Remove ' + file.name, 'sc-icon', () => {if (!this.sending) {this.files.splice(index, 1); this.retry = null; this.attachments(); this.saveDraft();}}, 'x')); list.append(wrap);
            });
        }
        async send() {
            if (this.sending) return;
            const text = this.input.value.trim();
            if (!text && !this.files.length) {this.setError('Write a message or attach an image.'); this.input.focus(); return;}
            if (text.length > 4000) {this.setError('Keep your message to 4,000 characters or fewer.'); return;}
            this.setError(); this.sending = true;
            this.input.disabled = true; this.$('[data-send]').disabled = true; this.$('[data-attach]').disabled = true;
            this.$('[data-send-status]').textContent = this.edit ? 'Saving changes…' : 'Sending…';
            const epoch = this.epoch;
            try {
                let data;
                if (this.edit) data = await this.action('edit', {message_id: this.edit.id, message: text});
                else {
                    if (!this.retry) {
                        const form = new FormData(); form.set('message', text); form.set('request_id', crypto.randomUUID());
                        if (this.sessionId) form.set('session_id', this.sessionId);
                        if (this.reply) form.set('reply_to_id', this.reply.id);
                        this.files.forEach(file => form.append('image', file)); this.retry = form;
                    }
                    data = await this.request(this.root.dataset.sendUrl, {method: 'POST', body: this.retry});
                }
                if (epoch !== this.epoch) return;
                if (data.updated) this.messages.set(data.updated.id, data.updated);
                else {this.sessionId = data.session_id; data.messages.forEach(message => this.messages.set(message.id, message));}
                const edited = !!this.edit;
                this.input.value = edited ? this.beforeEdit?.text || '' : '';
                this.files = edited ? this.beforeEdit?.files || [] : [];
                this.reply = edited ? this.beforeEdit?.reply || null : null;
                this.edit = null; this.retry = null; this.beforeEdit = null;
                this.context(); this.attachments(); this.sizeInput(); this.saveDraft(); this.renderMessages(); this.bottom();
                this.$('[data-send-status]').textContent = edited ? 'Message updated' : 'Message sent';
                if (this.admin) this.loadInbox(false, true);
                if (this.threadQuery) this.searchMessages('');
                else this.loadState();
            } catch (error) {
                this.setError(error.message); this.$('[data-send-status]').textContent = 'Not sent · Your draft is kept. Try again.';
                this.saveDraft();
            } finally {
                this.sending = false; this.input.disabled = false; this.$('[data-send]').disabled = false; this.$('[data-attach]').disabled = false; this.input.focus();
            }
        }
        async activity(typing = false) {
            if (!this.open || !this.sessionId || document.hidden || !document.hasFocus()) return;
            if (Date.now() - (this.activityAt || 0) < 2800) return;
            this.activityAt = Date.now();
            const last = this.cursor || 0; const read = this.atBottom() && !this.threadQuery && !this.dialog.open && !!last;
            try { await this.action('activity', {typing, read, last_id: last}); if (read && !this.admin) this.badge(0); }
            catch (_) { /* Message load/send requests report connection failures. */ }
        }
        async jump(id) {
            if (this.threadQuery) await this.searchMessages('');
            // Keep history contiguous when jumping to an older pin/reply. Adding
            // just its surrounding page would leave an unreachable gap above it.
            while (!this.messages.has(Number(id)) && this.hasMore) {
                const oldest = Math.min(...this.messages.keys());
                await this.loadState({older: true});
                if (Math.min(...this.messages.keys()) === oldest) {
                    this.setError('Could not load the original message. Please try again.'); return;
                }
            }
            const row = this.list.querySelector('[data-message="' + Number(id) + '"]');
            if (row) {
                row.scrollIntoView({block: 'center', behavior: matchMedia('(prefers-reduced-motion:reduce)').matches ? 'instant' : 'smooth'});
                row.classList.remove('sc-highlight'); requestAnimationFrame(() => row.classList.add('sc-highlight'));
            } else this.setError('This message is no longer available.');
        }
        openDialog(title, image = false) {
            this.$('[data-dialog-body]').replaceChildren(); this.$('[data-dialog-footer]').replaceChildren();
            this.$('[data-dialog-title]').textContent = title; this.dialog.classList.toggle('sc-image-dialog', image);
            if (!this.dialog.open) this.dialog.showModal();
            return [this.$('[data-dialog-body]'), this.$('[data-dialog-footer]')];
        }
        confirmDelete(message) {
            const [body, footer] = this.openDialog('Delete this message?');
            body.append(node('p', '', 'The message will be removed from this conversation for both you and the other person.'));
            const cancel = button('Cancel', 'sc-button', () => this.dialog.close());
            const remove = button('Delete message', 'sc-button sc-danger', async () => {
                remove.disabled = true; cancel.disabled = true;
                const success = await this.messageAction('delete', message);
                if (success) this.dialog.close();
                else {const error = node('p', 'sc-error', this.$('[data-error]').textContent); body.querySelector('.sc-error')?.remove(); body.append(error);}
                remove.disabled = false; cancel.disabled = false;
            }); footer.append(cancel, remove); cancel.focus();
        }
        async showInfo() {
            const [body, footer] = this.openDialog('Conversation details');
            body.append(node('p', '', this.admin ? this.session?.email || 'Customer support conversation.' : 'Your conversation with the Balloorina support team. Leave a message whenever you need help.'));
            body.append(node('h3', '', 'Pinned messages'));
            if (!this.pins?.length) body.append(node('p', '', 'No pinned messages yet. Use a message’s options to pin it.'));
            (this.pins || []).forEach(pin => body.append(button(pin.snippet || 'Photo attachment', 'sc-pin-item', () => {this.dialog.close(); this.jump(pin.id);})));
            body.append(node('h3', '', 'Shared photos'));
            const media = node('div', 'sc-media-grid'); body.append(media);
            if (this.admin && this.session) {
                const closed = this.session.status === 'closed';
                footer.append(button(closed ? 'Reopen conversation' : 'Close conversation', 'sc-button', async event => {
                    event.currentTarget.disabled = true;
                    try {
                        const data = await this.action(closed ? 'reopen' : 'close'); this.session = data.session; this.updateHeader(data.session);
                        this.dialog.close(); this.feedback(closed ? 'Conversation reopened.' : 'Conversation closed.'); this.loadInbox(false, true);
                    } catch (error) {body.append(node('p', 'sc-error', error.message)); event.currentTarget.disabled = false;}
                }));
            }
            footer.append(button('Done', 'sc-button', () => this.dialog.close()));
            if (!this.sessionId) {media.append(node('p', '', 'No photos shared yet.')); return;}
            const epoch = this.epoch;
            try {
                const url = new URL(this.root.dataset.stateUrl, location.origin); url.searchParams.set('session_id', this.sessionId); url.searchParams.set('media', '1');
                const data = await this.request(url); if (!this.dialog.open || epoch !== this.epoch) return;
                for (const photo of data.media || []) {
                    const b = button('View ' + photo.name, '', () => this.showImage(photo.url, photo.name));
                    const img = node('img'); img.src = photo.url; img.alt = photo.name; img.loading = 'lazy'; b.replaceChildren(img); b.setAttribute('aria-label', 'View ' + photo.name); media.append(b);
                }
                if (!data.media?.length) media.append(node('p', '', 'No photos shared yet.'));
                else if (data.media.length === 100) body.append(node('p', '', 'Showing the latest 100 photos. Earlier photos are available in the conversation.'));
            } catch (error) {media.append(node('p', 'sc-error', error.message));}
        }
        showImage(url, name = 'Chat photo') {
            const [body, footer] = this.openDialog('Photo attachment', true);
            const img = node('img', 'sc-preview-image'); img.src = url; img.alt = name;
            body.append(img);
            const link = node('a', 'sc-button', 'Download image'); link.href = url; link.download = name || 'chat-photo';
            link.target = '_blank'; link.rel = 'noopener'; link.prepend(icon('download')); footer.append(link);
        }
        async poll(immediate = false) {
            clearTimeout(this.pollTimer);
            if (this.polling) return;
            this.polling = true;
            try {
                if (!document.hidden) {
                    if (this.admin) await this.loadInbox(false, true);
                    if (this.open && !this.sending) await this.loadState();
                    else if (!this.admin) await this.loadSummary();
                }
            } finally { this.polling = false; this.pollTimer = setTimeout(() => this.poll(), this.open ? 4500 : 15000); }
        }
    }
    function init() {
        document.querySelectorAll('[data-support-chat]').forEach(root => {
            if (!root.dataset.supportReady) { root.dataset.supportReady = 'true'; new SupportChat(root); }
        });
    }
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init, {once: true}); else init();
})();
