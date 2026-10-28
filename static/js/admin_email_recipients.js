/* Progressive enhancement: comma-separated email input becomes removable tags. */
window.AdminEmailRecipients = {
    init(input) {
        if (!input) return null;
        const wrapper = input.closest('[data-email-recipients]');
        if (!wrapper) return null;
        const tags = wrapper.querySelector('.cfg-email-tags');
        const error = document.getElementById(`${input.id}_error`);
        const status = document.getElementById(`${input.id}_status`);
        const field = document.createElement('input');
        field.type = 'hidden'; field.name = input.name; field.value = input.value;
        input.before(field); input.removeAttribute('name');
        input.dataset.fieldName = field.name;
        input.setAttribute('aria-keyshortcuts', 'Enter');
        wrapper.classList.add('is-enhanced'); tags.hidden = false;
        const probe = document.createElement('input'); probe.type = 'email';
        const split = value => value.split(/[,;\n\r]+/).map(value => value.trim()).filter(Boolean);
        const unique = values => {
            const known = new Map();
            values.forEach(value => { if (!known.has(value.toLowerCase())) known.set(value.toLowerCase(), value); });
            return [...known.values()];
        };
        const valid = value => {
            probe.value = value;
            return probe.checkValidity() && /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(value);
        };
        let emails = [];
        const sync = (notify = true) => {
            field.value = unique([...emails, ...split(input.value)]).join(', ');
            if (notify) field.dispatchEvent(new Event('input', {bubbles:true}));
        };
        const showError = text => {
            error.textContent = text;
            input.setAttribute('aria-invalid', 'true');
            input.focus();
            return false;
        };
        const render = () => {
            tags.replaceChildren();
            emails.forEach(email => {
                const tag = document.createElement('span'); tag.className = 'cfg-email-tag';
                const label = document.createElement('span'); label.textContent = email;
                const remove = document.createElement('button'); remove.type = 'button';
                remove.className = 'cfg-email-remove';
                remove.setAttribute('aria-label', `Remove ${email}`);
                remove.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m7 7 10 10M17 7 7 17"/></svg>';
                remove.addEventListener('click', () => {
                    emails = emails.filter(value => value !== email);
                    render(); sync(); input.focus(); status.textContent = `${email} removed.`;
                });
                tag.append(label, remove); tags.append(tag);
            });
            input.placeholder = emails.length ? 'Add another email' : 'Add an email address';
        };
        const commit = () => {
            const added = split(input.value);
            const all = unique([...emails, ...added]);
            sync();
            if (all.some(email => !valid(email))) return showError('Enter a valid email address.');
            if (all.join(', ').length > 500) return showError('Keep the recipient list within 500 characters.');
            const duplicates = emails.length + added.length - all.length;
            emails = all; input.value = ''; render(); sync();
            status.textContent = duplicates ? 'That email is already in the recipient list.' : added.length ? 'Email added.' : '';
            return true;
        };
        const restore = () => {
            emails = unique(split(field.value)); input.value = ''; render(); sync(false);
            status.textContent = '';
        };
        input.addEventListener('input', () => { sync(); status.textContent = ''; });
        input.addEventListener('keydown', event => {
            if (event.isComposing) return;
            if (event.key === 'Enter' || event.key === ',') {
                event.preventDefault(); commit();
            } else if (event.key === 'Backspace' && !input.value && emails.length) {
                event.preventDefault(); emails.pop(); render(); sync();
            }
        });
        input.addEventListener('paste', event => {
            const text = event.clipboardData?.getData('text');
            if (!text || !/[,;\n\r]/.test(text)) return;
            event.preventDefault();
            const start = input.selectionStart ?? input.value.length;
            const end = input.selectionEnd ?? input.value.length;
            input.value = input.value.slice(0, start) + text.replace(/[;\n\r]+/g, ',') + input.value.slice(end);
            commit();
        });
        input.addEventListener('blur', () => {
            if (!input.value.trim()) return;
            const all = [...emails, ...split(input.value)];
            // Do not pull focus back while someone moves to another setting.
            if (all.every(valid) && unique(all).join(', ').length <= 500) commit();
        });
        wrapper.addEventListener('click', event => { if (event.target === wrapper) input.focus(); });
        restore();
        return {field, input, commit, restore};
    }
};
