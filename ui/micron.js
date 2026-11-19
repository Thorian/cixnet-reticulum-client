/** Micron is data, never HTML. Parse to a small tree and build DOM nodes safely.
 * Formatting state deliberately carries between lines, as in regular NomadNet.
 */
export function micronColor(value) {
  return /^(?:[0-9a-f]{3}|[0-9a-f]{6})$/i.test(value || "")
    ? `#${value}`
    : null;
}

/** Parse inline Micron constructs into data tokens rather than remote markup. */
function inline(text, state) {
  const result = [];
  let buffer = "";
  /** Emit accumulated text with a snapshot of the current inline style. */
  const flush = () => {
    if (buffer)
      result.push({ type: "text", text: buffer, style: { ...state.style } });
    buffer = "";
  };
  for (let i = 0; i < text.length; ) {
    if (text[i] === "\\" && i + 1 < text.length) {
      buffer += text[i + 1];
      i += 2;
      continue;
    }
    if (text[i] !== "`" || i + 1 >= text.length) {
      buffer += text[i++];
      continue;
    }
    flush();
    const command = text[i + 1];
    i += 2;
    const toggle = { "!": "bold", "*": "italic", _: "underline" }[command];
    if (toggle) state.style[toggle] = !state.style[toggle];
    else if (command === "`") {
      state.style = {};
      state.align = "left";
    } else if (["c", "l", "r", "a"].includes(command))
      state.align = { c: "center", l: "left", r: "right", a: "left" }[command];
    else if (command === "f" || command === "b")
      delete state.style[command === "f" ? "fg" : "bg"];
    else if (command === "F" || command === "B") {
      const truecolor = text[i] === "T";
      const count = truecolor ? 6 : 3;
      const value = text.slice(
        i + (truecolor ? 1 : 0),
        i + (truecolor ? 1 : 0) + count,
      );
      const color = micronColor(value);
      if (color) {
        state.style[command === "F" ? "fg" : "bg"] = color;
        i += count + (truecolor ? 1 : 0);
      }
    } else if (command === ":") {
      const match = text.slice(i).match(/^[A-Za-z0-9_-]+/);
      if (match) {
        result.push({ type: "anchor", name: match[0] });
        i += match[0].length;
      }
    } else if (command === "[") {
      const end = text.indexOf("]", i);
      if (end < 0) {
        buffer += "`[";
        continue;
      }
      const parts = text.slice(i, end).split("`");
      const target = parts.length === 1 ? parts[0] : parts[1];
      result.push({
        type: "link",
        label: parts.length === 1 ? target : parts[0] || target,
        target,
        fields: (parts[2] || "").split("|").filter(Boolean),
        style: { ...state.style },
      });
      i = end + 1;
    } else if (command === "<") {
      const middle = text.indexOf("`", i);
      const end = middle < 0 ? -1 : text.indexOf(">", middle + 1);
      if (end < 0) {
        buffer += "`<";
        continue;
      }
      const spec = text.slice(i, middle).split("|");
      const flags = spec.length > 1 ? spec[0] : "";
      const name = spec.length > 1 ? spec[1] : spec[0];
      const dimensions = flags.match(/(\d+)(?:x(\d+))?/);
      result.push({
        type: "field",
        style: { ...state.style },
        kind: flags.includes("^")
          ? "radio"
          : flags.includes("?")
            ? "checkbox"
            : flags.includes("!")
              ? "password"
              : "text",
        name,
        value: text.slice(middle + 1, end),
        choice: spec[2],
        checked: spec[3] === "*",
        width: Math.max(1, Math.min(256, Number(dimensions?.[1] || 24))),
        rows: Math.max(1, Math.min(256, Number(dimensions?.[2] || 1))),
      });
      i = end + 1;
    } else buffer += "`" + command;
  }
  flush();
  if (result.length > 10000)
    throw new Error("This Micron line has too many elements to render.");
  return result;
}

/** Split table cells while respecting inline constructs that contain separators. */
function tableCells(line) {
  const cells = [];
  let cell = "",
    construct = null;
  for (let i = 0; i < line.length; i++) {
    if (line[i] === "\\" && i + 1 < line.length) {
      cell += line[i] + line[++i];
      continue;
    }
    if (line[i] === "`" && ["[", "<"].includes(line[i + 1]))
      construct = line[i + 1] === "[" ? "]" : ">";
    if (construct && line[i] === construct) construct = null;
    if (line[i] === "|" && !construct) {
      cells.push(cell.trim());
      cell = "";
    } else cell += line[i];
  }
  cells.push(cell.trim());
  if (!cells[0]) cells.shift();
  if (!cells[cells.length - 1]) cells.pop();
  return cells;
}

/** Parse a bounded Micron document into structured blocks and persistent style state. */
export function parseMicron(source) {
  if (typeof source !== "string" || source.length > 1024 * 1024)
    throw new Error("Micron page exceeds the 1 MiB rendering limit.");
  // Terminal control bytes are not page content. Keep newline and tab.
  source = source
    .replace(/\r\n?/g, "\n")
    .replace(/[\u0000-\u0008\u000b-\u001f\u007f]/g, "");
  const document = { blocks: [], fg: null, bg: null };
  const state = { style: {}, align: "left", depth: 0 };
  let literal = null,
    table = null;
  for (let line of source.split("\n")) {
    if (line === "`=") {
      if (literal) literal = null;
      else {
        literal = { type: "pre", text: "", depth: state.depth };
        document.blocks.push(literal);
      }
      continue;
    }
    if (literal) {
      literal.text += (line === "\\`=" ? "`=" : line) + "\n";
      continue;
    }
    if (line.startsWith("#")) {
      const color = line.match(
        /^#!(fg|bg)=([0-9a-fA-F]{3}(?:[0-9a-fA-F]{3})?)$/,
      );
      if (color) document[color[1]] = micronColor(color[2]);
      continue;
    }
    if (/^`t(?:[lcr])?\d*$/.test(line)) {
      if (table) table = null;
      else {
        table = { type: "table", rows: [], depth: state.depth };
        document.blocks.push(table);
      }
      continue;
    }
    if (table) {
      const cells = tableCells(line);
      if (cells.length && cells.every((cell) => /^:?-{3,}:?$/.test(cell))) {
        table.header = true;
        continue;
      }
      table.rows.push(cells.map((cell) => inline(cell, state)));
      continue;
    }
    let escaped = line.startsWith("\\"),
      folded = null;
    if (escaped) {
      line = line.slice(1);
      if (line.startsWith("`") || line.startsWith("\\")) line = "\\" + line;
    }
    if (!escaped && /^`[+-]>/.test(line)) {
      folded = line[1] === "-";
      line = line.slice(2);
    }
    if (!escaped && line.startsWith("<")) {
      state.depth = 0;
      line = line.slice(1);
    }
    const heading = !escaped && line.match(/^(>+)(.*)$/);
    if (heading) {
      state.depth = Math.min(20, heading[1].length);
      line = heading[2];
    }
    if (heading && !line) continue;
    if (!escaped && line.startsWith("-")) {
      document.blocks.push({ type: "rule", depth: state.depth });
      continue;
    }
    if (!escaped && line.startsWith("`(")) {
      const parts = line.slice(2, line.lastIndexOf(")")).split("`");
      if (line.lastIndexOf(")") > 2 && parts.length >= 2) {
        const properties = Object.fromEntries(
          parts.slice(1, -1).map((value) => value.split("=")),
        );
        document.blocks.push({
          type: "image",
          alt: parts[0].trim(),
          target: parts.at(-1).trim(),
          width: properties.w,
          height: properties.h,
          align:
            { c: "center", l: "left", r: "right" }[properties.a] || state.align,
          depth: state.depth,
        });
      }
      continue;
    }
    if (!escaped && line.startsWith("`{")) {
      const target = line.slice(2).split(/[`}]/)[0];
      document.blocks.push({
        type: "line",
        depth: state.depth,
        align: state.align,
        inlines: [
          { type: "link", label: "Open embedded page", target, fields: [] },
        ],
      });
      continue;
    }
    const tokens = inline(line, state);
    const block = {
      type: heading ? "heading" : "line",
      depth: state.depth,
      align: state.align,
      inlines: tokens,
    };
    if (heading) {
      block.anchor = tokens
        .map((token) => token.text || token.label || "")
        .join("")
        .replace(/[^A-Za-z0-9]+/g, "-")
        .replace(/^-|-$/g, "")
        .toLowerCase();
      block.folded = folded;
    }
    document.blocks.push(block);
    if (document.blocks.length > 10000)
      throw new Error("This page has too many lines to render.");
  }
  return document;
}

/** Apply the supported text-style properties to a locally created element. */
function styleElement(element, style = {}) {
  if (style.bold) element.style.fontWeight = "bold";
  if (style.italic) element.style.fontStyle = "italic";
  if (style.underline) element.style.textDecoration = "underline";
  if (style.fg) element.style.color = style.fg;
  if (style.bg) element.style.backgroundColor = style.bg;
}

/** Create safe DOM nodes for parsed text, links, anchors and form controls. */
function appendTokens(element, tokens, onLink) {
  for (const token of tokens) {
    let node;
    if (token.type === "anchor") {
      node = document.createElement("span");
      node.dataset.micronAnchor = token.name;
    } else if (token.type === "link") {
      if (/^https?:\/\//i.test(token.target)) {
        node = document.createElement("a");
        node.href = token.target;
        node.target = "_blank";
        node.rel = "noopener noreferrer";
      } else {
        node = document.createElement("button");
        node.type = "button";
        /** Follow this parsed Micron link with its declared form-field selectors. */
        node.onclick = () => onLink(token.target, token.fields);
      }
      node.textContent = token.label;
      node.className = "micron-link";
    } else if (token.type === "field") {
      node = document.createElement("label");
      const input = document.createElement(
        token.kind === "text" && token.rows > 1 ? "textarea" : "input",
      );
      input.dataset.micronField = token.name;
      input.setAttribute("aria-label", token.name);
      if (input.tagName === "INPUT") input.type = token.kind;
      if (["radio", "checkbox"].includes(token.kind)) {
        input.name = "micron-" + token.name;
        input.value = token.choice || token.value || "1";
        input.checked = token.checked;
        node.append(input, document.createTextNode(token.value));
      } else {
        input.value = token.value;
        input.style.width = `${token.width}ch`;
        input.style.maxWidth = "100%";
        if (input.tagName === "TEXTAREA") input.rows = Math.min(20, token.rows);
        node.append(input);
      }
    } else {
      node = document.createElement("span");
      node.textContent = token.text;
    }
    styleElement(node, token.style);
    element.append(node);
  }
}

/** Render parsed page blocks into the selected document root. */
export function renderMicron(root, source, onLink, onImage = null) {
  const page = parseMicron(source);
  root.replaceChildren();
  root.style.color = page.fg || "";
  root.style.backgroundColor = page.bg || "";
  const folds = [];
  for (const block of page.blocks) {
    if (block.type === "heading")
      while (folds.length && block.depth <= folds[folds.length - 1].depth)
        folds.pop();
    let parent = folds.length ? folds[folds.length - 1].node : root;
    let element;
    if (block.type === "image") {
      element = document.createElement("div");
      const image = document.createElement("img");
      image.alt = block.alt;
      image.style.maxWidth = "100%";
      image.style.objectFit = "contain";
      for (const dimension of ["width", "height"]) {
        const value = block[dimension];
        if (/^[1-9][0-9]{0,3}$/.test(value || ""))
          image[dimension] = Number(value);
      }
      element.append(image);
      parent.append(element);
      if (onImage) onImage(block.target, image);
    } else if (block.type === "heading" && block.folded !== null) {
      const details = document.createElement("details");
      details.open = !block.folded;
      parent.append(details);
      element = document.createElement("summary");
      details.append(element);
      folds.push({ depth: block.depth, node: details });
      appendTokens(element, block.inlines, onLink);
    } else if (block.type === "table") {
      element = document.createElement("table");
      block.rows.forEach((row, index) => {
        /** Create one row of the locally rendered Micron table. */

        const tr = document.createElement("tr");
        row.forEach((tokens) => {
          /** Create a header or data cell and fill it with safe parsed tokens. */

          const td = document.createElement(
            block.header && index === 0 ? "th" : "td",
          );
          appendTokens(td, tokens, onLink);
          tr.append(td);
        });
        element.append(tr);
      });
      parent.append(element);
    } else {
      element = document.createElement(
        block.type === "pre"
          ? "pre"
          : block.type === "rule"
            ? "hr"
            : block.type === "heading"
              ? `h${Math.max(1, Math.min(6, block.depth))}`
              : "div",
      );
      if (block.inlines) appendTokens(element, block.inlines, onLink);
      else if (block.text) element.textContent = block.text;
      parent.append(element);
    }
    element.classList.add("micron-" + block.type);
    element.style.textAlign = block.align || "left";
    element.style.marginInline = `${Math.max(0, block.depth - 1) * 2}ch`;
    if (block.anchor) element.dataset.micronAnchor = block.anchor;
  }
}

/** Collect only the form fields requested by the parsed link selectors. */
export function collectMicronFields(root, selectors) {
  const data = Object.create(null);
  for (const entry of selectors) {
    const split = entry.indexOf("=");
    if (split > 0)
      data["var_" + entry.slice(0, split)] = entry.slice(split + 1);
  }
  for (const input of root.querySelectorAll("[data-micron-field]")) {
    const name = input.dataset.micronField;
    if (!selectors.includes("*") && !selectors.includes(name)) continue;
    if (["checkbox", "radio"].includes(input.type) && !input.checked) continue;
    const key = "field_" + name;
    data[key] =
      input.type === "checkbox" && data[key]
        ? data[key] + "," + input.value
        : input.value;
  }
  return data;
}
