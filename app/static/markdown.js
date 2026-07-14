(function () {
  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;");
  }

  function inlineMarkdown(value) {
    return escapeHtml(value)
      .replace(/`([^`]+)`/g, "<code>$1</code>")
      .replace(/\$([^\s$](?:[^$\n]*[^\s$])?)\$/g, '<span class="math-inline">$1</span>')
      .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
      .replace(/\*([^*]+)\*/g, "<em>$1</em>")
      .replace(
        /!\[([^\]]*)\]\(((?:https?:\/\/|\/)[^)\s]+)\)/g,
        '<img src="$2" alt="$1" loading="lazy">',
      )
      .replace(
        /\[\[(\d+)\]\]\((https?:\/\/[^)\s]+)\)/g,
        '<a class="citation-link" href="$2" target="_blank" rel="noreferrer" title="$2">[$1]</a>',
      )
      .replace(
        /\[\(([^()\n]{1,120})\)\]\((https?:\/\/[^)\s]+)\)/g,
        '<a class="citation-link" href="$2" target="_blank" rel="noreferrer" title="$2">($1)</a>',
      )
      .replace(
        /\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g,
        '<a href="$2" target="_blank" rel="noreferrer">$1</a>',
      );
  }

  function slugifyHeading(value, counts) {
    const base =
      String(value || "")
        .toLowerCase()
        .replace(/<[^>]+>/g, "")
        .replace(/[^\p{L}\p{N}\s-]/gu, "")
        .trim()
        .replace(/\s+/g, "-")
        .slice(0, 80) || "section";
    counts[base] = (counts[base] || 0) + 1;
    return counts[base] === 1 ? base : `${base}-${counts[base]}`;
  }

  function renderMarkdown(markdown, options = {}) {
    const emptyMessage = options.emptyMessage || "";
    const lines = String(markdown || "").replace(/\r\n/g, "\n").split("\n");
    const html = [];
    const toc = [];
    const headingCounts = {};
    let paragraph = [];
    let listOpen = false;
    let orderedListOpen = false;
    let blockquote = [];
    let codeOpen = false;
    let codeLines = [];
    let codeLang = "";
    let mathOpen = false;
    let mathLines = [];

    function flushParagraph() {
      if (paragraph.length === 0) return;
      html.push(`<p>${inlineMarkdown(paragraph.join(" "))}</p>`);
      paragraph = [];
    }

    function closeList() {
      if (!listOpen) return;
      html.push("</ul>");
      listOpen = false;
    }

    function closeOrderedList() {
      if (!orderedListOpen) return;
      html.push("</ol>");
      orderedListOpen = false;
    }

    function flushBlockquote() {
      if (blockquote.length === 0) return;
      html.push(
        `<blockquote>${blockquote.map((line) => `<p>${inlineMarkdown(line)}</p>`).join("")}</blockquote>`,
      );
      blockquote = [];
    }

    function closeCode() {
      if (!codeOpen) return;
      if (codeLang === "mermaid") {
        html.push(`<div class="mermaid">${escapeHtml(codeLines.join("\n"))}</div>`);
      } else {
        html.push(`<pre><code>${escapeHtml(codeLines.join("\n"))}</code></pre>`);
      }
      codeLines = [];
      codeOpen = false;
      codeLang = "";
    }

    function closeMath() {
      if (!mathOpen) return;
      html.push(`<div class="math-block">${escapeHtml(mathLines.join("\n"))}</div>`);
      mathLines = [];
      mathOpen = false;
    }

    function splitTableRow(row) {
      return row
        .trim()
        .replace(/^\|/, "")
        .replace(/\|$/, "")
        .split("|")
        .map((cell) => cell.trim());
    }

    function isTableSeparator(row) {
      const cells = splitTableRow(row);
      return cells.length > 0 && cells.every((cell) => /^:?-{3,}:?$/.test(cell.replace(/\s/g, "")));
    }

    function renderTable(headers, rows) {
      const headerHtml = headers.map((header) => `<th>${inlineMarkdown(header)}</th>`).join("");
      const rowHtml = rows
        .map((row) => {
          const cells = headers
            .map((_, index) => `<td>${inlineMarkdown(row[index] || "")}</td>`)
            .join("");
          return `<tr>${cells}</tr>`;
        })
        .join("");
      return `<div class="table-scroll"><table><thead><tr>${headerHtml}</tr></thead><tbody>${rowHtml}</tbody></table></div>`;
    }

    for (let index = 0; index < lines.length; index += 1) {
      const line = lines[index];
      if (line.trim().startsWith("```")) {
        if (codeOpen) {
          closeCode();
        } else {
          flushParagraph();
          closeList();
          closeOrderedList();
          flushBlockquote();
          codeOpen = true;
          codeLang = line.trim().slice(3).trim().toLowerCase();
        }
        continue;
      }

      if (codeOpen) {
        codeLines.push(line);
        continue;
      }

      if (mathOpen) {
        if (line.trim() === "$$") {
          closeMath();
        } else {
          mathLines.push(line);
        }
        continue;
      }

      if (line.trim() === "$$") {
        flushParagraph();
        closeList();
        closeOrderedList();
        flushBlockquote();
        mathOpen = true;
        continue;
      }

      const trimmed = line.trim();
      if (!trimmed) {
        flushParagraph();
        closeList();
        closeOrderedList();
        flushBlockquote();
        continue;
      }

      const blockMath = trimmed.match(/^\$\$(.+)\$\$$/);
      if (blockMath) {
        flushParagraph();
        closeList();
        closeOrderedList();
        flushBlockquote();
        html.push(`<div class="math-block">${escapeHtml(blockMath[1].trim())}</div>`);
        continue;
      }

      const nextLine = lines[index + 1]?.trim() || "";
      if (trimmed.includes("|") && isTableSeparator(nextLine)) {
        flushParagraph();
        closeList();
        closeOrderedList();
        flushBlockquote();
        const headers = splitTableRow(trimmed);
        const rows = [];
        index += 2;
        while (index < lines.length) {
          const rowLine = lines[index].trim();
          if (!rowLine || !rowLine.includes("|") || rowLine.startsWith("```")) {
            index -= 1;
            break;
          }
          rows.push(splitTableRow(rowLine));
          index += 1;
        }
        html.push(renderTable(headers, rows));
        continue;
      }

      const heading = trimmed.match(/^(#{1,6})\s+(.+)$/);
      if (heading) {
        flushParagraph();
        closeList();
        closeOrderedList();
        flushBlockquote();
        const level = heading[1].length;
        const text = heading[2].trim();
        const id = slugifyHeading(text, headingCounts);
        toc.push({ id, level, text });
        html.push(`<h${level} id="${escapeHtml(id)}">${inlineMarkdown(text)}</h${level}>`);
        continue;
      }

      const bullet = trimmed.match(/^[-*]\s+(.+)$/);
      if (bullet) {
        flushParagraph();
        closeOrderedList();
        flushBlockquote();
        if (!listOpen) {
          html.push("<ul>");
          listOpen = true;
        }
        html.push(`<li>${inlineMarkdown(bullet[1])}</li>`);
        continue;
      }

      const numbered = trimmed.match(/^\d+\.\s+(.+)$/);
      if (numbered) {
        flushParagraph();
        closeList();
        flushBlockquote();
        if (!orderedListOpen) {
          html.push("<ol>");
          orderedListOpen = true;
        }
        html.push(`<li>${inlineMarkdown(numbered[1])}</li>`);
        continue;
      }

      const quote = trimmed.match(/^>\s?(.+)$/);
      if (quote) {
        flushParagraph();
        closeList();
        closeOrderedList();
        blockquote.push(quote[1]);
        continue;
      }

      paragraph.push(trimmed);
    }

    closeCode();
    closeMath();
    flushParagraph();
    closeList();
    closeOrderedList();
    flushBlockquote();
    return {
      html: html.join("\n") || (emptyMessage ? `<p>${escapeHtml(emptyMessage)}</p>` : ""),
      toc,
    };
  }

  window.DocuGenMarkdown = {
    escapeHtml,
    inlineMarkdown,
    slugifyHeading,
    renderMarkdown,
  };
})();
