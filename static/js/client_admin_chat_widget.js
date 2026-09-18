(function () {
    const widget = document.getElementById("adminChatWidget");
    if (!widget) return;

    const toggle = document.getElementById("adminChatToggle");
    const closeBtn = document.getElementById("adminChatClose");
    const panel = document.getElementById("adminChatPanel");
    const messagesEl = document.getElementById("adminChatMessages");
    const emptyEl = document.getElementById("adminChatEmpty");
    const form = document.getElementById("adminChatForm");
    const input = document.getElementById("adminChatInput");
    const imageInput = document.getElementById("adminChatImage");
    const attachmentPreview = document.getElementById("adminChatAttachmentPreview");
    const sendBtn = document.getElementById("adminChatSend");
    const statusEl = document.getElementById("adminChatStatus");
    const errorEl = document.getElementById("adminChatError");
    const badgeEl = document.getElementById("adminChatBadge");
    const editingBar = document.getElementById("adminChatEditingBar");
    const editingTextEl = document.getElementById("adminChatEditingText");
    const cancelEditBtn = document.getElementById("adminChatCancelEdit");
    const replyBar = document.getElementById("adminChatReplyBar");
    const replyTextEl = document.getElementById("adminChatReplyText");
    const cancelReplyBtn = document.getElementById("adminChatCancelReply");
    const typingEl = document.getElementById("adminChatTyping");
    const lightboxEl = document.getElementById("adminChatLightbox");
    const lightboxImg = document.getElementById("adminChatLightboxImg");
    const lightboxCaption = document.getElementById("adminChatLightboxCaption");

    // Info drawer + pinned messages
    const infoTrigger = document.getElementById("adminChatInfoTrigger");
    const infoDrawer = document.getElementById("adminChatInfoDrawer");
    const infoCloseBtn = document.getElementById("adminChatInfoClose");
    const infoBackdrop = document.getElementById("adminChatInfoBackdrop");
    const infoPresence = document.getElementById("adminChatInfoPresence");
    const pinnedList = document.getElementById("adminChatPinnedList");
    const pinnedEmpty = document.getElementById("adminChatPinnedEmpty");
    const pinnedCountBadge = document.getElementById("adminChatPinnedCount");
    const mediaGrid = document.getElementById("adminChatMediaGrid");
    const mediaEmpty = document.getElementById("adminChatMediaEmpty");
    const mediaCountBadge = document.getElementById("adminChatMediaCount");
    const mediaLightbox = document.getElementById("adminChatMediaLightbox");

    let currentSessionId = null;
    let editingMessageId = null;
    let replyToId = null;
    let currentStatus = "idle";
    let isSending = false;
    let lastMessageSignature = "";
    let lastTypingPingAt = 0;
    let lightboxImages = [];
    let lightboxIndex = 0;
    const maxImageBytes = 15 * 1024 * 1024;
    const allowedImageTypes = ["image/jpeg", "image/png", "image/gif", "image/webp"];
    const REACTION_EMOJIS = ["👍", "❤️", "😮", "😂", "😢"];
    const ICON_REACT = '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="10"></circle><path d="M8 14s1.5 2 4 2 4-2 4-2"></path><line x1="9" y1="9" x2="9.01" y2="9"></line><line x1="15" y1="9" x2="15.01" y2="9"></line></svg>';
    const ICON_REPLY = '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="9 14 4 9 9 4"></polyline><path d="M20 20v-7a4 4 0 0 0-4-4H4"></path></svg>';
    const ICON_EDIT = '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M17 3a2.85 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z"></path></svg>';
    const ICON_DELETE = '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path></svg>';
    const ICON_PIN = '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 17v5"></path><path d="M9 10.76a2 2 0 0 1-1.11 1.79l-1.78.9A2 2 0 0 0 5 15.24V16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-.76a2 2 0 0 0-1.11-1.79l-1.78-.9A2 2 0 0 1 15 10.76V6h1a2 2 0 0 0 0-4H8a2 2 0 0 0 0 4h1z"></path></svg>';
    // Messenger-style red pushpin shown on pinned bubbles (nakatusok sa bubble)
    const PIN_FLAG_SVG = '<svg viewBox="0 0 384 512" width="11" height="11" fill="currentColor" aria-hidden="true"><path d="M298.028 214.267L285.793 96H328c13.255 0 24-10.745 24-24s-10.745-24-24-24H56c-13.255 0-24 10.745-24 24s10.745 24 24 24h42.207L86.028 214.267C70.485 229.81 64 244.038 64 256c0 30.928 25.072 56 56 56h56v110.057c0 11.612 9.417 21.028 21.028 21.028s21.028-9.417 21.028-21.028V312h56c30.928 0 56-25.072 56-56 0-11.962-6.485-26.19-21.972-41.733z"></path></svg>';
    const PIN_FLAG_HTML = '<span class="pin-flag" aria-hidden="true">' + PIN_FLAG_SVG + '<span>Pinned</span></span>';

    const urls = {
        sessions: widget.dataset.sessionsUrl,
        history: widget.dataset.historyUrl,
        request: widget.dataset.requestUrl,
        send: widget.dataset.sendUrl,
        markRead: widget.dataset.markReadUrl,
        edit: widget.dataset.editUrl,
        typingPing: widget.dataset.typingPingUrl,
        reaction: widget.dataset.reactionUrl,
        delete: widget.dataset.deleteUrl,
        pin: widget.dataset.pinUrl,
        media: widget.dataset.mediaUrl,
    };
    const csrfToken = widget.dataset.csrfToken;

    function escapeHtml(value) {
        const div = document.createElement("div");
        div.textContent = value || "";
        return div.innerHTML;
    }

    function headers() {
        return {
            "Content-Type": "application/json",
            "X-CSRFToken": csrfToken,
        };
    }

    function validateImage(file) {
        if (!file) return true;
        if (!allowedImageTypes.includes(file.type)) {
            setError("Images only: JPG, PNG, GIF, or WEBP.");
            return false;
        }
        if (file.size > maxImageBytes) {
            setError("Image must be 15MB or smaller.");
            return false;
        }
        return true;
    }

    function clearAttachment() {
        if (imageInput) imageInput.value = "";
        if (attachmentPreview) {
            attachmentPreview.hidden = true;
            attachmentPreview.innerHTML = "";
        }
    }

    function renderAttachmentPreview(files) {
        if (!attachmentPreview || !files || !files.length) return;
        attachmentPreview.hidden = false;
        const label = files.length === 1
            ? escapeHtml(files[0].name)
            : `${escapeHtml(files[0].name)} +${files.length - 1} more`;
        attachmentPreview.innerHTML = `
            <span><i class="fas fa-image"></i> ${label} — ${files.length} image${files.length === 1 ? "" : "s"}</span>
            <button type="button" aria-label="Remove image">&times;</button>
        `;
        attachmentPreview.querySelector("button").addEventListener("click", clearAttachment);
    }

    function validateImages(fileList) {
        const files = Array.from(fileList || []);
        if (!files.length) return [];
        for (const file of files) {
            if (!validateImage(file)) return null;
        }
        return files;
    }

    function setError(message) {
        errorEl.textContent = message || "";
        errorEl.classList.toggle("show", Boolean(message));
    }

    function setBadge(count) {
        const value = Number(count || 0);
        badgeEl.textContent = String(value);
        badgeEl.hidden = value <= 0;
    }

    function setStatus(status, assignedAdmin) {
        currentStatus = status || "idle";
        input.disabled = false;
        if (imageInput) imageInput.disabled = false;
        sendBtn.disabled = isSending;
    }

    function setPresence(online) {
        if (!statusEl) return;
        statusEl.innerHTML = online
            ? '<span class="admin-chat-presence online"><span class="admin-chat-presence-dot"></span> Online</span>'
            : '<span class="admin-chat-presence offline"><span class="admin-chat-presence-dot"></span> Offline</span>';
        // Mirror the presence into the info drawer (status line)
        if (infoPresence) {
            infoPresence.innerHTML = online
                ? '<span class="admin-chat-presence online"><span class="admin-chat-presence-dot"></span> Online</span>'
                : '<span class="admin-chat-presence offline"><span class="admin-chat-presence-dot"></span> Offline</span>';
        }
    }

    function scrollBottom() {
        messagesEl.scrollTop = messagesEl.scrollHeight;
    }

    function computeMessagesSignature(messages) {
        return JSON.stringify((messages || []).map(msg => [
            msg.id, msg.role, msg.content, msg.image_url, msg.sent_at,
            msg.is_edited, msg.seen, msg.delivered, msg.is_deleted,
            JSON.stringify(msg.reactions || {}), JSON.stringify(msg.reply_to || null),
            Boolean(msg.is_pinned),
        ]));
    }

    let lastMessagesData = [];

    function renderMessages(messages) {
        lastMessagesData = messages || [];
        const signature = computeMessagesSignature(lastMessagesData);
        if (signature === lastMessageSignature) return;
        lastMessageSignature = signature;
        const prevCount = messagesEl.querySelectorAll(".admin-chat-msg").length;
        const wasNearBottom = messagesEl.scrollHeight - messagesEl.scrollTop - messagesEl.clientHeight < 140;
        messagesEl.innerHTML = "";
        lightboxImages = [];

        if (!messages || messages.length === 0) {
            messagesEl.appendChild(emptyEl);
            emptyEl.hidden = false;
            return;
        }

        emptyEl.hidden = true;
        messages.forEach(msg => {
            const isClient = msg.role === "user";
            const row = document.createElement("div");
            row.className = `admin-chat-msg ${isClient ? "client" : "admin"}`;
            row.dataset.senderName = msg.sender_name || "";
            let imageHtml = "";
            if (!msg.is_deleted && msg.image_url) {
                lightboxImages.push({ url: msg.image_url, name: msg.image_name || "Chat image" });
                const idx = lightboxImages.length - 1;
                imageHtml = `<div class="admin-chat-image-wrap"><img src="${escapeHtml(msg.image_url)}" alt="${escapeHtml(msg.image_name || "Chat image")}" data-lightbox-index="${idx}" class="admin-chat-image-link"><a href="${escapeHtml(msg.image_url)}" download="${escapeHtml(msg.image_name || "chat-image")}" class="admin-chat-image-download" title="Save image" aria-label="Save image"><svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="7 10 12 15 17 10"></polyline><line x1="12" y1="15" x2="12" y2="3"></line></svg></a></div>`;
            }
            let replyHtml = "";
            if (!msg.is_deleted && msg.reply_to) {
                const r = msg.reply_to;
                let quoteCls = "admin-chat-quote";
                let quoteInner;
                if (r.is_deleted) {
                    quoteInner = `<span class="admin-chat-quote-text">↩ This message was deleted</span>`;
                } else if (r.text) {
                    quoteInner = `<span class="admin-chat-quote-text">↩ ${escapeHtml(String(r.text).substring(0, 60))}</span>`;
                } else if (r.has_image) {
                    quoteCls += " has-photo";
                    quoteInner = `<span class="admin-chat-quote-icon"><i class="fas fa-image"></i></span><span class="admin-chat-quote-text">Photo</span>`;
                } else {
                    quoteInner = `<span class="admin-chat-quote-text">↩ Message</span>`;
                }
                replyHtml = `<div class="${quoteCls}" data-reply-to-id="${escapeHtml(String(r.id || ""))}" title="Jump to original message">${quoteInner}</div>`;
            }
            const deletedHtml = msg.is_deleted ? ` <span class="admin-chat-deleted-at">${escapeHtml(msg.deleted_at || "")}</span>` : "";
            const editedHtml = (!msg.is_deleted && msg.is_edited) ? `<span class="admin-chat-edited">(Edited)</span>` : "";
            const textHtml = msg.content || msg.is_deleted
                ? `<div class="admin-chat-text ${msg.is_deleted ? "is-deleted" : ""}">${msg.is_deleted ? "This message was deleted" : escapeHtml(msg.content)}</div>`
                : "";
            let actionsHtml = "";
            if (!msg.is_deleted && msg.id) {
                const editBtn = (isClient && msg.content)
                    ? `<button type="button" class="admin-chat-act" data-act="edit" title="Edit message" aria-label="Edit message">${ICON_EDIT}</button>`
                    : "";
                const pinBtn = `<button type="button" class="admin-chat-act pin-act${msg.is_pinned ? " active" : ""}" data-act="pin" data-message-id="${msg.id}" title="${msg.is_pinned ? "Unpin message" : "Pin message"}" aria-label="${msg.is_pinned ? "Unpin message" : "Pin message"}">${ICON_PIN}</button>`;
                actionsHtml = `<div class="admin-chat-actions"><button type="button" class="admin-chat-act" data-act="react" title="React" aria-label="React">${ICON_REACT}</button><button type="button" class="admin-chat-act" data-act="reply" title="Reply" aria-label="Reply">${ICON_REPLY}</button>${pinBtn}${editBtn}${isClient ? `<button type="button" class="admin-chat-act" data-act="delete" title="Delete message" aria-label="Delete message">${ICON_DELETE}</button>` : ""}</div>`;
            }
            let reactionsHtml = "";
            if (!msg.is_deleted && msg.reactions && Object.keys(msg.reactions).length) {
                const mine = new Set(msg.my_reactions || []);
                const emojis = Object.keys(msg.reactions).join("");
                const total = Object.values(msg.reactions).reduce(function (a, b) { return a + b; }, 0);
                const myEmoji = mine.size ? mine.values().next().value : "";
                reactionsHtml = `<div class="admin-chat-reactions"><button type="button" class="admin-chat-reaction-chip ${mine.size ? "mine" : ""}" data-my-emoji="${escapeHtml(myEmoji)}" title="Reaction">${escapeHtml(emojis)} <span class="count">${total}</span></button></div>`;
            }
            const receipt = isClient
                ? `<span class="admin-chat-receipt ${msg.seen ? "seen" : msg.delivered ? "delivered" : "sent"}">${msg.seen ? `✓ Seen${msg.seen_at ? " " + escapeHtml(msg.seen_at) : ""}` : msg.delivered ? "✓ Delivered" : "Sent"}</span>`
                : "";
            row.innerHTML = `
                ${replyHtml}
                <div class="admin-chat-bubble">${msg.is_pinned && !msg.is_deleted ? PIN_FLAG_HTML : ""}${textHtml}${imageHtml}${reactionsHtml}</div>
                ${actionsHtml}
                <div class="admin-chat-time">${escapeHtml(msg.sent_at || "")} ${editedHtml}${deletedHtml} ${receipt}</div>
            `;
            if (msg.id) row.dataset.id = msg.id;
            if (msg.is_pinned) row.classList.add("pinned-row");
            if (reactionsHtml) row.classList.add("has-reactions");
            messagesEl.appendChild(row);
            const imgEl = row.querySelector("img.admin-chat-image-link");
            if (imgEl && !imgEl.complete) imgEl.addEventListener("load", function () {
                const nearBottom = messagesEl.scrollHeight - messagesEl.scrollTop - messagesEl.clientHeight < 160;
                if (nearBottom) scrollBottom();
            }, { once: true });
        });
        // Only jump to the bottom when a new message arrived or the user was
        // already reading at the bottom — never on reaction-only updates.
        if (messages.length > prevCount || wasNearBottom) scrollBottom();
        renderPinEventLines();
    }

    // ── Hover actions: reaction picker, reply, delete, lightbox ──
    function closeReactionPicker() {
        document.querySelectorAll(".admin-chat-reaction-picker").forEach(el => el.remove());
    }

    function showReactionPicker(row) {
        closeReactionPicker();
        const picker = document.createElement("div");
        picker.className = "admin-chat-reaction-picker";
        picker.innerHTML = REACTION_EMOJIS.map(e => `<button type="button" data-emoji="${e}">${e}</button>`).join("");
        row.appendChild(picker);
    }

    function updateReactionChip(row, reactions, myReactions) {
        if (!row) return;
        const counts = reactions || {};
        const emojis = Object.keys(counts).join("");
        let container = row.querySelector(".admin-chat-reactions");
        if (!emojis) {
            if (container) container.remove();
            row.classList.remove("has-reactions");
            return;
        }
        const mine = new Set(myReactions || []);
        const total = Object.values(counts).reduce(function (a, b) { return a + b; }, 0);
        const myEmoji = mine.size ? mine.values().next().value : "";
        const html = `<button type="button" class="admin-chat-reaction-chip ${mine.size ? "mine" : ""}" data-my-emoji="${escapeHtml(myEmoji)}" title="Reaction">${escapeHtml(emojis)} <span class="count">${total}</span></button>`;
        if (!container) {
            container = document.createElement("div");
            container.className = "admin-chat-reactions";
            // The pill lives inside the bubble (position: relative) so it
            // hugs the bubble's bottom edge like Messenger.
            const bubble = row.querySelector(".admin-chat-bubble");
            if (bubble) bubble.appendChild(container);
            else row.appendChild(container);
        }
        container.innerHTML = html;
        row.classList.add("has-reactions");
    }

    async function toggleReaction(messageId, emoji) {
        if (!messageId || !emoji) return;
        const response = await fetch(urls.reaction, {
            method: "POST",
            headers: headers(),
            body: JSON.stringify({ message_id: messageId, emoji: emoji }),
        });
        const data = await response.json();
        if (data.error) throw new Error(data.error);
        // Update the pill in place — no reload, no scroll jump, no flicker.
        const row = messagesEl.querySelector(`.admin-chat-msg[data-id="${messageId}"]`);
        updateReactionChip(row, data.reactions, data.my_reactions);
        // Keep the cached messages + signature in sync so the next poll
        // doesn't re-render the whole thread.
        const cached = (lastMessagesData || []).find(function (m) { return String(m.id) === String(messageId); });
        if (cached) {
            cached.reactions = data.reactions || {};
            cached.my_reactions = data.my_reactions || [];
            lastMessageSignature = computeMessagesSignature(lastMessagesData);
        }
    }

    function confirmDeleteDialog() {
        const overlay = document.getElementById("adminChatConfirmOverlay");
        if (!overlay) return Promise.resolve(window.confirm("Delete this message?"));
        return new Promise(function (resolve) {
            const cancelBtn = document.getElementById("adminChatConfirmCancel");
            const deleteBtn = document.getElementById("adminChatConfirmDelete");
            function done(result) {
                overlay.hidden = true;
                cancelBtn.removeEventListener("click", onCancel);
                deleteBtn.removeEventListener("click", onOk);
                overlay.removeEventListener("click", onBackdrop);
                document.removeEventListener("keydown", onKey);
                resolve(result);
            }
            function onCancel() { done(false); }
            function onOk() { done(true); }
            function onBackdrop(e) { if (e.target === overlay) done(false); }
            function onKey(e) { if (e.key === "Escape") done(false); }
            cancelBtn.addEventListener("click", onCancel);
            deleteBtn.addEventListener("click", onOk);
            overlay.addEventListener("click", onBackdrop);
            document.addEventListener("keydown", onKey);
            overlay.hidden = false;
        });
    }

    async function deleteMessage(messageId) {
        if (!messageId) return;
        if (!(await confirmDeleteDialog())) return;
        const response = await fetch(urls.delete, {
            method: "POST",
            headers: headers(),
            body: JSON.stringify({ message_id: messageId }),
        });
        const data = await response.json();
        if (data.error) throw new Error(data.error);
        lastMessageSignature = "";
        await loadHistory();
    }

    function setReplyTo(row) {
        const textEl = row.querySelector(".admin-chat-text:not(.is-deleted)");
        const bubble = row.querySelector(".admin-chat-bubble");
        let text = textEl ? textEl.textContent : "";
        if (!text && bubble && bubble.querySelector(".admin-chat-image-link")) text = "📷 Photo";
        replyToId = row.dataset.id || null;
        /* No sender name — privacy: the client never sees the admin's email/username */
        replyTextEl.textContent = text || "";
        replyBar.hidden = false;
        editingBar.hidden = true;
        editingMessageId = null;
        input.focus();
    }

    function cancelReply() {
        replyToId = null;
        replyBar.hidden = true;
        replyTextEl.textContent = "";
    }

    // ── Click a reply quote → scroll to the original message (Messenger-style) ──
    let quoteJumpTimer = null;
    function jumpToQuotedMessage(messageId) {
        if (!messageId || !messagesEl) return;
        const target = messagesEl.querySelector('.admin-chat-msg[data-id="' + String(messageId) + '"]');
        if (!target) return;
        messagesEl.querySelectorAll(".admin-chat-msg.chat-jump").forEach(function (el) {
            el.classList.remove("chat-jump");
        });
        void target.offsetWidth;
        target.classList.add("chat-jump");
        if (quoteJumpTimer) clearTimeout(quoteJumpTimer);
        quoteJumpTimer = setTimeout(function () { target.classList.remove("chat-jump"); }, 1600);
        target.scrollIntoView({ block: "center", behavior: "smooth" });
    }

    function pingTyping() {
        if (!currentSessionId) return;
        const now = Date.now();
        if (now - lastTypingPingAt < 3000) return;
        lastTypingPingAt = now;
        fetch(urls.typingPing, {
            method: "POST",
            headers: headers(),
            body: JSON.stringify({ session_id: currentSessionId, is_typing: true }),
        }).catch(() => {});
    }

    function updatePresence(session) {
        if (typingEl) {
            if (session && session.admin_typing) {
                typingEl.hidden = false;
            } else {
                typingEl.hidden = true;
            }
        }
        setPresence(Boolean(session && session.admin_online));
    }

    function openLightbox(index) {
        if (!lightboxImages.length) return;
        lightboxIndex = (index + lightboxImages.length) % lightboxImages.length;
        const item = lightboxImages[lightboxIndex];
        lightboxImg.src = item.url;
        lightboxCaption.textContent = `${lightboxIndex + 1} / ${lightboxImages.length} — ${item.name}`;
        lightboxEl.hidden = false;
    }

    function closeLightbox() {
        lightboxEl.hidden = true;
        lightboxImg.src = "";
    }

    async function markRead() {
        if (!currentSessionId) return;
        try {
            await fetch(urls.markRead, {
                method: "POST",
                headers: headers(),
                body: JSON.stringify({ session_id: currentSessionId }),
            });
            if (widget.classList.contains("open")) setBadge(0);
        } catch (error) {}
    }

    function pickAdminSession(sessions) {
        const adminSessions = (sessions || []).filter(session => {
            return session.status === "pending_admin" || session.status === "active_admin" || session.status === "closed";
        });
        return adminSessions[0] || null;
    }

    async function loadSessions() {
        const response = await fetch(urls.sessions, {
            headers: { "X-CSRFToken": csrfToken },
        });
        const data = await response.json();
        const session = pickAdminSession(data.sessions);

        const unreadTotal = (data.sessions || [])
            .filter(item => item.status === "pending_admin" || item.status === "active_admin")
            .reduce((total, item) => total + Number(item.unread_count || 0), 0);
        setBadge(unreadTotal);

        if (session) {
            currentSessionId = String(session.id);
            setStatus(session.status, session.assigned_admin);
            return session;
        }

        currentSessionId = null;
        setStatus("idle");
        renderMessages([]);
        return null;
    }

    async function loadHistory() {
        if (!currentSessionId) {
            await loadSessions();
        }
        if (!currentSessionId) return;

        const url = `${urls.history}?session_id=${encodeURIComponent(currentSessionId)}`;
        const response = await fetch(url, {
            headers: { "X-CSRFToken": csrfToken },
        });
        const data = await response.json();
        if (data.session) {
            setStatus(data.session.status, data.session.assigned_admin);
            updatePresence(data.session);
        }
        if (Array.isArray(data.pinned_messages)) setPinned(data.pinned_messages);
        renderMessages(data.messages || []);
        if (widget.classList.contains("open")) await markRead();
    }

    async function ensureAdminSession() {
        if (currentSessionId && (currentStatus === "pending_admin" || currentStatus === "active_admin" || currentStatus === "closed")) {
            return currentSessionId;
        }

        const response = await fetch(urls.request, {
            method: "POST",
            headers: headers(),
            body: JSON.stringify(currentSessionId ? { session_id: currentSessionId } : {}),
        });
        const data = await response.json();
        if (data.error) throw new Error(data.error);
        if (data.session_id) {
            currentSessionId = String(data.session_id);
            setStatus(data.new_status || "active_admin");
        }
        return currentSessionId;
    }

    async function sendMessage(message, imageFiles) {
        await ensureAdminSession();
        if (!currentSessionId) throw new Error("Unable to start admin chat.");

        const formData = new FormData();
        formData.append("session_id", currentSessionId);
        formData.append("message", message || "");
        if (replyToId) formData.append("reply_to_id", replyToId);
        (imageFiles || []).forEach(function (file) {
            formData.append("image", file);
        });

        const response = await fetch(urls.send, {
            method: "POST",
            headers: { "X-CSRFToken": csrfToken },
            body: formData,
        });
        const data = await response.json();
        if (data.error) throw new Error(data.error);
        if (data.session_id) currentSessionId = String(data.session_id);
        if (data.new_status) setStatus(data.new_status);
    }

    function openWidget() {
        widget.classList.add("open");
        const aiWidget = document.getElementById("ai-widget");
        if (aiWidget) aiWidget.classList.remove("active");
        loadHistory().then(function () { setTimeout(scrollBottom, 60); }).catch(function () {});
        setTimeout(() => input.focus(), 80);
    }

    function closeWidget() {
        widget.classList.remove("open");
    }

    toggle.addEventListener("click", function () {
        if (widget.classList.contains("open")) {
            closeWidget();
        } else {
            openWidget();
        }
    });

    closeBtn.addEventListener("click", closeWidget);

    const aiFab = document.getElementById("ai-fab");
    if (aiFab) {
        aiFab.addEventListener("click", closeWidget);
    }

    function startEdit(row) {
        const textEl = row.querySelector(".admin-chat-text");
        if (!textEl || !row.dataset.id) return;
        /* Only one mode at a time — starting an edit cancels any active reply */
        cancelReply();
        editingMessageId = String(row.dataset.id);
        editingTextEl.textContent = textEl.textContent;
        editingBar.hidden = false;
        input.value = textEl.textContent;
        input.focus();
        input.setSelectionRange(input.value.length, input.value.length);
    }

    function cancelEdit() {
        editingMessageId = null;
        editingBar.hidden = true;
        editingTextEl.textContent = "";
        input.value = "";
        input.style.height = "";
    }

    async function submitEdit() {
        const new_text = input.value.trim();
        if (!new_text || !editingMessageId) return;
        const response = await fetch(urls.edit, {
            method: "POST",
            headers: headers(),
            body: JSON.stringify({ message_id: editingMessageId, message: new_text }),
        });
        const data = await response.json();
        if (data.error) throw new Error(data.error);
        cancelEdit();
        lastMessageSignature = "";
        await loadHistory();
    }

    form.addEventListener("submit", async function (event) {
        event.preventDefault();
        if (isSending) return;

        if (editingMessageId) {
            const message = input.value.trim();
            if (!message) return;
            setError("");
            isSending = true;
            sendBtn.disabled = true;
            try {
                await submitEdit();
            } catch (error) {
                setError(error.message || "Could not update message. Please try again.");
            } finally {
                isSending = false;
                sendBtn.disabled = false;
                input.focus();
            }
            return;
        }

        const message = input.value.trim();
        const imageFiles = validateImages(imageInput?.files);
        if (imageFiles === null) return;
        if ((!message && !imageFiles.length) || isSending) return;

        setError("");
        isSending = true;
        sendBtn.disabled = true;
        input.value = "";
        input.style.height = "";

        try {
            await sendMessage(message, imageFiles);
            clearAttachment();
            cancelReply();
            await loadHistory();
        } catch (error) {
            setError(error.message || "Could not send message. Please try again.");
        } finally {
            isSending = false;
            sendBtn.disabled = false;
            input.focus();
        }
    });

    if (imageInput) {
        imageInput.addEventListener("change", function () {
            setError("");
            const files = validateImages(imageInput.files);
            if (files === null || !files.length) {
                clearAttachment();
                return;
            }
            renderAttachmentPreview(files);
        });
    }

    messagesEl.addEventListener("click", async function (event) {
        // Click a reply quote → scroll to the original message (Messenger-style)
        const quoteEl = event.target.closest(".admin-chat-quote[data-reply-to-id]");
        if (quoteEl) {
            event.preventDefault();
            jumpToQuotedMessage(quoteEl.dataset.replyToId);
            return;
        }

        // "See all" on the pinned event line → open the chat info drawer
        const seeAll = event.target.closest(".admin-chat-pin-seeall");
        if (seeAll) {
            event.preventDefault();
            openInfoDrawer();
            return;
        }

        const row = event.target.closest(".admin-chat-msg");

        // Lightbox open (image click)
        const img = event.target.closest("img.admin-chat-image-link");
        if (img && img.dataset.lightboxIndex !== undefined) {
            event.preventDefault();
            openLightbox(Number(img.dataset.lightboxIndex));
            return;
        }

        // Reaction pill click → toggle off own reaction
        const chip = event.target.closest(".admin-chat-reaction-chip");
        if (chip && row && row.dataset.id) {
            event.preventDefault();
            const myEmoji = chip.dataset.myEmoji || "";
            if (!myEmoji) return;
            try {
                await toggleReaction(row.dataset.id, myEmoji);
            } catch (error) {
                setError(error.message || "Could not update reaction.");
            }
            return;
        }

        // Reaction picker option click
        const pick = event.target.closest(".admin-chat-reaction-picker button");
        if (pick && row && row.dataset.id) {
            event.preventDefault();
            closeReactionPicker();
            try {
                await toggleReaction(row.dataset.id, pick.dataset.emoji);
            } catch (error) {
                setError(error.message || "Could not update reaction.");
            }
            return;
        }

        // Action buttons: react / reply / edit / delete
        const act = event.target.closest(".admin-chat-act");
        if (!act || !row || isSending) return;
        event.preventDefault();
        closeReactionPicker();
        const action = act.dataset.act;
        try {
            if (action === "react") {
                showReactionPicker(row);
            } else if (action === "reply") {
                setReplyTo(row);
            } else if (action === "edit") {
                startEdit(row);
            } else if (action === "pin") {
                await togglePin(act.dataset.messageId);
            } else if (action === "delete") {
                await deleteMessage(row.dataset.id);
            }
        } catch (error) {
            setError(error.message || "Action failed. Please try again.");
        }
    });

    // Close reaction picker on outside click
    document.addEventListener("click", function (event) {
        if (event.target && !event.target.isConnected) return;
        if (!event.target.closest(".admin-chat-reaction-picker") && !event.target.closest(".admin-chat-act[data-act='react']")) {
            closeReactionPicker();
        }
    });

    // Pin buttons toggle directly (Messenger-style — walang floating menu).
    // Hanapin sa messagesEl click handler ang "See all" ng pin note.

    if (cancelEditBtn) cancelEditBtn.addEventListener("click", cancelEdit);
    if (cancelReplyBtn) cancelReplyBtn.addEventListener("click", cancelReply);

    // Lightbox controls
    const lightboxCloseBtn = document.getElementById("adminChatLightboxClose");
    const lightboxPrevBtn = document.getElementById("adminChatLightboxPrev");
    const lightboxNextBtn = document.getElementById("adminChatLightboxNext");
    if (lightboxCloseBtn) lightboxCloseBtn.addEventListener("click", closeLightbox);
    if (lightboxPrevBtn) lightboxPrevBtn.addEventListener("click", function () { openLightbox(lightboxIndex - 1); });
    if (lightboxNextBtn) lightboxNextBtn.addEventListener("click", function () { openLightbox(lightboxIndex + 1); });
    if (lightboxEl) {
        lightboxEl.addEventListener("click", function (event) {
            if (event.target === lightboxEl) closeLightbox();
        });
    }

    document.addEventListener("keydown", function (event) {
        if (event.key === "Escape") {
            if (!lightboxEl.hidden) { closeLightbox(); return; }
            closeReactionPicker();
            if (editingMessageId) cancelEdit();
            else if (replyToId) cancelReply();
            return;
        }
        if (!lightboxEl.hidden) {
            if (event.key === "ArrowLeft") openLightbox(lightboxIndex - 1);
            if (event.key === "ArrowRight") openLightbox(lightboxIndex + 1);
        }
    });

    input.addEventListener("input", function () {
        input.style.height = "24px";
        input.style.height = Math.min(input.scrollHeight, 110) + "px";
        pingTyping();
    });

    input.addEventListener("keydown", function (event) {
        if (event.key === "Enter" && !event.shiftKey) {
            event.preventDefault();
            form.requestSubmit();
        }
    });

    document.addEventListener("click", function (event) {
        if (event.target && !event.target.isConnected) return;
        if (!widget.contains(event.target)) closeWidget();
    });

    loadSessions().then(() => {
        if (currentSessionId) loadHistory();
    }).catch(() => {});

    /* ════════════════════════════════════════════════════════════════
       CHAT INFO DRAWER + PINNED MESSAGES (Messenger-style)
       Opens when the header avatar/name is clicked.
       ════════════════════════════════════════════════════════════════ */
    let pinnedMessages = [];
    let mediaItems = [];
    let mediaLightboxList = [];
    let mediaLightboxIndex = 0;

    function pinnedSnippet(pin) {
        if (pin.snippet) return pin.snippet;
        if (pin.has_image) return "📷 Photo";
        return "Message";
    }

    function setPinned(list) {
        const next = Array.isArray(list) ? list : [];
        if (JSON.stringify(next) === JSON.stringify(pinnedMessages)) return;
        pinnedMessages = next;
        renderPinnedList();
        syncPinButtons();
    }

    function renderPinnedList() {
        if (!pinnedList || !pinnedEmpty) return;
        pinnedList.innerHTML = "";
        if (pinnedCountBadge) pinnedCountBadge.textContent = String(pinnedMessages.length);
        if (!pinnedMessages.length) {
            pinnedEmpty.hidden = false;
            return;
        }
        pinnedEmpty.hidden = true;
        pinnedMessages.forEach(function (pin) {
            const item = document.createElement("div");
            item.className = "admin-chat-pinned-item";
            const byWho = pin.pinned_by
                ? `<div class="admin-chat-pinned-meta">Pinned by ${escapeHtml(pin.pinned_by)}${pin.pinned_by_is_admin ? " (Admin)" : ""}${pin.pinned_at ? " · " + escapeHtml(pin.pinned_at) : ""}</div>`
                : "";
            // Ikaw lang (client) ang nakapin mo ang pwedeng mag-unpin — itago
            // ang X kapag si admin ang nag-pin ng mensahe.
            const unpinHtml = !pin.pinned_by_is_admin
                ? `<button type="button" class="admin-chat-pinned-item-unpin" data-unpin-id="${pin.id}" title="Unpin" aria-label="Unpin message"><svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg></button>`
                : "";
            item.innerHTML =
                `<div class="admin-chat-pinned-item-icon">${ICON_PIN}</div>` +
                `<div class="admin-chat-pinned-item-body">` +
                    `<div class="admin-chat-pinned-sender">${escapeHtml(pin.sender_name || "")}</div>` +
                    `<div class="admin-chat-pinned-text">${escapeHtml(pinnedSnippet(pin))}</div>` +
                    byWho +
                `</div>` +
                unpinHtml;
            item.addEventListener("click", function (event) {
                if (event.target.closest(".admin-chat-pinned-item-unpin")) return;
                jumpToQuotedMessage(pin.id);
            });
            pinnedList.appendChild(item);
        });
    }

    function syncPinButtons() {
        const pinnedMap = {};
        pinnedMessages.forEach(function (pin) { pinnedMap[pin.id] = pin; });
        messagesEl.querySelectorAll(".admin-chat-msg").forEach(function (row) {
            const pin = (row.dataset.id && pinnedMap[row.dataset.id]) || null;
            const isPinned = Boolean(pin);
            row.classList.toggle("pinned-row", isPinned);
            const btn = row.querySelector(".admin-chat-act.pin-act");
            if (btn) {
                // Ikaw lang (client) ang pwedeng mag-unpin ng pin mo — itago ang
                // action kapag si admin ang nag-pin ng mensahe.
                btn.hidden = isPinned && Boolean(pin.pinned_by_is_admin);
                btn.classList.toggle("active", isPinned);
                btn.title = isPinned ? "Unpin message" : "Pin message";
                btn.setAttribute("aria-label", isPinned ? "Unpin message" : "Pin message");
            }
            const bubble = row.querySelector(".admin-chat-bubble");
            if (bubble) {
                let flag = bubble.querySelector(".pin-flag");
                if (isPinned && !flag) {
                    flag = document.createElement("span");
                    flag.setAttribute("aria-hidden", "true");
                    flag.innerHTML = PIN_FLAG_SVG + "<span>Pinned</span>";
                    bubble.insertBefore(flag, bubble.firstChild);
                }
                if (isPinned && flag) {
                    // Naka-tusok sa gilid ng nag-pin: admin → kaliwa, client → kanan
                    flag.className = "pin-flag " + (pin.pinned_by_is_admin ? "flag-left" : "flag-right");
                } else if (!isPinned && flag) {
                    flag.remove();
                }
            }
        });
        renderPinEventLines();
    }

    /* ── "You pinned a message. See all" system line under each pinned message ── */
    function renderPinEventLines() {
        messagesEl.querySelectorAll(".admin-chat-pin-note").forEach(function (el) { el.remove(); });
        if (!pinnedMessages.length) return;
        pinnedMessages.forEach(function (pin) {
            const target = messagesEl.querySelector('.admin-chat-msg[data-id="' + pin.id + '"]');
            if (!target) return;
            const line = document.createElement("div");
            line.className = "admin-chat-pin-note";
            const who = pin.pinned_by_is_admin
                ? "Admin pinned a message."
                : "You pinned a message.";
            line.innerHTML = '<span class="admin-chat-pin-note-text">' + escapeHtml(who) + '</span>' +
                '<button type="button" class="admin-chat-pin-seeall">See all</button>';
            target.after(line);
        });
    }

    function renderMedia(items) {
        mediaItems = Array.isArray(items) ? items : [];
        if (mediaCountBadge) mediaCountBadge.textContent = String(mediaItems.length);
        if (!mediaGrid || !mediaEmpty) return;
        mediaGrid.innerHTML = "";
        if (!mediaItems.length) {
            mediaEmpty.hidden = false;
            return;
        }
        mediaEmpty.hidden = true;
        mediaLightboxList = [];
        mediaItems.forEach(function (item) {
            const idx = mediaLightboxList.length;
            mediaLightboxList.push(item);
            const cell = document.createElement("button");
            cell.type = "button";
            cell.className = "admin-chat-media-thumb";
            cell.title = (item.name || "Chat image") + " — " + (item.sent_at || "");
            cell.innerHTML =
                `<img src="${escapeHtml(item.url)}" alt="${escapeHtml(item.name || "Chat image")}" loading="lazy">` +
                `<span class="admin-chat-media-overlay">${escapeHtml(item.sent_at || "")}</span>`;
            cell.addEventListener("click", function () { openMediaLightbox(idx); });
            mediaGrid.appendChild(cell);
        });
    }

    function loadMedia() {
        if (!currentSessionId) return;
        fetch(`${urls.media}?session_id=${encodeURIComponent(currentSessionId)}`, {
            headers: { "X-CSRFToken": csrfToken },
        })
            .then(function (r) { return r.ok ? r.json() : null; })
            .then(function (data) {
                if (data && Array.isArray(data.media)) renderMedia(data.media);
            })
            .catch(function () {});
    }

    function openMediaLightbox(index) {
        if (!mediaLightboxList.length || !mediaLightbox) return;
        const total = mediaLightboxList.length;
        mediaLightboxIndex = ((index % total) + total) % total;
        const item = mediaLightboxList[mediaLightboxIndex];
        const mediaLightboxImg = document.getElementById("adminChatMediaLightboxImg");
        const mediaLightboxCaption = document.getElementById("adminChatMediaLightboxCaption");
        if (mediaLightboxImg) mediaLightboxImg.src = item.url;
        if (mediaLightboxCaption) mediaLightboxCaption.textContent = (mediaLightboxIndex + 1) + " / " + total + " — " + (item.name || "Chat image");
        mediaLightbox.hidden = false;
    }

    function openInfoDrawer() {
        if (!infoDrawer) return;
        infoDrawer.hidden = false;
        if (infoBackdrop) infoBackdrop.hidden = false;
        if (infoTrigger) infoTrigger.setAttribute("aria-expanded", "true");
        loadMedia();
    }

    function closeInfoDrawer() {
        if (!infoDrawer) return;
        infoDrawer.hidden = true;
        if (infoBackdrop) infoBackdrop.hidden = true;
        if (infoTrigger) infoTrigger.setAttribute("aria-expanded", "false");
    }

    function togglePin(messageId) {
        const id = Number(messageId);
        if (!id || !urls.pin) return Promise.resolve();
        return fetch(urls.pin, {
            method: "POST",
            headers: headers(),
            body: JSON.stringify({ message_id: id }),
        })
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (data.error) { setError(data.error); return; }
                if (Array.isArray(data.pinned_messages)) setPinned(data.pinned_messages);
                lastMessageSignature = ""; // let the next poll re-render pin states
                return loadHistory(); // instant re-render with the new pin flag + event line
            })
            .catch(function () { setError("Could not update pin."); });
    }

    if (infoTrigger) infoTrigger.addEventListener("click", function () {
        if (!infoDrawer || infoDrawer.hidden) openInfoDrawer();
        else closeInfoDrawer();
    });
    if (infoCloseBtn) infoCloseBtn.addEventListener("click", closeInfoDrawer);
    if (infoBackdrop) infoBackdrop.addEventListener("click", closeInfoDrawer);
    if (pinnedList) {
        pinnedList.addEventListener("click", function (event) {
            const unpinBtn = event.target.closest(".admin-chat-pinned-item-unpin");
            if (unpinBtn) {
                event.preventDefault();
                togglePin(unpinBtn.dataset.unpinId);
            }
        });
    }

    // Media gallery lightbox controls
    if (mediaLightbox) {
        const mediaLightboxClose = document.getElementById("adminChatMediaLightboxClose");
        const mediaLightboxPrev = document.getElementById("adminChatMediaLightboxPrev");
        const mediaLightboxNext = document.getElementById("adminChatMediaLightboxNext");
        const mediaLightboxImg = document.getElementById("adminChatMediaLightboxImg");
        function closeMediaLightbox() {
            mediaLightbox.hidden = true;
            if (mediaLightboxImg) mediaLightboxImg.src = "";
        }
        if (mediaLightboxClose) mediaLightboxClose.addEventListener("click", closeMediaLightbox);
        if (mediaLightboxPrev) mediaLightboxPrev.addEventListener("click", function () { openMediaLightbox(mediaLightboxIndex - 1); });
        if (mediaLightboxNext) mediaLightboxNext.addEventListener("click", function () { openMediaLightbox(mediaLightboxIndex + 1); });
        mediaLightbox.addEventListener("click", function (event) {
            if (event.target === mediaLightbox) closeMediaLightbox();
        });
    }

    document.addEventListener("keydown", function (event) {
        if (event.key === "Escape") {
            if (mediaLightbox && !mediaLightbox.hidden) { mediaLightbox.hidden = true; return; }
            if (lightboxEl && !lightboxEl.hidden) { closeLightbox(); return; }
            if (infoDrawer && !infoDrawer.hidden) closeInfoDrawer();
        }
        if (mediaLightbox && !mediaLightbox.hidden) {
            if (event.key === "ArrowLeft") openMediaLightbox(mediaLightboxIndex - 1);
            if (event.key === "ArrowRight") openMediaLightbox(mediaLightboxIndex + 1);
        }
        if (lightboxEl && !lightboxEl.hidden) {
            if (event.key === "ArrowLeft") openLightbox(lightboxIndex - 1);
            if (event.key === "ArrowRight") openLightbox(lightboxIndex + 1);
        }
    });

    setInterval(function () {
        if (widget.classList.contains("open")) {
            loadHistory().catch(() => {});
        } else {
            loadSessions().catch(() => {});
        }
    }, 7000);
})();
