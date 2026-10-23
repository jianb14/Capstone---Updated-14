/* The guide builds a reviewable message; generation uses the existing chat flow. */
(function () {
    'use strict';

    window.initAiDesignGuide = function ({ onGenerate, userId }) {
        const guide = document.getElementById('ai-design-guide');
        const openButton = document.getElementById('ai-guide-open');
        const main = document.querySelector('.ai-main-chat');
        const form = document.getElementById('ai-guide-form');
        if (!guide || !openButton || !form) return;

        const title = document.getElementById('ai-guide-title');
        const description = document.getElementById('ai-guide-description');
        const error = document.getElementById('ai-guide-error');
        const back = document.getElementById('ai-guide-back');
        const next = document.getElementById('ai-guide-next');
        const preview = document.getElementById('ai-guide-preview');
        const other = document.getElementById('ai-guide-other');
        const theme = document.getElementById('ai-guide-theme');
        const colors = document.getElementById('ai-guide-colors');
        const styleNote = document.getElementById('ai-guide-style-note');
        const input = document.getElementById('ai-widget-input');
        const steps = [
            ['Occasion', "What's the occasion?", 'Choose an occasion, or add your own.'],
            ['Style', 'Choose your theme and colors', "Have something in mind? Add it here, or let us suggest a style."],
            ['Details', 'Make it personal', 'Add a name, a milestone, or a few finishing touches. Everything here is optional.'],
            ['Review', 'Review your design idea', 'Read your description, then select Generate design when you are ready.']
        ];
        let step = 0;
        let previousValues = '';
        let returnFocus = openButton;
        const draftKey = `balloorina-ai-guide:${userId || 'customer'}`;
        const draftNotice = document.getElementById('ai-guide-draft');
        const styles = document.getElementById('ai-guide-style-options');
        const suggestButton = document.getElementById('ai-guide-suggest');
        const fields = ['other', 'theme', 'colors', 'name', 'age', 'details', 'preview'];
        const choices = {
            Birthday: [['Butterfly', 'Pink and lavender', '#efb9cc', '#c9b6e4'], ['Outer space', 'Navy and silver', '#283952', '#c8cbd1'], ['Minimalist', 'White and gold', '#f9f7f1', '#c5a35c']],
            Christening: [['Little angel', 'White and gold', '#f9f7f1', '#c5a35c'], ['Clouds', 'Powder blue and white', '#b6d3e6', '#f9f7f1'], ['Soft floral', 'Ivory and sage', '#f4edde', '#a8b69c']],
            Wedding: [['Classic elegance', 'Ivory and gold', '#f4edde', '#c5a35c'], ['Garden', 'Sage and white', '#a8b69c', '#f9f7f1'], ['Romantic floral', 'Blush and champagne', '#eac4c1', '#d6c5a7']],
            Debut: [['Elegant rose', 'Blush and gold', '#eac4c1', '#c5a35c'], ['Starry night', 'Navy and silver', '#283952', '#c8cbd1'], ['Butterfly', 'Lavender and white', '#c9b6e4', '#f9f7f1']],
            Anniversary: [['Classic celebration', 'White and gold', '#f9f7f1', '#c5a35c'], ['Romantic floral', 'Burgundy and blush', '#753541', '#eac4c1'], ['Modern', 'Black and silver', '#272727', '#c8cbd1']],
            other: [['Modern neutral', 'Cream and taupe', '#eee4d1', '#b1a18d'], ['Minimalist', 'White and gold', '#f9f7f1', '#c5a35c'], ['Garden floral', 'Sage and blush', '#a8b69c', '#eac4c1']]
        };
        const moreChoices = {
            Birthday: [['Safari', 'Sage and beige', '#a8b69c', '#ddd0b7'], ['Under the sea', 'Aqua and lavender', '#8bcac8', '#c9b6e4'], ['Dinosaur', 'Olive and sand', '#7b8450', '#ddd0b7'], ['Princess', 'Blush and gold', '#eac4c1', '#c5a35c'], ['Race day', 'Red and black', '#bd4545', '#272727'], ['Rainbow', 'Peach and sky blue', '#efbea6', '#b6d3e6']],
            Christening: [['Teddy bear', 'Beige and cream', '#ddd0b7', '#eee4d1'], ['Moon and stars', 'Ivory and silver', '#f4edde', '#c8cbd1'], ['Botanical', 'Sage and cream', '#a8b69c', '#eee4d1'], ['Soft butterflies', 'Blush and ivory', '#eac4c1', '#f4edde'], ['Little dove', 'White and powder blue', '#f9f7f1', '#b6d3e6'], ['Gentle sunshine', 'Butter yellow and white', '#efdfa0', '#f9f7f1']],
            Wedding: [['Modern arch', 'White and black', '#f9f7f1', '#272727'], ['Terracotta garden', 'Terracotta and cream', '#b97860', '#eee4d1'], ['Pearl', 'Ivory and champagne', '#f4edde', '#d6c5a7'], ['Rustic botanical', 'Olive and beige', '#7b8450', '#ddd0b7'], ['Lavender garden', 'Lavender and sage', '#c9b6e4', '#a8b69c'], ['Evening elegance', 'Burgundy and gold', '#753541', '#c5a35c']],
            Debut: [['Enchanted garden', 'Sage and blush', '#a8b69c', '#eac4c1'], ['Disco', 'Silver and pink', '#c8cbd1', '#efb9cc'], ['Royal celebration', 'Emerald and gold', '#276b58', '#c5a35c'], ['Modern glam', 'Black and champagne', '#272727', '#d6c5a7'], ['Dreamy clouds', 'Powder blue and white', '#b6d3e6', '#f9f7f1'], ['Peach blossom', 'Peach and ivory', '#efbea6', '#f4edde']],
            Anniversary: [['Golden memories', 'Champagne and gold', '#d6c5a7', '#c5a35c'], ['Silver celebration', 'White and silver', '#f9f7f1', '#c8cbd1'], ['Garden romance', 'Sage and ivory', '#a8b69c', '#f4edde'], ['Elegant evening', 'Navy and gold', '#283952', '#c5a35c'], ['Soft rose', 'Dusty rose and cream', '#be8e96', '#eee4d1'], ['Warm sunset', 'Terracotta and blush', '#b97860', '#eac4c1']],
            other: [['Starry celebration', 'Navy and gold', '#283952', '#c5a35c'], ['Tropical', 'Emerald and peach', '#276b58', '#efbea6'], ['Modern monochrome', 'Black and white', '#272727', '#f9f7f1'], ['Soft pastels', 'Lavender and sky blue', '#c9b6e4', '#b6d3e6'], ['Warm earth', 'Terracotta and cream', '#b97860', '#eee4d1'], ['Silver sparkle', 'White and silver', '#f9f7f1', '#c8cbd1']]
        };
        const previousSuggestions = new Map();

        function saveDraft() {
            const values = Object.fromEntries(fields.map(key => [key, document.getElementById(`ai-guide-${key}`).value]));
            const occasion = form.querySelector('[name="guide_occasion"]:checked')?.value || '';
            try {
                if (!occasion && fields.every(key => !values[key])) {
                    localStorage.removeItem(draftKey);
                    draftNotice.hidden = true;
                    return;
                }
                localStorage.setItem(draftKey, JSON.stringify({ values, occasion, step, previousValues, savedAt: Date.now() }));
                draftNotice.hidden = false;
            } catch (_) { draftNotice.hidden = true; }
        }

        function restoreDraft() {
            try {
                const draft = JSON.parse(localStorage.getItem(draftKey) || 'null');
                if (!draft || Date.now() - draft.savedAt > 7 * 86400000) {
                    localStorage.removeItem(draftKey);
                    return;
                }
                fields.forEach(key => {
                    if (typeof draft.values?.[key] === 'string') {
                        const field = document.getElementById(`ai-guide-${key}`);
                        field.value = draft.values[key].slice(0, field.maxLength);
                    }
                });
                const selected = Array.from(form.querySelectorAll('[name="guide_occasion"]')).find(field => field.value === draft.occasion);
                if (selected) selected.checked = true;
                document.getElementById('ai-guide-other-wrap').hidden = draft.occasion !== 'other';
                step = selected ? Math.max(0, Math.min(3, Number(draft.step) || 0)) : 0;
                previousValues = typeof draft.previousValues === 'string' ? draft.previousValues : '';
                draftNotice.hidden = false;
            } catch (_) { /* Storage is optional; the form remains usable. */ }
        }

        function showStyles() {
            const occasion = form.querySelector('[name="guide_occasion"]:checked')?.value || 'other';
            const key = choices[occasion] ? occasion : 'other';
            const previous = previousSuggestions.get(key) || [];
            const pool = [...choices[key], ...moreChoices[key]].filter(choice => !previous.includes(choice[0]));
            for (let index = pool.length - 1; index > 0; index--) {
                const swap = Math.floor(Math.random() * (index + 1));
                [pool[index], pool[swap]] = [pool[swap], pool[index]];
            }
            const suggestions = pool.slice(0, 3);
            previousSuggestions.set(key, suggestions.map(choice => choice[0]));
            styles.replaceChildren();
            suggestions.forEach(([label, palette, first, second]) => {
                const button = document.createElement('button');
                button.type = 'button';
                button.className = 'ai-guide-style-choice';
                button.setAttribute('aria-pressed', String(theme.value === label && colors.value === palette));
                const swatches = document.createElement('span');
                swatches.className = 'ai-guide-swatches';
                swatches.setAttribute('aria-hidden', 'true');
                [first, second].forEach(color => { const swatch = document.createElement('i'); swatch.style.backgroundColor = color; swatches.appendChild(swatch); });
                const text = document.createElement('span');
                const heading = document.createElement('strong');
                const caption = document.createElement('small');
                heading.textContent = label;
                caption.textContent = palette;
                text.append(heading, caption);
                button.append(swatches, text);
                button.addEventListener('click', () => {
                    theme.value = label;
                    colors.value = palette;
                    styles.querySelectorAll('button').forEach(option => option.setAttribute('aria-pressed', String(option === button)));
                    styleNote.textContent = `${label} selected. You can edit the theme or colors before continuing.`;
                    saveDraft();
                });
                styles.appendChild(button);
            });
            styles.hidden = false;
            suggestButton.setAttribute('aria-expanded', 'true');
            suggestButton.textContent = 'Show more ideas';
            styleNote.textContent = 'Select a style to fill in the theme and colors. You can change them at any time.';
        }

        restoreDraft();
        form.addEventListener('input', saveDraft);
        form.addEventListener('change', saveDraft);
        document.getElementById('ai-guide-reset').addEventListener('click', () => {
            form.reset();
            previousValues = '';
            step = 0;
            styles.hidden = true;
            suggestButton.setAttribute('aria-expanded', 'false');
            suggestButton.textContent = 'Help me choose';
            document.getElementById('ai-guide-other-wrap').hidden = true;
            saveDraft();
            showStep();
        });

        function clearError() {
            error.hidden = true;
            error.textContent = '';
            guide.querySelectorAll('[aria-invalid]').forEach(el => el.removeAttribute('aria-invalid'));
        }

        function showError(message, field) {
            error.textContent = message;
            error.hidden = false;
            if (field) {
                field.setAttribute('aria-invalid', 'true');
                field.focus();
            }
        }

        function buildDescription() {
            const selected = form.querySelector('[name="guide_occasion"]:checked');
            const clean = value => value.trim().replace(/\s+/g, ' ').replace(/[.!?]+$/, '');
            const occasions = {
                Birthday: 'a birthday celebration', Christening: 'a christening',
                Wedding: 'a wedding', Debut: 'a debut celebration', Anniversary: 'an anniversary celebration'
            };
            const occasion = selected?.value === 'other' ? `the ${clean(other.value)} celebration` : occasions[selected?.value];
            const name = document.getElementById('ai-guide-name').value.trim();
            const age = clean(document.getElementById('ai-guide-age').value);
            const details = clean(document.getElementById('ai-guide-details').value);
            const chosenTheme = clean(theme.value);
            const chosenColors = clean(colors.value);
            let opening = `Create a balloon backdrop design for ${occasion}`;
            if (chosenTheme) opening += ` with a ${chosenTheme} theme`;
            if (chosenColors) opening += ` in ${chosenColors}`;
            const sentences = [opening + '.'];
            if (!chosenTheme && !chosenColors) sentences.push('Suggest a suitable theme and matching colors.');
            else if (!chosenTheme) sentences.push('Suggest a theme that complements these colors.');
            else if (!chosenColors) sentences.push('Choose colors that suit the theme.');
            if (name) sentences.push(`Display "${name}" on the backdrop.`);
            if (age) {
                if (selected?.value === 'Birthday' && /^\d{1,3}$/.test(age)) {
                    sentences.push(`The celebrant is ${age} ${age === '1' ? 'year' : 'years'} old.`);
                } else {
                    sentences.push(`Include "${age}" as the age or milestone.`);
                }
            }
            if (details) sentences.push(details.charAt(0).toUpperCase() + details.slice(1) + '.');
            return sentences.join(' ');
        }

        function showStep() {
            clearError();
            guide.querySelectorAll('[data-guide-step]').forEach((panel, index) => { panel.hidden = index !== step; });
            title.textContent = steps[step][1];
            description.textContent = steps[step][2];
            document.getElementById('ai-guide-progress').textContent = `Step ${step + 1} of 4 · ${steps[step][0]}`;
            guide.querySelectorAll('.ai-guide-track span').forEach((segment, index) => {
                segment.classList.toggle('is-complete', index <= step);
            });
            back.hidden = step === 0;
            next.querySelector('[data-guide-next-label]').textContent = step === 3 ? 'Generate design' : 'Next';
            if (step === 3) {
                const message = buildDescription();
                // Keep manual edits when the customer goes back without changing answers.
                if (message !== previousValues) preview.value = message;
                previousValues = message;
            }
            guide.querySelector('.ai-guide-content').scrollTop = 0;
            title.focus({ preventScroll: true });
            if (step === 3) preview.scrollTop = 0;
            saveDraft();
        }

        function close() {
            guide.hidden = true;
            main.classList.remove('ai-guide-is-open');
            openButton.setAttribute('aria-expanded', 'false');
            returnFocus.focus({ preventScroll: true });
            saveDraft();
        }

        function open() {
            returnFocus = document.activeElement;
            guide.hidden = false;
            main.classList.add('ai-guide-is-open');
            openButton.setAttribute('aria-expanded', 'true');
            showStep();
        }

        openButton.addEventListener('click', () => guide.hidden ? open() : close());
        document.getElementById('ai-guide-exit').addEventListener('click', close);
        guide.addEventListener('keydown', event => {
            if (event.key === 'Escape') {
                event.preventDefault();
                event.stopPropagation();
                close();
            }
        });
        form.addEventListener('change', event => {
            if (event.target.name !== 'guide_occasion') return;
            const isOther = event.target.value === 'other';
            document.getElementById('ai-guide-other-wrap').hidden = !isOther;
            clearError();
            styles.hidden = true;
            suggestButton.setAttribute('aria-expanded', 'false');
            suggestButton.textContent = 'Help me choose';
            if (isOther) other.focus();
        });
        [theme, colors].forEach(field => field.addEventListener('input', () => {
            styleNote.textContent = 'Leave either field blank for a suggestion.';
        }));
        suggestButton.addEventListener('click', showStyles);
        back.addEventListener('click', () => { step -= 1; showStep(); });
        form.addEventListener('submit', event => {
            event.preventDefault();
            clearError();
            if (step === 0) {
                const selected = form.querySelector('[name="guide_occasion"]:checked');
                if (!selected) {
                    showError('Choose an occasion to continue.', form.querySelector('[name="guide_occasion"]'));
                    return;
                }
                if (selected.value === 'other' && !other.value.trim()) {
                    showError('Enter your occasion, such as Graduation.', other);
                    return;
                }
            }
            if (step < 3) {
                step += 1;
                showStep();
                return;
            }
            const message = preview.value.trim();
            if (!message) {
                showError('Add a description of the design you would like.', preview);
                return;
            }
            const result = onGenerate(message);
            if (result !== true) {
                showError(result || 'Your description could not be sent. Please try again.', next);
                return;
            }
            close();
            // Keep answers and edited preview available for another design.
            document.getElementById('ai-chat-box').focus({ preventScroll: true });
        });

        document.getElementById('ai-guide-example').addEventListener('click', () => {
            if (!guide.hidden) close();
            const sample = 'Create a balloon backdrop design for Sofia\'s 7th birthday with a butterfly theme in pink and lavender. Include a balloon garland and butterfly decorations.';
            // Preserve an unfinished message; insert the example at the cursor.
            const spacer = input.value ? '\n' : '';
            input.setRangeText(spacer + sample, input.selectionStart, input.selectionEnd, 'end');
            input.dispatchEvent(new Event('input'));
            input.focus();
        });
    };
})();
