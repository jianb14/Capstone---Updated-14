/* Receives HTML-escaped text from the chat's trust filter. Images stay as tokens. */
(function () {
    'use strict';

    window.renderAiMarkdown = function (escapedText) {
        const root = document.createElement('div');
        const stack = [];
        let paragraph = null;
        const inline = value => value
            .replace(/\*\*([^\n]+?)\*\*|__([^\n]+?)__/g, (_, stars, underscores) => `<strong>${stars || underscores}</strong>`)
            .replace(/(?<![\w*])\*([^*\n]+?)\*(?![\w*])/g, '<em>$1</em>')
            .replace(/(?<![\w_])_([^_\n]+?)_(?![\w_])/g, '<em>$1</em>');
        const lines = escapedText.replace(/<br\s*\/?\s*>/gi, '\n')
            .replace(/(\u0000AIIMG\d+\u0000)/g, '\n$1\n').replace(/\r\n?/g, '\n').split('\n');

        for (const raw of lines) {
            const line = raw.trim();
            if (!line) {
                paragraph = null;
                // Keep the list alive across spacing and nested inclusion lists.
                continue;
            }
            if (/^\u0000AIIMG\d+\u0000$/.test(line)) {
                stack.length = 0;
                paragraph = null;
                root.appendChild(document.createTextNode(line));
                continue;
            }
            const match = raw.match(/^(\s*)(?:(\d+)[.)]|([-*•]))\s+(.+)$/);
            let indent = raw.match(/^\s*/)[0].replace(/\t/g, '    ').length;
            if (match) {
                const type = match[2] ? 'ol' : 'ul';
                // Models sometimes omit indentation from package inclusions.
                // Attach those bullets to the current numbered package.
                const parent = [...stack].reverse().find(list => list.type === 'ol' && list.indent === indent);
                if (type === 'ul' && parent?.item) indent += 2;
                while (stack.length && (stack.at(-1).indent > indent ||
                    (stack.at(-1).indent === indent && stack.at(-1).type !== type))) stack.pop();
                if (!stack.length || stack.at(-1).indent < indent) {
                    const list = document.createElement(type);
                    list.className = 'ai-reply-list';
                    if (type === 'ol' && Number(match[2]) > 1) list.start = Math.min(Number(match[2]), 9999);
                    (stack.at(-1)?.item || root).appendChild(list);
                    stack.push({ element: list, type, indent, item: null });
                }
                const current = stack.at(-1);
                const item = document.createElement('li');
                item.innerHTML = inline(match[4]);
                current.element.appendChild(item);
                current.item = item;
                paragraph = null;
                continue;
            }
            const parent = stack.at(-1);
            if (!parent || indent <= parent.indent) stack.length = 0;
            if (!paragraph) {
                paragraph = document.createElement('p');
                paragraph.className = 'ai-reply-paragraph';
                (stack.at(-1)?.item || root).appendChild(paragraph);
            } else {
                paragraph.appendChild(document.createElement('br'));
            }
            paragraph.insertAdjacentHTML('beforeend', inline(line));
        }
        return root.innerHTML;
    };
})();
