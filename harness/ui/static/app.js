(() => {
  const state = {
    agent: "schema",
    questions: { schema: [], quality: [], memory: [] },
    meta: null,
    apiOnline: false,
  };

  const el = {
    healthDot: document.getElementById("healthDot"),
    healthText: document.getElementById("healthText"),
    questionList: document.getElementById("questionList"),
    qCount: document.getElementById("qCount"),
    sessionId: document.getElementById("sessionId"),
    actorId: document.getElementById("actorId"),
    newSession: document.getElementById("newSession"),
    clearChat: document.getElementById("clearChat"),
    metaGrid: document.getElementById("metaGrid"),
    transcript: document.getElementById("transcript"),
    composer: document.getElementById("composer"),
    prompt: document.getElementById("prompt"),
    sendBtn: document.getElementById("sendBtn"),
    btnSchema: document.getElementById("btnSchema"),
    btnQuality: document.getElementById("btnQuality"),
    rail: document.getElementById("rail"),
    menuBtn: document.getElementById("menuBtn"),
    closeRail: document.getElementById("closeRail"),
    scrim: document.getElementById("scrim"),
  };

  if (window.marked) {
    marked.setOptions({ gfm: true, breaks: true, headerIds: false, mangle: false });
  }

  function newSessionId() {
    return `ui-${Math.random().toString(16).slice(2)}${Date.now().toString(16)}`;
  }

  function openRail(open) {
    el.rail.classList.toggle("open", open);
    el.scrim.hidden = !open;
  }

  function setAgent(agent) {
    state.agent = agent;
    el.btnSchema.classList.toggle("active", agent === "schema");
    el.btnQuality.classList.toggle("active", agent === "quality");
    renderQuestions();
  }

  function escapeHtml(s) {
    return String(s)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;");
  }

  function renderQuestions() {
    const items = state.questions[state.agent] || [];
    el.qCount.textContent = String(items.length);
    el.questionList.innerHTML = "";
    items.forEach((q) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "q-btn";
      btn.innerHTML = `<strong>${escapeHtml(q.id)} · ${escapeHtml(q.title)}</strong><span>${escapeHtml(q.why_ask || "")}</span>`;
      btn.addEventListener("click", () => {
        el.prompt.value = q.prompt;
        autosize();
        el.prompt.focus();
        openRail(false);
      });
      el.questionList.appendChild(btn);
    });
  }

  function renderMeta() {
    if (!state.meta) return;
    const a = state.meta.agents || {};
    const rows = [
      ["Schema runtime", a.schema?.runtime_id],
      ["Quality runtime", a.quality?.runtime_id],
      ["Gateway", state.meta.gateway_id],
      ["Memory", state.meta.memory_id],
      ["MCP", state.meta.mcp_runtime_id],
    ];
    el.metaGrid.innerHTML = rows
      .filter(([, v]) => v)
      .map(([k, v]) => `<div><dt>${escapeHtml(k)}</dt><dd>${escapeHtml(v)}</dd></div>`)
      .join("");
  }

  function enhanceCodeBlocks(root) {
    root.querySelectorAll("pre > code").forEach((code) => {
      const pre = code.parentElement;
      if (!pre || pre.parentElement?.classList.contains("code-block")) return;
      const lang =
        ([...code.classList].find((c) => c.startsWith("language-")) || "").replace(
          "language-",
          ""
        ) || "code";
      if (window.hljs) {
        try {
          hljs.highlightElement(code);
        } catch {
          /* ignore */
        }
      }
      const wrap = document.createElement("div");
      wrap.className = "code-block";
      const head = document.createElement("div");
      head.className = "code-head";
      head.innerHTML = `<span>${escapeHtml(lang)}</span>`;
      const copy = document.createElement("button");
      copy.type = "button";
      copy.textContent = "Copy";
      copy.addEventListener("click", async () => {
        try {
          await navigator.clipboard.writeText(code.textContent || "");
          copy.textContent = "Copied";
          setTimeout(() => (copy.textContent = "Copy"), 1200);
        } catch {
          copy.textContent = "Failed";
        }
      });
      head.appendChild(copy);
      pre.replaceWith(wrap);
      wrap.appendChild(head);
      wrap.appendChild(pre);
    });
  }

  function clearEmpty() {
    const empty = document.getElementById("emptyState");
    if (empty) empty.remove();
  }

  function ensureEmpty() {
    if (!el.transcript.querySelector(".bubble") && !document.getElementById("emptyState")) {
      el.transcript.innerHTML = `
        <div class="empty" id="emptyState">
          <div class="empty-mark">◈</div>
          <h3>Talk to the live agents</h3>
          <p>Pick a curated prompt or type below. Traffic goes Agent → Gateway → MCP → Supabase.</p>
        </div>`;
    }
  }

  function scrollTranscriptEnd() {
    requestAnimationFrame(() => {
      const last = el.transcript.lastElementChild;
      if (last) last.scrollIntoView({ block: "end", behavior: "smooth" });
      else el.transcript.scrollTop = el.transcript.scrollHeight;
    });
  }

  function addUserBubble(text) {
    clearEmpty();
    const div = document.createElement("div");
    div.className = "bubble user";
    div.innerHTML = `<div class="who">You</div>`;
    const body = document.createElement("div");
    body.className = "body";
    body.textContent = text;
    div.appendChild(body);
    el.transcript.appendChild(div);
    scrollTranscriptEnd();
  }

  function createAgentBubble() {
    clearEmpty();
    const div = document.createElement("div");
    div.className = "bubble agent pending";
    div.innerHTML = `<div class="who">${
      state.agent === "schema" ? "Schema agent" : "Quality agent"
    }</div>`;

    const trace = document.createElement("details");
    trace.className = "trace";
    trace.open = true;
    trace.innerHTML = `
      <summary>
        <span>Thinking &amp; tools</span>
        <span class="trace-live">working…</span>
      </summary>
      <div class="trace-body"></div>`;
    div.appendChild(trace);

    const body = document.createElement("div");
    body.className = "body";
    const md = document.createElement("div");
    md.className = "md stream-body";
    md.innerHTML = `<span class="typing" aria-label="Thinking"><i></i><i></i><i></i></span>`;
    body.appendChild(md);
    div.appendChild(body);

    const meta = document.createElement("div");
    meta.className = "meta";
    div.appendChild(meta);

    el.transcript.appendChild(div);
    scrollTranscriptEnd();

    return {
      root: div,
      traceBody: trace.querySelector(".trace-body"),
      traceLive: trace.querySelector(".trace-live"),
      md,
      meta,
      text: "",
      tools: new Map(),
    };
  }

  function appendThinking(ui, content) {
    if (!content) return;
    const item = document.createElement("div");
    item.className = "trace-item thinking";
    item.textContent = content;
    ui.traceBody.appendChild(item);
    scrollTranscriptEnd();
  }

  function upsertTool(ui, ev) {
    const id = String(ev.toolUseId || ev.name || Math.random());
    let item = ui.tools.get(id);
    if (!item) {
      item = document.createElement("div");
      item.className = "trace-item tool";
      item.innerHTML = `
        <div class="trace-label">
          <span></span>
          <span class="pill-status"></span>
        </div>
        <pre></pre>`;
      ui.traceBody.appendChild(item);
      ui.tools.set(id, item);
    }
    const nameEl = item.querySelector(".trace-label span");
    const statusEl = item.querySelector(".pill-status");
    const pre = item.querySelector("pre");
    nameEl.textContent = `⚙ ${ev.name || "tool"}`;
    statusEl.textContent = ev.status === "done" ? "done" : "running";
    const payload =
      ev.status === "done"
        ? ev.output ?? ev.input
        : ev.input ?? ev.output;
    pre.textContent =
      typeof payload === "string" ? payload : JSON.stringify(payload, null, 2);
    scrollTranscriptEnd();
  }

  function setStreamText(ui, text) {
    ui.text = text;
    const html = window.marked ? marked.parse(text || "") : escapeHtml(text || "");
    ui.md.innerHTML = window.DOMPurify ? DOMPurify.sanitize(html) : html;
    enhanceCodeBlocks(ui.md);
    scrollTranscriptEnd();
  }

  function finishBubble(ui, { error, meta }) {
    ui.root.classList.remove("pending");
    if (error) ui.root.classList.add("error");
    if (ui.traceLive) ui.traceLive.textContent = error ? "error" : "done";
    if (!ui.text && !error) {
      ui.md.innerHTML = `<p class="hint">(empty response)</p>`;
    }
    if (meta) {
      ui.meta.textContent = Object.entries(meta)
        .filter(([, v]) => v != null && v !== "")
        .map(([k, v]) => `${k}: ${v}`)
        .join(" · ");
    }
    scrollTranscriptEnd();
  }

  function autosize() {
    el.prompt.style.height = "auto";
    el.prompt.style.height = `${Math.min(el.prompt.scrollHeight, 140)}px`;
  }

  async function loadHealth() {
    try {
      const r = await fetch("/api/health", { cache: "no-store" });
      if (!r.ok) throw new Error(`health ${r.status}`);
      const j = await r.json();
      el.healthDot.className = `dot ${j.ok || j.connected ? "ok" : "bad"}`;
      el.healthText.textContent = j.ok || j.connected ? "Connected" : "Not ready";
      state.apiOnline = Boolean(j.ok || j.connected);
    } catch {
      state.apiOnline = false;
      el.healthDot.className = "dot bad";
      el.healthText.textContent = "API offline";
    }
  }

  async function loadQuestionsBank() {
    // Prefer live API when backend is wired; fall back to static S3 copy.
    try {
      const r = await fetch("/api/questions", { cache: "no-store" });
      if (r.ok) {
        const q = await r.json();
        if (q && (q.schema || q.quality)) return q;
      }
    } catch {
      /* static fallback */
    }
    const r = await fetch("/questions.json", { cache: "no-store" });
    if (!r.ok) throw new Error(`questions.json HTTP ${r.status}`);
    const data = await r.json();
    return {
      schema: data.schema_agent || [],
      quality: data.quality_agent || [],
      memory: data.memory_session || [],
    };
  }

  async function loadBoot() {
    const q = await loadQuestionsBank();
    state.questions = q;
    renderQuestions();

    try {
      const r = await fetch("/api/meta", { cache: "no-store" });
      if (r.ok) {
        const m = await r.json();
        state.meta = m;
        const bs = document.getElementById("blurbSchema");
        const bq = document.getElementById("blurbQuality");
        if (bs && m.agents?.schema?.blurb) bs.textContent = m.agents.schema.blurb;
        if (bq && m.agents?.quality?.blurb) bq.textContent = m.agents.quality.blurb;
        renderMeta();
      }
    } catch {
      /* optional on static hosting */
    }
  }

  async function send(e) {
    e.preventDefault();
    const prompt = el.prompt.value.trim();
    if (!prompt || el.sendBtn.disabled) return;

    addUserBubble(prompt);
    el.prompt.value = "";
    autosize();
    el.sendBtn.disabled = true;
    el.sendBtn.querySelector(".send-label").textContent = "Running…";

    const ui = createAgentBubble();
    let sessionId = el.sessionId.value.trim() || newSessionId();
    if (sessionId.length < 33) sessionId = `${sessionId}-${newSessionId()}`;
    el.sessionId.value = sessionId;

    try {
      const r = await fetch("/api/chat/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
        body: JSON.stringify({
          agent: state.agent,
          prompt,
          session_id: sessionId,
          actor_id: el.actorId.value.trim() || "ui-user",
        }),
      });
      if (!r.ok || !r.body) {
        const t = await r.text();
        const hint =
          r.status === 403 || r.status === 404
            ? "\n\nCloudFront is static-only right now. Wire `/api/*` to the FastAPI backend (`harness/ui/app.py`) to chat with agents."
            : "";
        setStreamText(ui, (t || `HTTP ${r.status}`) + hint);
        finishBubble(ui, { error: true, meta: { status: r.status } });
        return;
      }

      const reader = r.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let doneMeta = {};

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const parts = buffer.split("\n\n");
        buffer = parts.pop() || "";
        for (const part of parts) {
          const line = part
            .split("\n")
            .map((l) => l.trim())
            .find((l) => l.startsWith("data:"));
          if (!line) continue;
          let ev;
          try {
            ev = JSON.parse(line.slice(5).trim());
          } catch {
            continue;
          }
          if (!ev || typeof ev !== "object") continue;

          if (ev.type === "thinking") appendThinking(ui, ev.content);
          else if (ev.type === "tool") upsertTool(ui, ev);
          else if (ev.type === "text") setStreamText(ui, ui.text + (ev.content || ""));
          else if (ev.type === "result" && ev.content) setStreamText(ui, ev.content);
          else if (ev.type === "error") {
            setStreamText(ui, String(ev.content || "error"));
            finishBubble(ui, { error: true });
          } else if (ev.type === "meta" && ev.session_id) {
            el.sessionId.value = ev.session_id;
          } else if (ev.type === "done") {
            if (ev.response) setStreamText(ui, ev.response);
            if (ev.session_id) el.sessionId.value = ev.session_id;
            doneMeta = {
              ms: ev.elapsed_ms,
              session: ev.session_id,
              memory: ev.memory_id,
            };
          }
        }
      }
      finishBubble(ui, { error: false, meta: doneMeta });
    } catch (err) {
      setStreamText(ui, String(err));
      finishBubble(ui, { error: true });
    } finally {
      el.sendBtn.disabled = false;
      el.sendBtn.querySelector(".send-label").textContent = "Send";
      el.prompt.focus();
    }
  }

  el.btnSchema.addEventListener("click", () => setAgent("schema"));
  el.btnQuality.addEventListener("click", () => setAgent("quality"));
  el.newSession.addEventListener("click", () => {
    el.sessionId.value = newSessionId();
  });
  el.clearChat.addEventListener("click", () => {
    el.transcript.innerHTML = "";
    ensureEmpty();
  });
  el.composer.addEventListener("submit", send);
  el.prompt.addEventListener("input", autosize);
  el.prompt.addEventListener("keydown", (ev) => {
    if (ev.key === "Enter" && !ev.shiftKey) {
      ev.preventDefault();
      el.composer.requestSubmit();
    }
  });
  el.menuBtn.addEventListener("click", () => openRail(true));
  el.closeRail.addEventListener("click", () => openRail(false));
  el.scrim.addEventListener("click", () => openRail(false));

  el.sessionId.value = newSessionId();
  autosize();
  loadHealth();
  loadBoot().catch((err) => {
    el.healthDot.className = "dot bad";
    if (!el.healthText.textContent || el.healthText.textContent === "…") {
      el.healthText.textContent = "API offline";
    }
    console.error(err);
  });
})();
