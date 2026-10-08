/* AI 법률 길잡이 프런트엔드 (바닐라 JS). 대화는 이 브라우저의 localStorage에만 저장된다. */
(() => {
  "use strict";

  const STORE_KEY = "ai-law-chats-v1";
  // 화면에 보이는 문구와 실제로 보내는 질문이 같도록 한다. 첫 칩은 평가에 쓴 질문이라 저장된 답변이 있어 바로 열린다.
  const CHIPS = ["고영향 인공지능이란 무엇인가요?", "어떤 조문을 확인해야 하나요?"];
  // "예시 질문 더 보기"에 나오는 질문들: 평가 때 이미 답변이 저장되어 있어 눌러도 LLM 호출(크레딧)이 들지 않는다.
  // 질문 문구가 한 글자라도 다르면 저장된 답을 쓰지 못하므로 문구를 바꾸지 말 것.
  const MORE_CHIPS = [
      "이 법은 무엇을 위해 만들어졌나요?",
      "외국 회사가 만든 AI 서비스도 이 법의 적용을 받나요?",
      "인공지능 기본계획은 몇 년마다 세우나요?",
      "국가인공지능전략위원회는 어떻게 구성되나요?",
      "중소기업이나 스타트업을 위한 지원이 있나요?",
      "AI 윤리원칙에는 어떤 내용이 들어가나요?",
      "서비스가 AI로 운영된다는 사실을 이용자에게 미리 알려야 하나요?",
      "생성형 AI로 만든 결과물에는 표시를 해야 하나요?",
      "우리 서비스가 고영향 AI에 해당하는지 어떻게 확인하나요?",
      "고영향 AI를 제공하는 사업자는 어떤 안전 조치를 해야 하나요?",
      "한국에 사무소가 없는 해외 AI 기업은 어떻게 해야 하나요?",
      "직무상 알게 된 비밀을 누설하면 어떤 처벌을 받나요?",
      "과태료는 얼마이고 어떤 경우에 부과되나요?",
      "고영향 AI 사업자에게는 어떤 의무들이 있나요?",
      "오늘 서울 날씨 알려줘"
  ];

  const $ = (id) => document.getElementById(id);
  const el = { app: $("app"), sidebar: $("sidebar"), list: $("chatList"), messages: $("messages"), chips: $("chips"),
    form: $("composer"), input: $("input"), send: $("send"), panel: $("panel"), panelBody: $("panelBody"),
    scrim: $("scrim"), menu: $("menuBtn"), newChat: $("newChat"), panelClose: $("panelClose") };

  // ---------- 상태 ----------
  let chats = load();
  let activeId = chats[0]?.id ?? null;
  let busy = false;
  let chipsOpen = false;
  let selectedSrc = null; // {chatId, msgIndex, srcIndex}
  const articleCache = new Map();

  function load() {
    try { const v = JSON.parse(localStorage.getItem(STORE_KEY) || "[]"); return Array.isArray(v) ? v : []; }
    catch { return []; }
  }
  function save() {
    try { localStorage.setItem(STORE_KEY, JSON.stringify(chats.slice(0, 30))); } catch { /* 저장 불가여도 화면은 동작 */ }
  }
  const active = () => chats.find((c) => c.id === activeId);
  const uid = () => Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
  const timeText = (ts) => new Date(ts).toLocaleTimeString("ko-KR", { hour: "numeric", minute: "2-digit" });

  // ---------- 텍스트 안전 처리 ----------
  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  /** LLM 답변(마크다운 일부)을 HTML로 바꾼다. 먼저 전부 이스케이프하고 허용한 서식만 다시 만든다. */
  function md(text) {
    const lines = esc(text).split("\n");
    const out = [];
    let inList = false, para = [];
    const flushPara = () => { if (para.length) { out.push(`<p>${para.join("<br>")}</p>`); para = []; } };
    const closeList = () => { if (inList) { out.push("</ul>"); inList = false; } };
    const inline = (s) => s.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
    for (const raw of lines) {
      const line = raw.trimEnd();
      let m;
      if (!line.trim()) { flushPara(); closeList(); continue; }
      if ((m = line.match(/^#{1,4}\s+(.*)$/))) { flushPara(); closeList(); out.push(`<h4>${inline(m[1])}</h4>`); continue; }
      if ((m = line.match(/^\s*[-*•]\s+(.*)$/))) { flushPara(); if (!inList) { out.push("<ul>"); inList = true; } out.push(`<li>${inline(m[1])}</li>`); continue; }
      if (/^\s*---+\s*$/.test(line)) { flushPara(); closeList(); continue; }
      closeList();
      para.push(inline(line.trim()));
    }
    flushPara(); closeList();
    return out.join("");
  }

  const ICON = {
    chat: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 5.5A1.5 1.5 0 015.5 4h13A1.5 1.5 0 0120 5.5v9a1.5 1.5 0 01-1.5 1.5H10l-4 3.5V16h-.5A1.5 1.5 0 014 14.5z" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"/></svg>',
    doc: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 3h7l5 5v12a1 1 0 01-1 1H7a1 1 0 01-1-1V4a1 1 0 011-1z" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/><path d="M14 3v5h5M9 13h6M9 17h6" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>',
    copy: '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="8" y="8" width="11" height="12" rx="2" fill="none" stroke="currentColor" stroke-width="1.7"/><path d="M5 15V6a2 2 0 012-2h8" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/></svg>',
    redo: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20 12a8 8 0 10-2.5 5.8M20 5v5h-5" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    chev: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 9l6 6 6-6" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    avatar: '<svg class="avatar" viewBox="0 0 48 48" aria-hidden="true"><path d="M24 4l17 10v20L24 44 7 34V14z" fill="#14808a"/><path d="M24 14c4 5 7 8.5 7 13a7 7 0 01-14 0c0-4.500 3-8 7-13z" fill="#fff"/></svg>',
  };

  // ---------- 렌더링: 사이드바 ----------
  function renderSidebar() {
    if (!chats.length) { el.list.innerHTML = '<li class="empty-list">아직 대화가 없어요.</li>'; return; }
    el.list.innerHTML = chats.map((c) => `
      <li class="chat-item${c.id === activeId ? " active" : ""}">
        <button class="chat-open" type="button" data-open="${esc(c.id)}">${ICON.chat}<span>${esc(c.title)}</span></button>
        <button class="chat-del" type="button" data-del="${esc(c.id)}" aria-label="대화 삭제">✕</button>
      </li>`).join("");
  }

  // ---------- 렌더링: 메시지 ----------
  const welcomeHTML = `
    <div class="row-bot"><div class="bot-card">${ICON.avatar}<div class="bot-body">
      <h3 class="lead">법률 문서를 근거로 설명해드릴게요.</h3>
      <p class="sub">궁금한 내용을 질문하면 관련 조문을 찾아 쉬운 설명과 함께 안내합니다.</p>
      <ol class="steps"><li><b>1</b>용어의 의미와 적용 범위</li><li><b>2</b>질문과 관련된 법률 조항</li><li><b>3</b>답변에 사용한 근거 확인</li></ol>
    </div></div></div>`;

  function srcLabel(s) { return s.article; }
  function excerpt(s) {
    // 청크 본문의 첫 줄은 "[제N장 …]" 문맥 헤더이므로 건너뛰고 첫 문장 일부를 보여준다
    let body = s.content.split("\n").slice(1).join(" ").replace(/\s+/g, " ").trim();
    body = body.replace(/^제\d+조(?:의\d+)?\([^)]*\)\s*/, ""); // 제목 줄과 겹치는 "제N조(제목)" 접두어 제거
    return body.slice(0, 70) + (body.length > 70 ? "…" : "");
  }

  function botHTML(m, i) {
    if (m.loading) {
      return `<div class="row-bot"><div class="bot-card">${ICON.avatar}<div class="bot-body">
        <span class="typing"><span class="dots"><i></i><i></i><i></i></span>관련 조문을 찾고 있어요…</span></div></div></div>`;
    }
    if (m.error) {
      return `<div class="row-bot"><div class="bot-card error">${ICON.avatar}<div class="bot-body">
        <h3 class="lead">답변을 만들지 못했어요</h3><p>${esc(m.text)}</p></div></div>
        <div class="actions"><button class="act" type="button" data-redo="${i}">${ICON.redo}다시 시도</button></div></div>`;
    }
    const srcs = (m.sources || []).map((s, j) => `
      <li class="src${selectedSrc && selectedSrc.msg === i && selectedSrc.src === j && selectedSrc.chat === activeId ? " on" : ""}">
        <div class="src-top">${ICON.doc}
          <div class="src-text"><div class="src-title">${esc(srcLabel(s))}</div><div class="src-desc">${esc(excerpt(s))}</div></div>
          <button class="view" type="button" data-view="${i}:${j}">원문 보기 ↗</button>
          <button class="chev" type="button" aria-expanded="false" aria-label="검색된 내용 펼치기" data-toggle="${i}:${j}">${ICON.chev}</button>
        </div>
        <div class="src-body" hidden>${esc(s.content.split("\n").slice(1).join("\n"))}</div>
      </li>`).join("");
    const srcBlock = srcs ? `<div class="src-head">${ICON.doc}참고 근거</div><ul class="src-list">${srcs}</ul>` : "";
    return `<div class="row-bot"><div class="bot-card">${ICON.avatar}<div class="bot-body answer">${md(m.text)}</div></div>
      <div class="actions">
        <button class="act" type="button" data-copy="${i}">${ICON.copy}복사하기</button>
        <button class="act" type="button" data-redo="${i}" ${busy ? "disabled" : ""}>${ICON.redo}다시 생성하기</button>
      </div>${srcBlock}</div>`;
  }

  function renderMessages(scrollToEnd = true) {
    const c = active();
    let html = welcomeHTML;
    (c?.messages || []).forEach((m, i) => {
      html += m.role === "user"
        ? `<div class="row-user"><div class="bubble">${esc(m.text)}</div><div class="time">${timeText(m.ts)}</div></div>`
        : botHTML(m, i);
    });
    el.messages.innerHTML = html;
    if (scrollToEnd) el.messages.scrollTop = el.messages.scrollHeight;
  }

  function renderChips() {
    const chip = (q) => `<button class="chip" type="button" data-chip="${esc(q)}" ${busy ? "disabled" : ""}>${esc(q)}</button>`;
    const toggle = `<button class="chip more" type="button" id="moreToggle" aria-expanded="${chipsOpen}">${chipsOpen ? "예시 질문 접기 ▴" : "예시 질문 더 보기 ▾"}</button>`;
    el.chips.innerHTML = CHIPS.map(chip).join("") + toggle
      + (chipsOpen ? `<p class="chips-hint">✓ 저장된 답변이 있는 예시라서 바로 열려요</p>` + MORE_CHIPS.map(chip).join("") : "");
  }

  function setBusy(v) {
    busy = v;
    el.send.disabled = v;
    el.input.disabled = v;
    document.querySelectorAll(".chip[data-chip], [data-redo]").forEach((b) => { b.disabled = v; });
    if (!v) el.input.focus();
  }

  // ---------- 근거 문서 패널 ----------
  function renderPanelEmpty() {
    el.panelBody.innerHTML = `<h3>인공지능기본법</h3>
      <p class="hint">답변에 사용한 조문을 선택하면<br>이곳에서 원문을 확인할 수 있습니다.</p>
      <div class="skeleton" aria-hidden="true"><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i></div>`;
  }
  function openPanelOnNarrow() {
    if (window.matchMedia("(max-width: 1180px)").matches) { el.panel.classList.add("open"); el.scrim.hidden = false; }
  }
  function closeOverlays() { el.panel.classList.remove("open"); el.sidebar.classList.remove("open"); el.scrim.hidden = true; }

  async function showArticle(msgIndex, srcIndex) {
    const m = active()?.messages[msgIndex];
    const s = m?.sources?.[srcIndex];
    if (!s) return;
    selectedSrc = { chat: activeId, msg: msgIndex, src: srcIndex };
    renderMessages(false);
    openPanelOnNarrow();
    const key = (s.article.match(/^제\d+조(?:의\d+)?/) || [s.article])[0];
    el.panelBody.innerHTML = '<p class="hint">원문을 불러오는 중…</p>';
    try {
      let a = articleCache.get(key);
      if (!a) {
        const r = await fetch(`/api/article?article=${encodeURIComponent(key)}`);
        if (!r.ok) throw new Error(r.status);
        a = await r.json();
        articleCache.set(key, a);
      }
      el.panelBody.innerHTML = `<h3>인공지능기본법</h3>
        ${a.chapter ? `<span class="doc-chapter">${esc(a.chapter)}</span>` : ""}
        <div class="doc-title">${esc(a.article)}(${esc(a.title)})</div>
        <div class="doc-text">${esc(a.text)}</div>`;
    } catch {
      // 원문 조회에 실패하면 검색된 내용이라도 보여준다
      el.panelBody.innerHTML = `<h3>인공지능기본법</h3><div class="doc-title">${esc(s.article)}</div>
        <div class="doc-text">${esc(s.content.split("\n").slice(1).join("\n"))}</div>`;
    }
  }

  // ---------- 질문 보내기 ----------
  async function ask(question, { regenerateIndex = null } = {}) {
    if (busy) return;
    let c = active();
    if (!c) { c = { id: uid(), title: question.slice(0, 24), messages: [] }; chats.unshift(c); activeId = c.id; }

    if (regenerateIndex === null) {
      if (c.messages.length === 0) c.title = question.slice(0, 24) + (question.length > 24 ? "…" : "");
      c.messages.push({ role: "user", text: question, ts: Date.now() });
      c.messages.push({ role: "assistant", loading: true, ts: Date.now() });
    } else {
      c.messages[regenerateIndex] = { role: "assistant", loading: true, ts: Date.now() };
    }
    const slot = regenerateIndex ?? c.messages.length - 1;
    selectedSrc = null;
    setBusy(true);
    renderSidebar();
    renderMessages();

    try {
      const r = await fetch("/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question, regenerate: regenerateIndex !== null }),
      });
      const data = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(typeof data.detail === "string" ? data.detail : "서버에서 오류가 발생했어요.");
      c.messages[slot] = { role: "assistant", text: data.answer, sources: data.sources, ts: Date.now() };
    } catch (e) {
      const offline = e && e.name === "TypeError"; // fetch 네트워크 실패는 TypeError
      c.messages[slot] = { role: "assistant", error: true, text: offline ? "서버에 연결할 수 없어요. 서버가 켜져 있는지 확인해 주세요." : e.message, question, ts: Date.now() };
    }
    save();
    setBusy(false);
    renderSidebar();
    renderMessages();
  }

  const questionFor = (c, i) => {
    for (let k = i - 1; k >= 0; k--) if (c.messages[k].role === "user") return c.messages[k].text;
    return null;
  };

  // ---------- 이벤트 ----------
  el.form.addEventListener("submit", (e) => {
    e.preventDefault();
    const q = el.input.value.trim();
    if (!q || busy) return;
    el.input.value = "";
    ask(q);
  });
  // 한글 입력 중(조합 상태) Enter는 글자 확정이므로 전송하지 않는다: form submit은 조합 중에도 발생할 수 있어 키 이벤트에서 막는다
  el.input.addEventListener("keydown", (e) => { if (e.key === "Enter" && e.isComposing) e.preventDefault(); });

  el.chips.addEventListener("click", (e) => {
    if (e.target.closest("#moreToggle")) { chipsOpen = !chipsOpen; renderChips(); return; }
    const b = e.target.closest("[data-chip]");
    if (b) ask(b.dataset.chip);
  });

  el.newChat.addEventListener("click", () => {
    if (busy) return;
    const cur = active();
    if (cur && cur.messages.length === 0) { closeOverlays(); return; }
    const c = { id: uid(), title: "새 대화", messages: [] };
    chats.unshift(c); activeId = c.id; selectedSrc = null;
    save(); renderSidebar(); renderMessages(); renderPanelEmpty(); closeOverlays(); el.input.focus();
  });

  el.list.addEventListener("click", (e) => {
    const open = e.target.closest("[data-open]");
    const del = e.target.closest("[data-del]");
    if (del && !busy) {
      chats = chats.filter((c) => c.id !== del.dataset.del);
      if (activeId === del.dataset.del) activeId = chats[0]?.id ?? null;
      selectedSrc = null; save(); renderSidebar(); renderMessages(); renderPanelEmpty();
    } else if (open && !busy) {
      activeId = open.dataset.open; selectedSrc = null;
      renderSidebar(); renderMessages(); renderPanelEmpty(); closeOverlays();
    }
  });

  el.messages.addEventListener("click", async (e) => {
    const c = active();
    const view = e.target.closest("[data-view]");
    const tog = e.target.closest("[data-toggle]");
    const copy = e.target.closest("[data-copy]");
    const redo = e.target.closest("[data-redo]");
    if (view) { const [i, j] = view.dataset.view.split(":").map(Number); showArticle(i, j); }
    else if (tog) {
      const open = tog.getAttribute("aria-expanded") === "true";
      tog.setAttribute("aria-expanded", String(!open));
      tog.closest(".src").querySelector(".src-body").hidden = open;
    } else if (copy && c) {
      const text = c.messages[Number(copy.dataset.copy)].text;
      const done = () => { const old = copy.innerHTML; copy.textContent = "복사했어요"; setTimeout(() => { copy.innerHTML = old; }, 1400); };
      try { await navigator.clipboard.writeText(text); done(); }
      catch {
        const t = document.createElement("textarea"); t.value = text; t.style.position = "fixed"; t.style.opacity = "0";
        document.body.appendChild(t); t.select();
        try { document.execCommand("copy"); done(); } catch { /* 복사 불가 환경 */ }
        t.remove();
      }
    } else if (redo && c && !busy) {
      const i = Number(redo.dataset.redo);
      const q = c.messages[i].error && c.messages[i].question ? c.messages[i].question : questionFor(c, i);
      if (q) ask(q, { regenerateIndex: i });
    }
  });

  el.menu.addEventListener("click", () => { el.sidebar.classList.add("open"); el.scrim.hidden = false; });
  el.panelClose.addEventListener("click", closeOverlays);
  el.scrim.addEventListener("click", closeOverlays);
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeOverlays(); });

  // ---------- 시작 ----------
  renderSidebar(); renderMessages(); renderChips(); renderPanelEmpty();
  el.input.focus();
})();
