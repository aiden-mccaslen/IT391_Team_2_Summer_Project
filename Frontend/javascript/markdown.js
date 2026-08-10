/* A very small Markdown renderer.
 *
 * The monthly review and the profile arrive from the backend as Markdown, and
 * the coach's replies contain **bold** and lists too. This covers exactly what
 * those produce -- headings, bullets, bold, horizontal rules, paragraphs -- and
 * nothing else. No library: nothing in this project pulls one in, and a full
 * parser would be more code than the pages that use it.
 *
 * Everything is escaped BEFORE any markup is added, so text from the model can
 * never inject HTML. The inline pass only ever re-introduces <strong> and <em>,
 * which it builds itself.
 */

function escapeHtml(text) {
    return String(text)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
}

/* Bold and italic, applied to already-escaped text. Bold runs first so that the
 * single-asterisk rule cannot eat the halves of a ** pair. */
function inline(text) {
    return text
        .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
        .replace(/(^|[^*])\*([^*]+)\*/g, "$1<em>$2</em>");
}

function renderMarkdown(source) {
    const lines = String(source || "").split(/\r?\n/);
    const out = [];
    let listOpen = false;
    let paragraph = [];

    function closeParagraph() {
        if (paragraph.length) {
            out.push(`<p>${inline(paragraph.join(" "))}</p>`);
            paragraph = [];
        }
    }

    function closeList() {
        if (listOpen) {
            out.push("</ul>");
            listOpen = false;
        }
    }

    lines.forEach(function (raw) {
        const line = escapeHtml(raw.trim());

        if (!line) {
            closeParagraph();
            closeList();
            return;
        }

        // Horizontal rule.
        if (/^---+$/.test(line)) {
            closeParagraph();
            closeList();
            out.push("<hr>");
            return;
        }

        // Headings: #, ##, ###.
        const heading = line.match(/^(#{1,3})\s+(.*)$/);
        if (heading) {
            closeParagraph();
            closeList();
            const level = heading[1].length;
            out.push(`<h${level}>${inline(heading[2])}</h${level}>`);
            return;
        }

        // Bullets: "- " or "* ".
        const bullet = line.match(/^[-*]\s+(.*)$/);
        if (bullet) {
            closeParagraph();
            if (!listOpen) {
                out.push("<ul>");
                listOpen = true;
            }
            out.push(`<li>${inline(bullet[1])}</li>`);
            return;
        }

        // Anything else is prose; consecutive lines join into one paragraph.
        closeList();
        paragraph.push(line);
    });

    closeParagraph();
    closeList();

    return out.join("\n");
}
