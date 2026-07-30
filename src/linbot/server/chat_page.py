"""A minimal, dependency-free chat page served at GET /.

Kept as an inline string so packaging stays trivial (no static-file mounts,
nothing extra to copy into the container). It talks to the same POST /ask
endpoint any other client would — the UI has no privileged path.
"""

CHAT_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>LinBot</title>
<style>
  :root { color-scheme: light dark; }
  * { box-sizing: border-box; }
  body {
    margin: 0; font-family: system-ui, -apple-system, sans-serif;
    background: light-dark(#f6f5f2, #191a1c); color: light-dark(#222, #e8e6e3);
    display: flex; flex-direction: column; height: 100dvh;
  }
  header {
    padding: 14px 20px; border-bottom: 1px solid light-dark(#e2e0da, #2c2e31);
    font-weight: 600; letter-spacing: 0.2px;
  }
  header small { font-weight: 400; opacity: 0.55; margin-left: 8px; }
  #log {
    flex: 1; overflow-y: auto; padding: 20px; display: flex;
    flex-direction: column; gap: 12px; max-width: 760px; width: 100%;
    margin: 0 auto;
  }
  .msg { padding: 10px 14px; border-radius: 12px; max-width: 85%;
         white-space: pre-wrap; line-height: 1.45; }
  .msg code {
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 0.9em;
    background: light-dark(#efede8, #1d1f21); padding: 1px 5px; border-radius: 5px;
  }
  .msg pre {
    background: light-dark(#efede8, #1d1f21); padding: 10px 12px;
    border-radius: 8px; overflow-x: auto; margin: 6px 0;
  }
  .msg pre code { background: none; padding: 0; }
  .msg a { color: light-dark(#3d6b35, #8fbf85); }
  .user { align-self: flex-end; background: light-dark(#d8e6d3, #2f4331); }
  .bot  { align-self: flex-start; background: light-dark(#ffffff, #26282b);
          border: 1px solid light-dark(#e2e0da, #2c2e31); }
  .err  { align-self: flex-start; background: light-dark(#f6dede, #46282a);
          font-size: 0.9em; }
  .pending { opacity: 0.5; font-style: italic; }
  form {
    display: flex; gap: 10px; padding: 14px 20px 18px; max-width: 760px;
    width: 100%; margin: 0 auto;
  }
  textarea {
    flex: 1; resize: none; padding: 10px 12px; border-radius: 10px;
    border: 1px solid light-dark(#ccc9c0, #3a3d41); font: inherit;
    background: light-dark(#fff, #222427); color: inherit; min-height: 44px;
  }
  button {
    padding: 0 20px; border-radius: 10px; border: none; font: inherit;
    background: light-dark(#3d6b35, #4a7d42); color: #fff; cursor: pointer;
  }
  button:disabled { opacity: 0.5; cursor: default; }
</style>
</head>
<body>
<header>LinBot<small>a student query assistant</small></header>
<div id="log"></div>
<form id="form">
  <textarea id="q" rows="1" placeholder="Ask a question…" autofocus></textarea>
  <button id="send" type="submit">Send</button>
</form>
<script>
  const log = document.getElementById("log");
  const form = document.getElementById("form");
  const q = document.getElementById("q");
  const send = document.getElementById("send");

  // Conversation history lives only in this array — in-memory, per tab.
  // Refreshing the page discards it; nothing is stored anywhere else.
  const history = [];
  const MAX_HISTORY = 20;
  // Fresh random label per page load; groups this tab's turns in the server
  // log so conversations can be reconstructed for training data.
  const conversationId = crypto.randomUUID();

  // Minimal markdown renderer for bot replies: HTML is escaped first, then a
  // few safe constructs (bold, italic, code, links, bullets) are re-applied.
  // No external libraries, no raw model HTML ever reaches innerHTML.
  function esc(s) {
    return s.replace(/&/g, "&amp;").replace(/</g, "&lt;")
            .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }
  function inline(s) {
    return s
      .replace(/`([^`\\n]+)`/g, "<code>$1</code>")
      .replace(/\\[([^\\]]+)\\]\\((https?:\\/\\/[^\\s)]+)\\)/g,
               '<a href="$2" target="_blank" rel="noopener">$1</a>')
      .replace(/^#{1,4} (.+)$/gm, "<strong>$1</strong>")
      .replace(/^([ \\t]*)[-*] /gm, "$1\\u2022 ")
      .replace(/\\*\\*\\*([^*\\n]+)\\*\\*\\*/g, "<strong><em>$1</em></strong>")
      .replace(/\\*\\*([^*\\n]+)\\*\\*/g, "<strong>$1</strong>")
      .replace(/(^|[^*])\\*([^*\\n]+)\\*(?!\\*)/g, "$1<em>$2</em>")
      .replace(/___([^_\\n]+)___/g, "<strong><em>$1</em></strong>")
      .replace(/__([^_\\n]+)__/g, "<strong>$1</strong>")
      .replace(/(^|[\\s(>])_([^_\\n]+)_(?!\\w)/gm, "$1<em>$2</em>");
  }
  function renderMarkdown(text) {
    const parts = text.split("```");
    let out = "";
    for (let i = 0; i < parts.length; i++) {
      if (i % 2 === 1) {
        const code = parts[i].replace(/^[\\w-]*\\n/, "").replace(/\\n$/, "");
        out += "<pre><code>" + esc(code) + "</code></pre>";
      } else {
        let seg = parts[i];
        if (i > 0) seg = seg.replace(/^\\n/, "");
        if (i < parts.length - 1) seg = seg.replace(/\\n$/, "");
        out += inline(esc(seg));
      }
    }
    return out;
  }

  function add(cls, text) {
    const div = document.createElement("div");
    div.className = "msg " + cls;
    if (cls === "bot") {
      div.innerHTML = renderMarkdown(text);
    } else {
      div.textContent = text;
    }
    log.appendChild(div);
    log.scrollTop = log.scrollHeight;
    return div;
  }

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const question = q.value.trim();
    if (!question || send.disabled) return;
    add("user", question);
    q.value = "";
    send.disabled = true;
    const pending = add("bot pending", "thinking…");
    try {
      const res = await fetch("/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          question,
          history: history.slice(-MAX_HISTORY),
          conversation_id: conversationId,
        }),
      });
      const body = await res.json();
      pending.remove();
      if (res.ok) {
        add("bot", body.answer);
        history.push({ role: "user", content: question });
        history.push({ role: "assistant", content: body.answer });
      } else {
        add("err", body.error || ("error " + res.status));
      }
    } catch {
      pending.remove();
      add("err", "network error — try again");
    } finally {
      send.disabled = false;
      q.focus();
    }
  });

  q.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      form.requestSubmit();
    }
  });
</script>
</body>
</html>
"""
