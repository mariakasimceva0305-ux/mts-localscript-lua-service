const state = {
  messages: [],
  validationTimer: null,
  isDark: false,
  marked: null,
  hljs: null,
  editorApi: null,
  workMode: "new",
  depth: "fast",
  discussionMode: false,
  profile: "guest",
  lastReady: null,
  lastChunksCount: 0,
  lastRetrievedChunks: [],
  resultTab: "check",
  chatMemory: {
    recent: [],
    summary: "",
    lastTask: "",
    lastCode: "",
    lastAssistantResponse: "",
    pendingClarification: null,
  },
};

const LS_KEYS = {
  profile: "localscript_profile",
  notes: "localscript_notes",
  history: "localscript_history",
  drafts: "localscript_drafts",
  uiSettings: "localscript_ui_settings",
  splitPct: "localscript_split_pct",
  layout: "localscript_layout",
};

const DEFAULT_UI_SETTINGS = {
  theme: "dark",
  uiScale: 100,
  codeFontPx: 14,
  defaultDeep: false,
  preferDiagnosticsTab: false,
  saveHistory: true,
  catRunnerEnabled: true,
  catRunnerHeight: 80,
  catRunnerUrl: "/media/cat_runner.png",
};

/** Раньше по умолчанию был mp4 — в localStorage остался старый кот. Переводим на PNG. */
function isLegacyBundledCatVideoUrl(url) {
  const u = String(url || "").trim();
  if (!u) return false;
  if (u === "/media/cat_runner.mp4") return true;
  try {
    const p = new URL(u, "http://localscript.invalid").pathname;
    return p === "/media/cat_runner.mp4";
  } catch {
    return false;
  }
}

function normalizeCatRunnerUrl(raw) {
  const u = String(raw ?? "").trim();
  if (!u) return DEFAULT_UI_SETTINGS.catRunnerUrl;
  if (isLegacyBundledCatVideoUrl(u)) return DEFAULT_UI_SETTINGS.catRunnerUrl;
  return u;
}

const CLARIFICATION_HINT_CHIPS = [
  "Нужно вернуть значение wf.vars.<поле> для сценария …",
  "Исправить существующий код: …",
  "Работа с массивом из wf.initVariables …",
];

const CHAT_MEMORY_LIMITS = {
  recentMessages: 6,
  msgChars: 280,
  summaryChars: 520,
  codeChars: 900,
  responseChars: 420,
  promptChars: 1800,
};

function getUiSettings() {
  try {
    const raw = localStorage.getItem(LS_KEYS.uiSettings);
    if (!raw) return { ...DEFAULT_UI_SETTINGS };
    const o = JSON.parse(raw);
    const merged = { ...DEFAULT_UI_SETTINGS, ...o };
    const prev = merged.catRunnerUrl;
    merged.catRunnerUrl = normalizeCatRunnerUrl(merged.catRunnerUrl);
    if (merged.catRunnerUrl !== prev) {
      try {
        localStorage.setItem(LS_KEYS.uiSettings, JSON.stringify({ ...DEFAULT_UI_SETTINGS, ...o, catRunnerUrl: merged.catRunnerUrl }));
      } catch {
        /* ignore */
      }
    }
    return merged;
  } catch {
    return { ...DEFAULT_UI_SETTINGS };
  }
}

function saveUiSettings(s) {
  try {
    localStorage.setItem(LS_KEYS.uiSettings, JSON.stringify({ ...DEFAULT_UI_SETTINGS, ...s }));
  } catch {
    /* ignore */
  }
}

function applyUiSettingsToDom(s) {
  document.documentElement.style.fontSize = `${s.uiScale}%`;
  document.documentElement.style.setProperty("--code-font-size", `${s.codeFontPx}px`);
  document.documentElement.style.setProperty("--code-line-height", `${Math.round(s.codeFontPx * 1.55)}px`);
  const dark = s.theme === "dark";
  state.isDark = dark;
  document.documentElement.classList.toggle("theme-dark", dark);
  document.body.classList.toggle("theme-dark", dark);
  if (s.defaultDeep) {
    state.depth = "deep";
  } else {
    state.depth = "fast";
  }
  applyCatRunnerSettings(s);
}

function catRunnerUrlIsImage(url) {
  return /\.(png|jpe?g|gif|webp|svg)(\?|#|$)/i.test(String(url || ""));
}

function applyCatRunnerSettings(s = getUiSettings()) {
  const rail = document.getElementById("catRunnerRail");
  const vid = document.getElementById("catRunnerVideo");
  const sprite = document.getElementById("catRunnerSprite");
  const sprite2 = document.getElementById("catRunnerSprite2");
  const sprite3 = document.getElementById("catRunnerSprite3");
  const trio = document.getElementById("catRunnerTrio");
  if (!rail || !vid) return;
  const on = s.catRunnerEnabled !== false;
  const h = Math.min(160, Math.max(36, Number(s.catRunnerHeight) || 80));
  const url = String(s.catRunnerUrl || "/media/cat_runner.png").trim() || "/media/cat_runner.png";
  document.documentElement.style.setProperty("--cat-rail-h", `${h}px`);
  const hideExtraCatSprites = () => {
    [sprite2, sprite3].forEach((el) => {
      if (!el) return;
      el.removeAttribute("src");
      el.hidden = true;
    });
  };
  if (!on) {
    rail.classList.remove("cat-runner-rail--on");
    rail.setAttribute("aria-hidden", "true");
    vid.pause?.();
    vid.removeAttribute("src");
    vid.load?.();
    vid.hidden = false;
    if (sprite) {
      sprite.removeAttribute("src");
      sprite.hidden = true;
    }
    hideExtraCatSprites();
    trio?.classList.remove("cat-runner-trio--video-only");
    return;
  }
  rail.classList.add("cat-runner-rail--on");
  rail.setAttribute("aria-hidden", "false");
  const useImage = Boolean(sprite) && catRunnerUrlIsImage(url);
  if (useImage && sprite) {
    trio?.classList.remove("cat-runner-trio--video-only");
    vid.pause?.();
    vid.removeAttribute("src");
    vid.load?.();
    vid.hidden = true;
    const abs = new URL(url, window.location.origin).href;
    [sprite, sprite2, sprite3].filter(Boolean).forEach((el) => {
      if (el.src !== abs) el.src = url;
      el.hidden = false;
    });
  } else {
    trio?.classList.add("cat-runner-trio--video-only");
    if (sprite) {
      sprite.removeAttribute("src");
      sprite.hidden = true;
    }
    hideExtraCatSprites();
    vid.hidden = false;
    if (vid.src !== new URL(url, window.location.origin).href) {
      vid.src = url;
    }
    vid.play?.().catch(() => {});
  }
}

function openPlatformMenu() {
  const dlg = document.getElementById("platformMenuDialog");
  if (!dlg) return;
  const s = getUiSettings();
  const en = document.getElementById("catRunnerEnabled");
  const hh = document.getElementById("catRunnerHeight");
  const uu = document.getElementById("catRunnerUrl");
  if (en) en.checked = s.catRunnerEnabled !== false;
  if (hh) hh.value = String(s.catRunnerHeight ?? 80);
  if (uu) uu.value = s.catRunnerUrl || "/media/cat_runner.png";
  const themeEl = document.getElementById("settingTheme");
  const scaleEl = document.getElementById("settingUiScale");
  const fontEl = document.getElementById("settingCodeFont");
  const deepEl = document.getElementById("settingDefaultDeep");
  const histEl = document.getElementById("settingSaveHistory");
  const diagTabEl = document.getElementById("settingPreferDiagTab");
  if (themeEl) themeEl.value = s.theme === "dark" ? "dark" : "light";
  if (scaleEl) scaleEl.value = String(s.uiScale || 100);
  if (fontEl) fontEl.value = String(s.codeFontPx || 14);
  if (deepEl) deepEl.checked = Boolean(s.defaultDeep);
  if (histEl) histEl.checked = s.saveHistory !== false;
  if (diagTabEl) diagTabEl.checked = Boolean(s.preferDiagnosticsTab);
  const ob = document.getElementById("platformOverflowBtn");
  if (ob) ob.setAttribute("aria-expanded", "true");
  try {
    if (typeof dlg.showModal === "function") {
      dlg.showModal();
    } else {
      showToast("Окно настроек недоступно в этом браузере");
    }
  } catch (e) {
    console.warn("showModal", e);
    showToast("Закройте другое окно или обновите страницу");
    if (ob) ob.setAttribute("aria-expanded", "false");
  }
}

function closePlatformMenu() {
  const dlg = document.getElementById("platformMenuDialog");
  dlg?.close();
  document.getElementById("platformOverflowBtn")?.setAttribute("aria-expanded", "false");
}

function savePlatformMenuSettings() {
  const themeEl = document.getElementById("settingTheme");
  const scaleEl = document.getElementById("settingUiScale");
  const fontEl = document.getElementById("settingCodeFont");
  const deepEl = document.getElementById("settingDefaultDeep");
  const histEl = document.getElementById("settingSaveHistory");
  const diagTabEl = document.getElementById("settingPreferDiagTab");
  const next = {
    ...getUiSettings(),
    catRunnerEnabled: document.getElementById("catRunnerEnabled")?.checked !== false,
    catRunnerHeight: Number(document.getElementById("catRunnerHeight")?.value) || 80,
    catRunnerUrl: (document.getElementById("catRunnerUrl")?.value || "").trim() || "/media/cat_runner.png",
    theme: themeEl?.value === "dark" ? "dark" : "light",
    uiScale: Number(scaleEl?.value) || 100,
    codeFontPx: Number(fontEl?.value) || 14,
    defaultDeep: Boolean(deepEl?.checked),
    preferDiagnosticsTab: Boolean(diagTabEl?.checked),
    saveHistory: histEl?.checked !== false,
  };
  saveUiSettings(next);
  applyUiSettingsToDom(next);
  updateModeUI();
  refreshCodeFontInEditor();
  if (editor && editorThemeCompartment && oneDarkTheme && mtsLightTheme) {
    editor.dispatch({
      effects: editorThemeCompartment.reconfigure(state.isDark ? oneDarkTheme : mtsLightTheme),
    });
  }
  showToast("Сохранено", 1800);
  closePlatformMenu();
}

function triggerEditorCriticalFeedback() {
  const wrap = document.getElementById("editorWrap");
  if (!wrap) return;
  wrap.classList.remove("editor-wrap--critical");
  void wrap.offsetWidth;
  wrap.classList.add("editor-wrap--critical");
  setTimeout(() => wrap.classList.remove("editor-wrap--critical"), 650);
}

function openSourceDocViewer(index) {
  const chunk = state.lastRetrievedChunks[index];
  if (!chunk) return;
  const dlg = document.getElementById("sourceDocDialog");
  const titleEl = document.getElementById("sourceDocTitle");
  const metaEl = document.getElementById("sourceDocMeta");
  const bodyEl = document.getElementById("sourceDocBody");
  if (!dlg || !titleEl || !metaEl || !bodyEl) return;
  const src = [chunk.source, chunk.kind].filter(Boolean).join(" · ") || `Фрагмент ${index + 1}`;
  titleEl.textContent = src;
  const score = chunk.score != null ? `Релевантность: ${Number(chunk.score).toFixed(3)}` : "";
  metaEl.textContent = [score, "Локальный корпус знаний"].filter(Boolean).join(" · ");
  const text = (chunk.text || chunk.text_preview || "").replace(/\r\n/g, "\n");
  bodyEl.textContent = text || "(пустой фрагмент)";
  dlg.showModal();
}

function renderEditorSourcesStrip() {
  const strip = document.getElementById("editorSourcesStrip");
  const chips = document.getElementById("editorSourcesChips");
  if (!strip || !chips) return;
  const list = state.lastRetrievedChunks || [];
  chips.innerHTML = "";
  if (!list.length) {
    strip.hidden = true;
    return;
  }
  strip.hidden = false;
  list.forEach((chunk, i) => {
    const label = [chunk.source, chunk.kind].filter(Boolean).join(" · ") || `Фрагмент ${i + 1}`;
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "source-chip";
    btn.setAttribute("role", "listitem");
    btn.textContent = label.length > 44 ? `${label.slice(0, 43)}…` : label;
    btn.title = `Открыть: ${label}`;
    btn.addEventListener("click", () => openSourceDocViewer(i));
    chips.appendChild(btn);
  });
}

function setResultTab(tabId) {
  const allowed = ["check", "chunks", "explain", "help"];
  const id = allowed.includes(tabId) ? tabId : "check";
  state.resultTab = id;
  document.querySelectorAll(".result-tab").forEach((btn) => {
    const on = btn.dataset.resultTab === id;
    btn.classList.toggle("active", on);
    btn.setAttribute("aria-selected", on ? "true" : "false");
  });
  const panels = {
    check: "tab-panel-check",
    chunks: "tab-panel-chunks",
    explain: "tab-panel-explain",
    help: "tab-panel-help",
  };
  Object.entries(panels).forEach(([key, pid]) => {
    const el = document.getElementById(pid);
    if (el) el.hidden = key !== id;
  });
}

function glanceValidationSummary(v) {
  if (v == null || typeof v !== "object") return "—";
  if (!Object.keys(v).length) return "—";
  const hard = Array.isArray(v.hard_errors) ? v.hard_errors.length : 0;
  const warns = Array.isArray(v.warnings) ? v.warnings.length : 0;
  const hints = Array.isArray(v.hints) ? v.hints.length : 0;
  if (hard > 0) return `Критичные ошибки: ${hard}`;
  if (v.syntax_ok) {
    if (!warns && !hints) return "Ок, замечаний нет";
    return `Ок · предупр. ${warns} · подсказки ${hints}`;
  }
  return "Требуется внимание";
}

function updateResultGlance(data, validation, chunksCount = null) {
  const gs = document.getElementById("glanceStatus");
  const gm = document.getElementById("glanceModel");
  const gi = document.getElementById("glanceIterations");
  const gr = document.getElementById("glanceReflexion");
  const gfc = document.getElementById("glanceFallback");
  const gc = document.getElementById("glanceChunks");
  const gv = document.getElementById("glanceValidation");
  if (!gs) return;

  const status = data?.status || "—";
  const isClarify = status === "needs_clarification";
  gs.textContent = isClarify ? "Нужно уточнение" : status;
  gs.className = `result-glance-v${isClarify ? " result-glance-v--amber" : ""}`;

  if (gm) gm.textContent = data?.used_model ?? "—";
  if (gi) gi.textContent = data?.iterations != null ? String(data.iterations) : "—";
  if (gr) gr.textContent = data?.reflexion_applied === true ? "да" : data?.reflexion_applied === false ? "нет" : "—";

  if (gfc) {
    const fu = data?.fallback_used;
    gfc.className = "result-glance-v";
    if (fu === true) {
      const reason = data?.fallback_reason ? String(data.fallback_reason).trim() : "";
      gfc.textContent = reason ? `да · ${reason.slice(0, 120)}${reason.length > 120 ? "…" : ""}` : "да";
      gfc.classList.add("result-glance-v--amber");
    } else if (fu === false) {
      gfc.textContent = "нет";
    } else {
      gfc.textContent = "—";
    }
  }

  const nChunks = chunksCount != null ? chunksCount : state.lastChunksCount;
  if (gc) gc.textContent = nChunks != null ? String(nChunks) : "—";

  const vline = glanceValidationSummary(validation ?? data?.validation);
  if (gv) {
    gv.textContent = vline;
    gv.className = "result-glance-v";
    const v = validation ?? data?.validation;
    const hard = v?.hard_errors?.length > 0;
    if (hard || vline.includes("Требуется")) gv.classList.add("result-glance-v--bad");
    else if (v?.syntax_ok && !hard) gv.classList.add("result-glance-v--ok");
  }

  const root = document.getElementById("resultGlance");
  if (root) {
    root.classList.remove("result-glance--ok", "result-glance--warn", "result-glance--bad", "result-glance--clarify");
    if (isClarify) root.classList.add("result-glance--clarify");
    else if (status === "error" || String(status).toLowerCase().includes("fail")) root.classList.add("result-glance--bad");
    else {
      const v = validation ?? data?.validation;
      if (v?.hard_errors?.length > 0) root.classList.add("result-glance--bad");
      else if (v?.syntax_ok) root.classList.add("result-glance--ok");
      else if (v) root.classList.add("result-glance--warn");
    }
  }
}

function maybeOpenPreferredResultTab(data) {
  if (!getUiSettings().preferDiagnosticsTab) return;
  if (data?.status === "needs_clarification") return;
  const acc = document.getElementById("resultMetaAccordion");
  if (acc) acc.open = true;
}

function setEditorArtifactStatus(text, ms = 3200) {
  if (!editorArtifactStatus) return;
  const t = text?.trim();
  if (!t) {
    editorArtifactStatus.hidden = true;
    editorArtifactStatus.textContent = "";
    return;
  }
  editorArtifactStatus.textContent = t;
  editorArtifactStatus.hidden = false;
  clearTimeout(setEditorArtifactStatus._t);
  if (ms > 0) {
    setEditorArtifactStatus._t = setTimeout(() => {
      editorArtifactStatus.hidden = true;
    }, ms);
  }
}

function refreshCodeFontInEditor() {
  if (editor && codeFontCompartment && state.editorApi?.EditorView) {
    editor.dispatch({
      effects: codeFontCompartment.reconfigure(buildCodeFontTheme(state.editorApi.EditorView)),
    });
  }
  if (fallbackTextArea) {
    const px = getUiSettings().codeFontPx || 14;
    fallbackTextArea.style.fontSize = `${px}px`;
    fallbackTextArea.style.lineHeight = `${Math.round(px * 1.55)}px`;
  }
}

function scrollToResultPanel() {
  document.querySelector(".status-panel")?.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function clipText(value, max) {
  const s = String(value || "").replace(/\s+/g, " ").trim();
  if (!s) return "";
  return s.length > max ? `${s.slice(0, max - 1)}…` : s;
}

function rememberChatMessage(role, text) {
  const body = clipText(text, CHAT_MEMORY_LIMITS.msgChars);
  if (!body) return;
  state.chatMemory.recent.push({ role, text: body, at: Date.now() });
  if (state.chatMemory.recent.length > CHAT_MEMORY_LIMITS.recentMessages) {
    state.chatMemory.recent = state.chatMemory.recent.slice(-CHAT_MEMORY_LIMITS.recentMessages);
  }
  const users = state.chatMemory.recent.filter((m) => m.role === "user").slice(-2).map((m) => m.text).join(" | ");
  const assistants = state.chatMemory.recent
    .filter((m) => m.role === "assistant")
    .slice(-1)
    .map((m) => m.text)
    .join(" | ");
  state.chatMemory.summary = clipText(
    [users ? `Пользователь: ${users}` : "", assistants ? `Ассистент: ${assistants}` : ""].filter(Boolean).join(" || "),
    CHAT_MEMORY_LIMITS.summaryChars,
  );
}

function isFollowupPrompt(prompt) {
  const raw = (prompt || "").trim();
  const p = raw.toLowerCase();
  if (!p) return false;
  const words = p.split(/\s+/).filter(Boolean);
  const short = words.length <= 15;
  const mem = state.chatMemory;
  const hasThread = Boolean(mem.lastTask && mem.lastCode);

  const followupMarkers = [
    "теперь",
    "еще",
    "ещё",
    "добавь",
    "сделай",
    "перепиши",
    "исправь",
    "объясни",
    "почему",
    "короче",
    "безопас",
    "улучши",
    "убери",
    "замени",
    "верни",
    "напиши",
    "продолж",
 ];
  if (short && followupMarkers.some((m) => p.includes(m))) return true;

  // Короткая реплика при уже имеющемся коде/задаче — продолжение (да/ок/так же и т.д.)
  if (hasThread && words.length <= 5 && raw.length <= 48) {
    const ack = /^(да|ок|okay|ok|угу|ага|принято|спасибо|так|ладно|хорошо|продолжай|давай)\.?$/i;
    if (ack.test(raw.trim())) return true;
  }
  return false;
}

function composeFollowupPrompt(prompt) {
  const mem = state.chatMemory;
  const contextBits = [];
  if (mem.lastTask) contextBits.push(`Последняя задача: ${clipText(mem.lastTask, 220)}`);
  if (mem.summary) contextBits.push(`Краткий контекст: ${clipText(mem.summary, 280)}`);
  if (mem.lastCode) {
    contextBits.push(`Последний код:\n\`\`\`lua\n${clipText(mem.lastCode, 420)}\n\`\`\``);
  }
  const base = contextBits.length ? `${contextBits.join("\n\n")}\n\n` : "";
  const merged = `${base}Текущее продолжение пользователя: ${prompt}\nСохрани контекст и выдай обновлённый корректный Lua-код.`;
  return clipText(merged, CHAT_MEMORY_LIMITS.promptChars);
}

function composeClarificationPrompt(answerText) {
  const pend = state.chatMemory.pendingClarification;
  if (!pend) return answerText;
  const text = `Исходная задача: ${pend.originalPrompt}\nУточняющий вопрос: ${pend.question}\nОтвет пользователя: ${answerText}\nСформируй итоговый Lua-код по уточнённой задаче.`;
  return clipText(text, CHAT_MEMORY_LIMITS.promptChars);
}

function buildGenerateContext() {
  const mem = state.chatMemory;
  const code = editorText().trim();
  return {
    recent_messages: mem.recent.slice(-CHAT_MEMORY_LIMITS.recentMessages),
    chat_summary: clipText(mem.summary, CHAT_MEMORY_LIMITS.summaryChars),
    previous_code: clipText(code || mem.lastCode, CHAT_MEMORY_LIMITS.codeChars),
    last_user_task: clipText(mem.lastTask, CHAT_MEMORY_LIMITS.msgChars),
    last_assistant_response: clipText(mem.lastAssistantResponse, CHAT_MEMORY_LIMITS.responseChars),
    pending_clarification: mem.pendingClarification
      ? {
          original_prompt: clipText(mem.pendingClarification.originalPrompt, CHAT_MEMORY_LIMITS.msgChars),
          question: clipText(mem.pendingClarification.question, CHAT_MEMORY_LIMITS.msgChars),
        }
      : null,
  };
}

const DEMO_SCENARIOS = {
  simple: {
    mode: "new",
    prompt: "Верни значение переменной userName из wf.vars для сценария Octapi.",
    code: "",
  },
  edit: {
    mode: "edit",
    prompt: "Исправь: добавь проверку на пустой массив перед взятием последнего элемента.",
    code: 'return wf.vars.items[#wf.vars.items]',
  },
  clarify: {
    mode: "new",
    prompt: "сделай скрипт",
    code: "",
  },
  complex: {
    mode: "new",
    prompt:
      "MWS Octapi Lua: в wf.initVariables задан массив чисел numbers. Нужно посчитать сумму всех элементов и вернуть её через return. Используй _utils.array если уместно.",
    code: "",
  },
};

const EXAMPLE_PROMPT =
  "Верни последний элемент массива emails из wf.vars (массив не пустой).";

const chatLog = document.getElementById("chatLog");

/** Прокрутка левой колонки «Работа с кодом» вниз (примеры → чат → ввод → заметки). */
function scrollChatWorkPaneToBottom() {
  const inner = document.querySelector("#splitChatPane .split-pane-inner");
  if (!inner) return;
  requestAnimationFrame(() => {
    inner.scrollTop = inner.scrollHeight;
  });
}

const promptInput = document.getElementById("promptInput");
const healthBadge = document.getElementById("healthBadge");
const readyBadge = document.getElementById("readyBadge");
const profileLabel = document.getElementById("profileLabel");
const validationSummary = document.getElementById("validationSummary");
const validationSuccessBanner = document.getElementById("validationSuccessBanner");
const validationHardList = document.getElementById("validationHardList");
const validationWarnList = document.getElementById("validationWarnList");
const validationHintList = document.getElementById("validationHintList");
const validationHardEmpty = document.getElementById("validationHardEmpty");
const validationWarnEmpty = document.getElementById("validationWarnEmpty");
const validationHintEmpty = document.getElementById("validationHintEmpty");
const validationDot = document.getElementById("validationDot");
const validationExplanation = document.getElementById("validationExplanation");
const diagnosticsPanel = document.getElementById("diagnosticsPanel");
const diagnosticsDl = document.getElementById("diagnosticsDl");
const retrievedChunksEl = document.getElementById("retrievedChunks");
const chunksHint = document.getElementById("chunksHint");
const editModal = document.getElementById("editModal");
const editInstruction = document.getElementById("editInstruction");
const editorRoot = document.getElementById("editorRoot");
const editorEmptyState = document.getElementById("editorEmptyState");
const luaFileInput = document.getElementById("luaFileInput");
const modeHint = document.getElementById("modeHint");
const notesArea = document.getElementById("notesArea");
const historyList = document.getElementById("historyList");
const draftsList = document.getElementById("draftsList");
const toastEl = document.getElementById("toast");
const hotkeyHint = document.getElementById("hotkeyHint");
const notesEmptyHint = document.getElementById("notesEmptyHint");
const serviceAlert = document.getElementById("serviceAlert");
const clarificationCallout = document.getElementById("clarificationCallout");
const clarificationCalloutText = document.getElementById("clarificationCalloutText");
const clarificationReply = document.getElementById("clarificationReply");
const clarificationChips = document.getElementById("clarificationChips");
const editorArtifactStatus = document.getElementById("editorArtifactStatus");
let editor = null;
let fallbackTextArea = null;
let editorThemeCompartment = null;
let codeFontCompartment = null;
let mtsLightTheme = null;
let oneDarkTheme = null;
let vendorLibPromise = null;

function store() {
  return state.profile === "local" ? localStorage : sessionStorage;
}

function showToast(text, ms = 2600) {
  if (!toastEl) return;
  toastEl.textContent = text;
  toastEl.hidden = false;
  clearTimeout(showToast._t);
  showToast._t = setTimeout(() => {
    toastEl.hidden = true;
  }, ms);
}

function getVendorLib() {
  if (!vendorLibPromise) vendorLibPromise = import("/vendor/app-vendor.js");
  return vendorLibPromise;
}

function installPlainEditor() {
  const note = document.createElement("div");
  note.className = "editor-fallback-note";
  note.textContent = "Упрощённый редактор: без CodeMirror";

  const textarea = document.createElement("textarea");
  textarea.id = "codeEditorFallback";
  textarea.spellcheck = false;
  textarea.placeholder = "Lua код…";
  textarea.style.width = "100%";
  textarea.style.height = "100%";
  textarea.style.minHeight = "420px";
  textarea.style.border = "none";
  textarea.style.outline = "none";
  textarea.style.resize = "none";
  textarea.style.fontFamily = 'Consolas, "Courier New", monospace';
  const px = getUiSettings().codeFontPx || 14;
  textarea.style.fontSize = `${px}px`;
  textarea.style.lineHeight = `${Math.round(px * 1.55)}px`;
  textarea.style.padding = "10px";
  textarea.style.background = "transparent";
  textarea.style.color = "inherit";
  textarea.addEventListener("input", () => {
    if (state.validationTimer) clearTimeout(state.validationTimer);
    state.validationTimer = setTimeout(() => runValidation(true), 500);
    updateEditorEmptyState();
  });
  editorRoot.innerHTML = "";
  editorRoot.appendChild(note);
  editorRoot.appendChild(textarea);
  fallbackTextArea = textarea;
}

function buildCodeFontTheme(EditorView) {
  const px = getUiSettings().codeFontPx || 14;
  const lh = Math.round(px * 1.55);
  return EditorView.theme({
    ".cm-content, .cm-gutters": { fontSize: `${px}px` },
    ".cm-line, .cm-gutterElement": { fontSize: `${px}px`, lineHeight: `${lh}px` },
    ".cm-scroller": { lineHeight: `${lh}px` },
  });
}

async function initEditor() {
  try {
    const {
      EditorView,
      lineNumbers,
      Compartment,
      EditorState,
      lua,
      oneDark,
      syntaxHighlighting,
      defaultHighlightStyle,
      mtsLuaHighlight,
    } = await getVendorLib();

    const highlightStyle = mtsLuaHighlight ?? defaultHighlightStyle;

    state.editorApi = { EditorView, lineNumbers, Compartment, EditorState, lua };
    oneDarkTheme = oneDark;
    editorThemeCompartment = new Compartment();
    codeFontCompartment = new Compartment();
    mtsLightTheme = EditorView.theme({
      "&": { backgroundColor: "var(--panel-2)", color: "var(--text)" },
      ".cm-scroller": { backgroundColor: "var(--panel-2)" },
      ".cm-content": { caretColor: "var(--accent)" },
      ".cm-cursor, .cm-dropCursor": { borderLeftColor: "var(--accent)" },
      "&.cm-focused .cm-selectionBackground, .cm-selectionBackground, .cm-content ::selection": {
        backgroundColor: "#ffd8da",
      },
      ".cm-gutters": {
        backgroundColor: "var(--panel-2)",
        color: "var(--muted)",
      },
    });

    const editorState = EditorState.create({
      doc: "",
      extensions: [
        lineNumbers(),
        lua(),
        syntaxHighlighting(highlightStyle, { fallback: true }),
        EditorView.lineWrapping,
        editorThemeCompartment.of(state.isDark ? oneDarkTheme : mtsLightTheme),
        codeFontCompartment.of(buildCodeFontTheme(EditorView)),
        EditorView.updateListener.of((update) => {
          if (!update.docChanged) return;
          if (state.validationTimer) clearTimeout(state.validationTimer);
          state.validationTimer = setTimeout(() => runValidation(true), 500);
          updateEditorEmptyState();
        }),
      ],
    });

    editorRoot.innerHTML = "";
    editor = new EditorView({
      state: editorState,
      parent: editorRoot,
    });
    fallbackTextArea = null;
  } catch (error) {
    console.warn("CodeMirror unavailable, using textarea fallback.", error);
    installPlainEditor();
  }
  updateEditorEmptyState();
}

async function initOptionalLibraries() {
  try {
    const { marked, hljs } = await getVendorLib();
    state.marked = marked;
    state.hljs = hljs;
  } catch (error) {
    console.warn("Markdown/highlight libs unavailable.", error);
    state.marked = null;
    state.hljs = null;
  }
}

function editorText() {
  if (editor) return editor.state.doc.toString();
  return fallbackTextArea ? fallbackTextArea.value : "";
}

function setEditorText(code) {
  const normalized = code || "";
  if (editor) {
    editor.dispatch({
      changes: { from: 0, to: editor.state.doc.length, insert: normalized },
    });
  } else if (fallbackTextArea) {
    fallbackTextArea.value = normalized;
  }
  if (normalized.trim()) {
    state.chatMemory.lastCode = clipText(normalized, CHAT_MEMORY_LIMITS.codeChars);
  }
  updateEditorEmptyState();
}

function updateEditorEmptyState() {
  if (!editorEmptyState) return;
  const empty = !editorText().trim();
  editorEmptyState.hidden = !empty;
  editorEmptyState.setAttribute("aria-hidden", empty ? "false" : "true");
}

function autoResize(el) {
  el.style.height = "auto";
  el.style.height = `${Math.min(el.scrollHeight, 280)}px`;
}

let _splitDragPct = 70;

function applySplitRatio(pct) {
  const chat = document.getElementById("splitChatPane");
  if (!chat) return;
  const p = Math.min(82, Math.max(26, Number(pct) || 70));
  _splitDragPct = p;
  chat.style.flex = `0 0 ${p}%`;
  chat.style.maxWidth = `${p}%`;
}

function setWorkspaceLayout(mode) {
  const split = document.getElementById("workspaceSplit");
  if (!split) return;
  split.classList.remove("layout--chat-only", "layout--editor-only");
  if (mode === "chat") split.classList.add("layout--chat-only");
  if (mode === "editor") split.classList.add("layout--editor-only");
  document.querySelectorAll(".layout-btn").forEach((b) => {
    b.classList.toggle("active", b.dataset.layout === mode);
  });
  try {
    localStorage.setItem(LS_KEYS.layout, mode);
  } catch {
    /* ignore */
  }
  if (mode === "both") {
    let saved = _splitDragPct;
    try {
      const raw = localStorage.getItem(LS_KEYS.splitPct);
      if (raw != null) saved = Number(raw);
    } catch {
      /* ignore */
    }
    if (Number.isFinite(saved)) applySplitRatio(saved);
  }
}

function initWorkspaceSplitAndLayout() {
  const split = document.getElementById("workspaceSplit");
  const handle = document.getElementById("splitHandle");
  const chat = document.getElementById("splitChatPane");
  if (!split || !handle || !chat) return;

  try {
    const raw = localStorage.getItem(LS_KEYS.splitPct);
    if (raw != null) {
      const n = Number(raw);
      if (Number.isFinite(n)) _splitDragPct = n;
    }
  } catch {
    /* ignore */
  }

  let layout = "both";
  try {
    const l = localStorage.getItem(LS_KEYS.layout);
    if (l === "chat" || l === "editor" || l === "both") layout = l;
  } catch {
    /* ignore */
  }

  setWorkspaceLayout(layout);
  if (layout === "both") applySplitRatio(_splitDragPct);

  let dragging = false;

  function onMove(e) {
    if (!dragging) return;
    const rect = split.getBoundingClientRect();
    const w = rect.width || 1;
    const x = e.clientX - rect.left;
    const pct = (x / w) * 100;
    applySplitRatio(pct);
  }

  function onUp() {
    if (!dragging) return;
    dragging = false;
    document.body.style.cursor = "";
    document.body.style.userSelect = "";
    try {
      localStorage.setItem(LS_KEYS.splitPct, String(_splitDragPct));
    } catch {
      /* ignore */
    }
  }

  handle.addEventListener("mousedown", (e) => {
    if (split.classList.contains("layout--chat-only") || split.classList.contains("layout--editor-only")) return;
    e.preventDefault();
    dragging = true;
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
  });
  document.addEventListener("mousemove", onMove);
  document.addEventListener("mouseup", onUp);

  handle.addEventListener("keydown", (e) => {
    if (split.classList.contains("layout--chat-only") || split.classList.contains("layout--editor-only")) return;
    if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
    e.preventDefault();
    const delta = e.key === "ArrowLeft" ? -2 : 2;
    applySplitRatio(_splitDragPct + delta);
    try {
      localStorage.setItem(LS_KEYS.splitPct, String(_splitDragPct));
    } catch {
      /* ignore */
    }
  });

  document.getElementById("layoutBothBtn")?.addEventListener("click", () => setWorkspaceLayout("both"));
  document.getElementById("layoutChatBtn")?.addEventListener("click", () => setWorkspaceLayout("chat"));
  document.getElementById("layoutEditorBtn")?.addEventListener("click", () => setWorkspaceLayout("editor"));
}

function includeDiagnosticsFlag() {
  return state.depth === "deep";
}

function updatePrimaryButtonLabel() {
  const sendBtn = document.getElementById("sendBtn");
  if (!sendBtn) return;
  if (state.workMode === "validate") {
    sendBtn.textContent = "Проверить код";
  } else if (state.workMode === "edit") {
    sendBtn.textContent = "Применить правку";
  } else {
    sendBtn.textContent = "Сгенерировать по задаче";
  }
}

function setLoading(isLoading) {
  const sendBtn = document.getElementById("sendBtn");
  if (!sendBtn) return;
  sendBtn.disabled = isLoading;
  sendBtn.setAttribute("aria-busy", isLoading ? "true" : "false");
  if (isLoading) {
    sendBtn.textContent = "Выполняется…";
  } else {
    updatePrimaryButtonLabel();
  }
}

async function fetchJson(url, payload, timeoutMs = 600000) {
  const controller = new AbortController();
  const useTimeout = Number.isFinite(timeoutMs) && timeoutMs > 0;
  const timer = useTimeout ? setTimeout(() => controller.abort("request-timeout"), timeoutMs) : null;
  try {
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      signal: controller.signal,
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      const detail = data.detail || data.message || `HTTP ${res.status}`;
      throw new Error(detail);
    }
    return data;
  } catch (error) {
    if (error && error.name === "AbortError") {
      throw new Error("Превышено время ожидания ответа сервера");
    }
    throw error;
  } finally {
    if (timer) clearTimeout(timer);
  }
}

function renderDiagnosticsPanel(diag) {
  if (!diagnosticsDl || !diagnosticsPanel) return;
  diagnosticsDl.innerHTML = "";
  const emptyHint = document.getElementById("diagnosticsEmptyHint");
  if (!diag || typeof diag !== "object" || state.depth !== "deep") {
    diagnosticsPanel.hidden = true;
    if (emptyHint) emptyHint.hidden = false;
    return;
  }
  const entries = Object.entries(diag).filter(([, v]) => v != null && v !== "");
  if (!entries.length) {
    diagnosticsPanel.hidden = true;
    if (emptyHint) emptyHint.hidden = false;
    return;
  }
  diagnosticsPanel.hidden = false;
  if (emptyHint) emptyHint.hidden = true;
  const preferred = ["retrieval_chunks_count", "num_predict", "ollama_read_timeout_s", "gen1_prompt_chars", "gen1_response_chars", "stage", "final_stage"];
  const rest = entries.filter(([k]) => !preferred.includes(k));
  const ordered = [...preferred.map((k) => entries.find(([x]) => x === k)).filter(Boolean), ...rest];
  ordered.forEach(([k, v]) => {
    const dt = document.createElement("dt");
    dt.textContent = k;
    const dd = document.createElement("dd");
    dd.textContent = typeof v === "object" ? JSON.stringify(v) : String(v);
    diagnosticsDl.appendChild(dt);
    diagnosticsDl.appendChild(dd);
  });
}

function renderMeta(data) {
  const chunkCount = Array.isArray(data.retrieved_chunks) ? data.retrieved_chunks.length : state.lastChunksCount;
  updateResultGlance(data, data.validation, chunkCount);
  renderDiagnosticsPanel(data.diagnostics);
  maybeOpenPreferredResultTab(data);
}

function renderRetrievedChunks(chunks) {
  retrievedChunksEl.innerHTML = "";
  const list = Array.isArray(chunks) ? chunks : [];
  state.lastChunksCount = list.length;
  state.lastRetrievedChunks = list.map((c) => ({ ...c }));
  renderEditorSourcesStrip();
  if (!list.length) {
    const empty = document.createElement("div");
    empty.className = "chunk-empty";
    empty.innerHTML =
      "<p class=\"chunk-empty-title\">Фрагменты знаний ещё не загружены</p><p class=\"muted\">После успешного вызова генерации или правки здесь появятся отобранные чанки из <strong>локального</strong> корпуса (BM25 и ключевые слова). Пока запроса к модели не было — блок пустой.</p>";
    retrievedChunksEl.appendChild(empty);
    return;
  }
  list.forEach((chunk, i) => {
    const card = document.createElement("article");
    card.className = "chunk-card chunk-card--interactive";
    card.setAttribute("role", "listitem");
    card.tabIndex = 0;
    card.title = "Открыть фрагмент на платформе";
    const head = document.createElement("div");
    head.className = "chunk-card-head";
    const title = document.createElement("span");
    title.className = "chunk-card-source";
    title.textContent = [chunk.source, chunk.kind].filter(Boolean).join(" · ") || `Фрагмент ${i + 1}`;
    head.appendChild(title);
    if (chunk.score != null) {
      const sc = document.createElement("span");
      sc.className = "chunk-card-score";
      sc.textContent = Number(chunk.score).toFixed(2);
      head.appendChild(sc);
    }
    const body = document.createElement("p");
    body.className = "chunk-card-body";
    body.textContent = (chunk.text_preview || chunk.text || "").replace(/\s+/g, " ").trim().slice(0, 400);
    card.appendChild(head);
    card.appendChild(body);
    const open = () => openSourceDocViewer(i);
    card.addEventListener("click", open);
    card.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        open();
      }
    });
    retrievedChunksEl.appendChild(card);
  });
}

function setValidationVisual(ok, hasHardErrors) {
  if (hasHardErrors) validationDot.className = "status-dot error";
  else if (ok) validationDot.className = "status-dot success";
  else validationDot.className = "status-dot neutral";
}

function setValidationExplanation(text) {
  const t = text?.trim();
  validationExplanation.textContent = t || "Пояснение появится после генерации или правки.";
  validationExplanation.classList.toggle("muted", !t);
}

function fillList(ul, items, emptyEl) {
  ul.innerHTML = "";
  const arr = Array.isArray(items) ? items : [];
  emptyEl.hidden = arr.length > 0;
  arr.forEach((item) => {
    const li = document.createElement("li");
    li.textContent = item;
    ul.appendChild(li);
  });
}

function renderValidation(validation, brief = false) {
  const v = validation || {};
  const hard = v.hard_errors || [];
  const warns = v.warnings || [];
  const hints = v.hints || [];
  const syntaxOk = Boolean(v.syntax_ok);
  const hasHard = hard.length > 0;

  fillList(validationHardList, hard, validationHardEmpty);
  fillList(validationWarnList, warns, validationWarnEmpty);
  fillList(validationHintList, hints, validationHintEmpty);

  const allClear = syntaxOk && !hasHard;
  validationSuccessBanner.hidden = !allClear;
  setValidationVisual(syntaxOk, hasHard);

  validationSummary.classList.remove("validation-pill--neutral", "validation-pill--ok", "validation-pill--error");
  if (hasHard) {
    validationSummary.textContent = "Есть критичные ошибки";
    validationSummary.classList.add("validation-pill--error");
  } else if (syntaxOk) {
    validationSummary.textContent = "Синтаксис и правила: ок";
    validationSummary.classList.add("validation-pill--ok");
  } else {
    validationSummary.textContent = "Требуется внимание";
    validationSummary.classList.add("validation-pill--error");
  }

  if (brief && allClear) return;
  if (!brief && hasHard) triggerEditorCriticalFeedback();
}

function renderMarkdown(text) {
  if (!text) return "";
  if (!state.marked) {
    return text
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll("\n", "<br>");
  }
  const html = state.marked.parse(text);
  const holder = document.createElement("div");
  holder.innerHTML = html;
  if (state.hljs) {
    holder.querySelectorAll("pre code").forEach((node) => state.hljs.highlightElement(node));
  }
  return holder.innerHTML;
}

function hideClarificationCallout() {
  if (clarificationCallout) {
    clarificationCallout.hidden = true;
    if (clarificationCalloutText) clarificationCalloutText.textContent = "";
  }
  if (clarificationChips) clarificationChips.innerHTML = "";
  if (clarificationReply) clarificationReply.value = "";
}

function showClarificationCallout(text) {
  if (!clarificationCallout || !clarificationCalloutText) return;
  clarificationCalloutText.textContent = text || "";
  clarificationCallout.hidden = !text?.trim();
  if (clarificationChips) {
    clarificationChips.innerHTML = "";
    CLARIFICATION_HINT_CHIPS.forEach((hint) => {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "clar-chip";
      b.textContent = hint.length > 56 ? `${hint.slice(0, 55)}…` : hint;
      b.title = hint;
      b.addEventListener("click", () => {
        if (clarificationReply) {
          clarificationReply.value = hint;
          clarificationReply.focus();
        }
      });
      clarificationChips.appendChild(b);
    });
  }
  if (clarificationReply) clarificationReply.value = "";
  setResultTab("check");
  scrollToResultPanel();
}

function updateServiceAlert() {
  if (!serviceAlert) return;
  serviceAlert.classList.remove("service-alert--danger", "service-alert--warn");
  serviceAlert.innerHTML = "";
  const healthOk = Boolean(healthBadge?.classList.contains("status-pill--ok"));
  if (!healthOk) {
    serviceAlert.hidden = false;
    serviceAlert.classList.add("service-alert--danger");
    serviceAlert.innerHTML =
      "<strong>API недоступен.</strong> Запустите сервис API. Генерация и проверка недоступны.";
    return;
  }
  const readyOk = readyBadge?.classList.contains("status-pill--ok");
  if (!readyOk) {
    serviceAlert.hidden = false;
    serviceAlert.classList.add("service-alert--warn");
    const t = readyBadge?.textContent || "модели не готовы";
    serviceAlert.innerHTML = `<strong>Модели не готовы.</strong> ${t}. Проверка кода может работать без LLM.`;
    return;
  }
  serviceAlert.hidden = true;
}

function addMessage(role, payload, variant) {
  const box = document.createElement("article");
  box.className = `message ${role}`;
  if (variant === "clarification") box.classList.add("message--clarification");

  if (payload.text) {
    const p = document.createElement("div");
    p.className = payload.format === "plain" ? "message-body message-body--plain" : "message-body";
    if (payload.format === "plain") {
      p.textContent = payload.text;
    } else {
      p.innerHTML = renderMarkdown(payload.text);
    }
    if (role === "user") {
      const head = document.createElement("div");
      head.className = "message-head";
      const editBtn = document.createElement("button");
      editBtn.type = "button";
      editBtn.className = "edit-message-btn";
      editBtn.title = "Вставить в поле ввода";
      editBtn.setAttribute("aria-label", "Вставить в поле ввода");
      editBtn.innerHTML = `
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
          <path d="M17 3l4 4L7 21H3v-4L17 3z"></path>
        </svg>
      `;
      editBtn.addEventListener("click", () => {
        const sourceText = p.textContent?.trim();
        if (!sourceText) return;
        promptInput.value = sourceText;
        autoResize(promptInput);
        promptInput.focus();
      });
      head.appendChild(p);
      head.appendChild(editBtn);
      box.appendChild(head);
    } else {
      box.appendChild(p);
    }
  }

  if (payload.code) {
    const pre = document.createElement("pre");
    const code = document.createElement("code");
    code.className = "language-lua";
    code.textContent = payload.code;
    pre.appendChild(code);
    if (state.hljs) state.hljs.highlightElement(code);
    box.appendChild(pre);

    const actions = document.createElement("div");
    actions.className = "msg-actions";
    const applyBtn = document.createElement("button");
    applyBtn.type = "button";
    applyBtn.textContent = "В редактор";
    applyBtn.addEventListener("click", () => setEditorText(payload.code));
    actions.appendChild(applyBtn);
    box.appendChild(actions);
  }

  if (payload.docs?.length) {
    const details = document.createElement("details");
    details.innerHTML = "<summary>Фрагменты в ответе</summary>";
    const ul = document.createElement("ul");
    payload.docs.forEach((chunk) => {
      const li = document.createElement("li");
      li.textContent = `[${chunk.source}/${chunk.kind}] ${chunk.text_preview || chunk.text || ""}`;
      ul.appendChild(li);
    });
    details.appendChild(ul);
    box.appendChild(details);
  }

  if (payload.explanation) {
    setValidationExplanation(payload.explanation);
  }

  chatLog.appendChild(box);
  scrollChatWorkPaneToBottom();
}

function pushHistory(entry) {
  if (!getUiSettings().saveHistory) return;
  try {
    const raw = store().getItem(LS_KEYS.history);
    const arr = raw ? JSON.parse(raw) : [];
    if (!Array.isArray(arr)) return;
    arr.unshift(entry);
    store().setItem(LS_KEYS.history, JSON.stringify(arr.slice(0, 40)));
    renderHistory();
  } catch (_) {
    /* ignore */
  }
}

function renderHistory() {
  historyList.innerHTML = "";
  let arr = [];
  try {
    const raw = store().getItem(LS_KEYS.history);
    arr = raw ? JSON.parse(raw) : [];
  } catch (_) {
    arr = [];
  }
  if (!Array.isArray(arr) || !arr.length) {
    const li = document.createElement("li");
    li.className = "empty-state-inline";
    li.innerHTML =
      "<span class=\"muted\">Пока пусто. После генерации или правки здесь появятся последние запросы. Быстрый старт — карточки <strong>Попробовать пример</strong> в блоке «Работа с кодом».</span>";
    historyList.appendChild(li);
    return;
  }
  arr.slice(0, 15).forEach((h) => {
    const li = document.createElement("li");
    const a = document.createElement("button");
    a.type = "button";
    a.className = "history-item";
    const t = new Date(h.at || Date.now()).toLocaleString();
    a.textContent = `[${h.mode || "?"}] ${(h.prompt || "").slice(0, 72)}${(h.prompt || "").length > 72 ? "…" : ""} · ${t}`;
    a.addEventListener("click", () => {
      promptInput.value = h.prompt || "";
      autoResize(promptInput);
      if (h.mode === "new" || h.mode === "edit") setWorkMode(h.mode);
    });
    li.appendChild(a);
    historyList.appendChild(li);
  });
}

function saveDraftsList(drafts) {
  try {
    store().setItem(LS_KEYS.drafts, JSON.stringify(drafts.slice(0, 30)));
    renderDrafts();
  } catch (_) {
    showToast("Не удалось сохранить черновик");
  }
}

function renderDrafts() {
  draftsList.innerHTML = "";
  let drafts = [];
  try {
    const raw = store().getItem(LS_KEYS.drafts);
    drafts = raw ? JSON.parse(raw) : [];
  } catch (_) {
    drafts = [];
  }
  if (!Array.isArray(drafts) || !drafts.length) {
    const li = document.createElement("li");
    li.className = "empty-state-inline";
    li.innerHTML =
      "<span class=\"muted\">Нет сохранённых черновиков. Кнопки <strong>Черновик</strong> / <strong>В черновик</strong> в блоке «Работа с кодом» сохраняют Lua в браузер (при локальном профиле).</span>";
    draftsList.appendChild(li);
    return;
  }
  drafts.forEach((d, idx) => {
    const li = document.createElement("li");
    const row = document.createElement("div");
    row.className = "draft-row";
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "history-item";
    btn.textContent = d.title || `Черновик ${idx + 1}`;
    btn.addEventListener("click", () => setEditorText(d.code || ""));
    const del = document.createElement("button");
    del.type = "button";
    del.className = "ghost-btn tiny";
    del.textContent = "×";
    del.addEventListener("click", (e) => {
      e.stopPropagation();
      drafts.splice(idx, 1);
      saveDraftsList(drafts);
    });
    row.appendChild(btn);
    row.appendChild(del);
    li.appendChild(row);
    draftsList.appendChild(li);
  });
}

function saveNotes() {
  try {
    store().setItem(LS_KEYS.notes, notesArea.value || "");
  } catch (_) {
    /* ignore */
  }
}

function loadPersistedUi() {
  try {
    const prof = localStorage.getItem(LS_KEYS.profile);
    if (prof === "local" || prof === "guest") {
      state.profile = prof;
    }
  } catch (_) {
    /* ignore */
  }
  syncProfileButtons();
  updateProfileLabel();
  try {
    notesArea.value = store().getItem(LS_KEYS.notes) || "";
  } catch (_) {
    notesArea.value = "";
  }
  updateNotesHint();
  renderHistory();
  renderDrafts();
}

function updateProfileLabel() {
  if (!profileLabel) return;
  profileLabel.textContent = state.profile === "local" ? "локальный" : "гость";
}

function syncProfileButtons() {
  document.getElementById("profileGuestBtn")?.classList.toggle("active", state.profile === "guest");
  document.getElementById("profileLocalBtn")?.classList.toggle("active", state.profile === "local");
}

function setProfile(profile) {
  state.profile = profile === "local" ? "local" : "guest";
  try {
    localStorage.setItem(LS_KEYS.profile, state.profile);
  } catch (_) {
    /* ignore */
  }
  syncProfileButtons();
  updateProfileLabel();
  loadPersistedUi();
  showToast(state.profile === "local" ? "Профиль: локальный" : "Профиль: гость", 2400);
}

function updateNotesHint() {
  if (!notesEmptyHint) return;
  const has = Boolean(notesArea.value.trim());
  notesEmptyHint.hidden = has;
}

function updateModeUI() {
  document.querySelectorAll(".mode-btn").forEach((b) => {
    b.classList.toggle("active", b.dataset.workMode === state.workMode);
  });
  document.getElementById("depthFastBtn").classList.toggle("active", state.depth === "fast");
  document.getElementById("depthDeepBtn").classList.toggle("active", state.depth === "deep");

  const hints = {
    new: "Новый скрипт: текст задачи. Код редактора в запрос не входит.",
    edit: "Правка: инструкция + код из редактора → /edit.",
    validate: "Проверка: код из редактора → /validate.",
  };
  let hint = hints[state.workMode] || "";
  if (state.discussionMode) {
    hint = hint ? `${hint} Диалог.` : "Диалог.";
  }
  const depthNote = state.depth === "deep" ? "Ответ: в JSON есть диагностика." : "Ответ: компактный JSON.";
  modeHint.textContent = [hint, depthNote].filter(Boolean).join(" ");

  const chunkIntro = state.depth === "deep" ? "Режим «Глубоко»: в JSON есть диагностика." : "Режим «Быстро».";
  chunksHint.textContent = `${chunkIntro} Источник: карточка или чип — текст фрагмента в окне.`;

  if (hotkeyHint) {
    hotkeyHint.textContent =
      state.workMode === "validate"
        ? "Enter — проверить код · Shift+Enter — новая строка"
        : state.workMode === "edit"
          ? "Enter — отправить правку · Shift+Enter — новая строка"
          : "Enter — главное действие · Shift+Enter — новая строка";
  }
  updatePrimaryButtonLabel();
}

function setWorkMode(mode) {
  if (mode === "new" || mode === "edit" || mode === "validate") {
    state.workMode = mode;
    state.discussionMode = false;
    const discuss = document.getElementById("modeDiscussBtn");
    if (discuss) {
      discuss.classList.remove("active");
      discuss.setAttribute("aria-pressed", "false");
    }
    updateModeUI();
  }
}

function setDepth(depth) {
  if (depth === "fast" || depth === "deep") {
    state.depth = depth;
    updateModeUI();
  }
}

function applyDemoScenario(key) {
  const sc = DEMO_SCENARIOS[key];
  if (!sc) return;
  setWorkMode(sc.mode);
  promptInput.value = sc.prompt;
  autoResize(promptInput);
  setEditorText(sc.code || "");
  showToast(`Подставлен сценарий: ${key}`, 2000);
}

async function runGenerateNew(prompt) {
  const pending = state.chatMemory.pendingClarification;
  const effectivePrompt = pending
    ? composeClarificationPrompt(prompt)
    : isFollowupPrompt(prompt)
      ? composeFollowupPrompt(prompt)
      : prompt;
  state.chatMemory.lastTask = clipText(prompt, CHAT_MEMORY_LIMITS.msgChars);
  rememberChatMessage("user", prompt);
  const response = await fetchJson(
    "/generate",
    { prompt: effectivePrompt, context: buildGenerateContext(), include_diagnostics: includeDiagnosticsFlag() },
    600000,
  );
  if (response.status === "needs_clarification") {
    const q = response.clarifying_question || "Уточните задачу подробнее.";
    addMessage("assistant", { text: `**Нужно уточнение:** ${q}` }, "clarification");
    showClarificationCallout(q);
    setValidationExplanation("");
    renderRetrievedChunks([]);
    renderValidation(response.validation || {});
    renderMeta({ ...response, iterations: response.iterations ?? 1 });
    state.chatMemory.pendingClarification = {
      originalPrompt: pending?.originalPrompt || prompt,
      question: q,
      askedAt: Date.now(),
    };
    state.chatMemory.lastAssistantResponse = clipText(`Нужно уточнение: ${q}`, CHAT_MEMORY_LIMITS.responseChars);
    rememberChatMessage("assistant", `Нужно уточнение: ${q}`);
  } else {
    hideClarificationCallout();
    addMessage("assistant", {
      text: response.message || "Готово.",
      code: response.code || "",
      docs: response.retrieved_chunks || [],
      explanation: response.explanation || "",
    });
    if (response.code) setEditorText(response.code);
    setValidationExplanation(response.explanation || "");
    renderRetrievedChunks(response.retrieved_chunks || []);
    renderValidation(response.validation || {});
    renderMeta(response);
    if (response.code) setEditorArtifactStatus("Код создан");
    state.chatMemory.pendingClarification = null;
    state.chatMemory.lastAssistantResponse = clipText(response.message || response.explanation || "Готово.", CHAT_MEMORY_LIMITS.responseChars);
    state.chatMemory.lastCode = clipText(response.code || editorText(), CHAT_MEMORY_LIMITS.codeChars);
    rememberChatMessage("assistant", response.message || response.explanation || "Код обновлён");
  }
  pushHistory({ prompt, mode: "new", at: Date.now() });
}

async function runGenerateEditFromPrompt(instruction) {
  const currentCode = editorText().trim();
  if (!currentCode) {
    addMessage("assistant", { text: "Добавьте код в редактор для режима правки." });
    return;
  }
  hideClarificationCallout();
  rememberChatMessage("user", `Правка: ${instruction}`);
  state.chatMemory.lastTask = clipText(instruction, CHAT_MEMORY_LIMITS.msgChars);
  addMessage("user", { text: `Правка: ${instruction}` });
  const response = await fetchJson(
    "/edit",
    { instruction, original_code: currentCode, code: currentCode, include_diagnostics: includeDiagnosticsFlag() },
    600000,
  );
  if (response.code) setEditorText(response.code);
  addMessage("assistant", {
    text: response.message || "Код обновлён.",
    code: response.code || "",
    docs: response.retrieved_chunks || [],
    explanation: response.explanation || "",
  });
  setValidationExplanation(response.explanation || "");
  renderValidation(response.validation || {});
  renderMeta(response);
  renderRetrievedChunks(response.retrieved_chunks || []);
  if (response.code) setEditorArtifactStatus("Код обновлён");
  state.chatMemory.pendingClarification = null;
  state.chatMemory.lastAssistantResponse = clipText(response.message || response.explanation || "Код обновлён.", CHAT_MEMORY_LIMITS.responseChars);
  state.chatMemory.lastCode = clipText(response.code || editorText(), CHAT_MEMORY_LIMITS.codeChars);
  rememberChatMessage("assistant", response.message || response.explanation || "Код обновлён");
  pushHistory({ prompt: instruction, mode: "edit", at: Date.now() });
}

async function primaryAction() {
  const prompt = promptInput.value.trim();
  if (state.workMode === "validate") {
    await runValidation(false);
    if (prompt) pushHistory({ prompt: `(проверка) ${prompt}`, mode: "validate", at: Date.now() });
    return;
  }
  if (state.workMode === "edit") {
    if (!prompt) {
      showToast("Введите инструкцию к правке");
      return;
    }
    setLoading(true);
    try {
      await runGenerateEditFromPrompt(prompt);
      promptInput.value = "";
      autoResize(promptInput);
    } catch (error) {
      addMessage("assistant", { text: `Ошибка: ${error.message}` });
    } finally {
      setLoading(false);
    }
    return;
  }
  if (!prompt) {
    showToast("Введите описание задачи");
    return;
  }
  addMessage("user", { text: prompt });
  promptInput.value = "";
  autoResize(promptInput);
  setLoading(true);
  try {
    await runGenerateNew(prompt);
  } catch (error) {
    addMessage("assistant", { text: `Ошибка: ${error.message}` });
  } finally {
    setLoading(false);
  }
}

async function runValidation(isSilent = false) {
  const code = editorText().trim();
  if (!code) {
    validationDot.className = "status-dot neutral";
    validationSummary.textContent = "Нет кода";
    validationSummary.classList.remove("validation-pill--ok", "validation-pill--error");
    validationSummary.classList.add("validation-pill--neutral");
    validationSuccessBanner.hidden = true;
    fillList(validationHardList, [], validationHardEmpty);
    fillList(validationWarnList, [], validationWarnEmpty);
    fillList(validationHintList, [], validationHintEmpty);
    if (!isSilent) showToast("Сначала вставьте или сгенерируйте код");
    return;
  }
  try {
    const data = await fetchJson("/validate", { code }, 15000);
    renderValidation(data.validation, isSilent);
    renderMeta({ status: data.status, validation: data.validation, iterations: 1, reflexion_applied: false, used_model: "— (только luac)" });
    renderRetrievedChunks([]);
    if (!isSilent) {
      const v = data.validation;
      const ok = v?.syntax_ok && !(v?.hard_errors?.length);
      setEditorArtifactStatus(ok ? "Код проверен" : "Проверка выполнена");
    }
  } catch (error) {
    if (!isSilent) addMessage("assistant", { text: `Ошибка валидации: ${error.message}` });
    validationDot.className = "status-dot error";
  }
}

function openEditModal() {
  const inst = promptInput.value.trim();
  if (inst) editInstruction.value = inst;
  editModal.showModal();
  editInstruction.focus();
}

function closeEditModal() {
  editModal.close();
  editInstruction.value = "";
}

async function applyEdit() {
  const instruction = editInstruction.value.trim();
  if (!instruction) return;
  closeEditModal();
  promptInput.value = instruction;
  autoResize(promptInput);
  setWorkMode("edit");
  setLoading(true);
  try {
    await runGenerateEditFromPrompt(instruction);
    promptInput.value = "";
    autoResize(promptInput);
  } catch (error) {
    addMessage("assistant", { text: `Ошибка правки: ${error.message}` });
  } finally {
    setLoading(false);
  }
}

async function copyCode() {
  const code = editorText();
  if (!code.trim()) {
    showToast("Редактор пуст — нечего копировать");
    return;
  }
  try {
    await navigator.clipboard.writeText(code);
    showToast("Код скопирован в буфер обмена");
  } catch {
    showToast("Не удалось скопировать (разрешения браузера?)");
  }
}

function clearEditor() {
  document.getElementById("editorWrap")?.classList.remove("editor-wrap--critical");
  hideClarificationCallout();
  setEditorArtifactStatus("", 0);
  setEditorText("");
  validationDot.className = "status-dot neutral";
  validationSummary.textContent = "Редактор очищен";
  validationSummary.classList.remove("validation-pill--ok", "validation-pill--error");
  validationSummary.classList.add("validation-pill--neutral");
  validationSuccessBanner.hidden = true;
  fillList(validationHardList, [], validationHardEmpty);
  fillList(validationWarnList, [], validationWarnEmpty);
  fillList(validationHintList, [], validationHintEmpty);
  setValidationExplanation("");
  if (diagnosticsPanel) diagnosticsPanel.hidden = true;
  const emptyHint = document.getElementById("diagnosticsEmptyHint");
  if (emptyHint) emptyHint.hidden = false;
  renderRetrievedChunks([]);
  updateResultGlance({ status: "—", used_model: "—", iterations: "—", reflexion_applied: null }, null, 0);
}

function clearAll() {
  if (!window.confirm("Очистить чат, редактор и панели? История и черновики в браузере не удаляются.")) return;
  chatLog.innerHTML = "";
  clearEditor();
  promptInput.value = "";
  autoResize(promptInput);
  hideClarificationCallout();
  state.chatMemory = {
    recent: [],
    summary: "",
    lastTask: "",
    lastCode: "",
    lastAssistantResponse: "",
    pendingClarification: null,
  };
  addMessage("assistant", {
    text: "Рабочая область сброшена. Введите задачу или откройте примеры.",
    format: "plain",
  });
  showToast("Сброшено: чат и редактор");
}

function saveDraft() {
  const code = editorText();
  if (!code.trim()) {
    showToast("Нечего сохранять — редактор пуст");
    return;
  }
  let drafts = [];
  try {
    const raw = store().getItem(LS_KEYS.drafts);
    drafts = raw ? JSON.parse(raw) : [];
    if (!Array.isArray(drafts)) drafts = [];
  } catch (_) {
    drafts = [];
  }
  const title = (promptInput.value.trim() || "Черновик").slice(0, 60);
  drafts.unshift({ title, code, at: Date.now() });
  saveDraftsList(drafts);
  showToast(`Черновик «${title.slice(0, 24)}${title.length > 24 ? "…" : ""}» сохранён`);
}

async function refreshServerStatus() {
  let healthOk = false;
  try {
    const h = await fetch("/health");
    healthOk = h.ok;
  } catch {
    healthOk = false;
  }

  healthBadge.classList.remove("status-pill--ok", "status-pill--warn", "status-pill--bad", "status-pill--pending");
  if (healthOk) {
    healthBadge.textContent = "API: онлайн";
    healthBadge.classList.add("status-pill--ok");
  } else {
    healthBadge.textContent = "API: недоступен";
    healthBadge.classList.add("status-pill--bad");
    readyBadge.classList.remove("status-pill--ok", "status-pill--warn", "status-pill--bad", "status-pill--pending");
    readyBadge.textContent = "Модели: —";
    readyBadge.classList.add("status-pill--bad");
    state.lastReady = null;
    updateServiceAlert();
    return;
  }

  readyBadge.classList.remove("status-pill--ok", "status-pill--warn", "status-pill--bad", "status-pill--pending");
  try {
    const r = await fetch("/ready");
    const data = await r.json().catch(() => ({}));
    state.lastReady = data;
    if (r.ok && data.ready) {
      const p = data.primary_available ? "осн." : "";
      const f = data.fallback_available ? "запасн." : "";
      const bits = [p, f].filter(Boolean).join("+") || "OK";
      readyBadge.textContent = `Модели: готовы (${bits})`;
      readyBadge.classList.add("status-pill--ok");
    } else {
      const detail = (data.detail || "").slice(0, 80);
      readyBadge.textContent = detail ? `Модели: не готовы — ${detail}` : "Модели: не готовы (см. docker / pull)";
      readyBadge.classList.add("status-pill--warn");
    }
  } catch {
    readyBadge.textContent = "Модели: не удалось проверить";
    readyBadge.classList.add("status-pill--bad");
    state.lastReady = null;
  }
  updateServiceAlert();
}

function uploadLuaFile() {
  luaFileInput.value = "";
  luaFileInput.click();
}

function handleLuaFileSelection(event) {
  const [file] = event.target.files || [];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = () => {
    const content = typeof reader.result === "string" ? reader.result : "";
    setEditorText(content);
    const label = file.name || "script.lua";
    setEditorArtifactStatus(`Импорт: ${label}`);
    showToast(`Файл «${label}» загружен в редактор`, 2400);
    runValidation(true);
  };
  reader.onerror = () => addMessage("assistant", { text: "Не удалось прочитать файл." });
  reader.readAsText(file, "utf-8");
}

function downloadLuaFile() {
  const code = editorText();
  const blob = new Blob([code], { type: "text/plain;charset=utf-8" });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = "script.lua";
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(link.href);
}

document.getElementById("sendBtn")?.addEventListener("click", primaryAction);
document.getElementById("fixCodeBtn").addEventListener("click", openEditModal);
document.getElementById("checkCodeBtn").addEventListener("click", () => runValidation(false));
document.getElementById("clearAllBtn").addEventListener("click", clearAll);
document.getElementById("insertExampleBtn").addEventListener("click", () => {
  promptInput.value = EXAMPLE_PROMPT;
  autoResize(promptInput);
  setWorkMode("new");
  showToast("Вставлен пример задачи");
});

document.querySelectorAll(".demo-card").forEach((btn) => {
  btn.addEventListener("click", () => applyDemoScenario(btn.dataset.demo));
});

document.getElementById("modeNewBtn").addEventListener("click", () => setWorkMode("new"));
document.getElementById("modeEditBtn").addEventListener("click", () => setWorkMode("edit"));
document.getElementById("modeValidateBtn").addEventListener("click", () => setWorkMode("validate"));

document.getElementById("depthFastBtn").addEventListener("click", () => setDepth("fast"));
document.getElementById("depthDeepBtn").addEventListener("click", () => setDepth("deep"));

document.getElementById("modeDiscussBtn")?.addEventListener("click", () => {
  state.discussionMode = !state.discussionMode;
  const discuss = document.getElementById("modeDiscussBtn");
  if (discuss) {
    discuss.classList.toggle("active", state.discussionMode);
    discuss.setAttribute("aria-pressed", state.discussionMode ? "true" : "false");
  }
  updateModeUI();
});

document.getElementById("profileGuestBtn").addEventListener("click", () => setProfile("guest"));
document.getElementById("profileLocalBtn").addEventListener("click", () => setProfile("local"));

document.getElementById("cancelEditBtn").addEventListener("click", closeEditModal);
document.getElementById("applyEditBtn").addEventListener("click", applyEdit);

document.querySelectorAll(".result-tab").forEach((btn) => {
  btn.addEventListener("click", () => setResultTab(btn.dataset.resultTab));
});
document.getElementById("platformOverflowBtn")?.addEventListener("click", openPlatformMenu);
document.getElementById("platformMenuCloseBtn")?.addEventListener("click", closePlatformMenu);
document.getElementById("platformMenuApplyBtn")?.addEventListener("click", savePlatformMenuSettings);
document.getElementById("splashReplayBtn")?.addEventListener("click", () => {
  try {
    sessionStorage.removeItem("localscript_splash_ok");
  } catch {
    /* ignore */
  }
  closePlatformMenu();
  location.reload();
});
document.getElementById("platformMenuDialog")?.addEventListener("close", () => {
  document.getElementById("platformOverflowBtn")?.setAttribute("aria-expanded", "false");
});
document.getElementById("sourceDocCloseBtn")?.addEventListener("click", () => document.getElementById("sourceDocDialog")?.close());
function openHelpTab() {
  setResultTab("help");
  scrollToResultPanel();
}
document.getElementById("helpFooterBtn")?.addEventListener("click", openHelpTab);
document.getElementById("clarificationContinueBtn")?.addEventListener("click", async () => {
  const t = clarificationReply?.value?.trim();
  if (!t) {
    showToast("Введите уточнение для продолжения");
    return;
  }
  hideClarificationCallout();
  setWorkMode("new");
  addMessage("user", { text: t });
  setLoading(true);
  try {
    await runGenerateNew(t);
  } catch (error) {
    addMessage("assistant", { text: `Ошибка: ${error.message}` });
  } finally {
    setLoading(false);
  }
});
document.getElementById("editorCopyBtn")?.addEventListener("click", copyCode);
document.getElementById("editorUploadBtn")?.addEventListener("click", uploadLuaFile);
document.getElementById("editorDownloadBtn")?.addEventListener("click", downloadLuaFile);
document.getElementById("editorClearBtn")?.addEventListener("click", clearEditor);
document.getElementById("editorDraftBtn")?.addEventListener("click", saveDraft);
luaFileInput.addEventListener("change", handleLuaFileSelection);

notesArea.addEventListener("input", () => {
  clearTimeout(notesArea._t);
  notesArea._t = setTimeout(() => {
    saveNotes();
    updateNotesHint();
  }, 400);
});
notesArea.addEventListener("blur", () => {
  saveNotes();
  updateNotesHint();
  if (notesArea.value.trim()) showToast("Заметки сохранены", 1600);
});

promptInput.addEventListener("input", () => autoResize(promptInput));
promptInput.addEventListener("keydown", (event) => {
  if (event.key !== "Enter") return;
  if (event.shiftKey) return;
  event.preventDefault();
  primaryAction();
});

applyUiSettingsToDom(getUiSettings());
loadPersistedUi();
initWorkspaceSplitAndLayout();
updateModeUI();
setResultTab("check");

chatLog.innerHTML = "";

setValidationExplanation("");
renderRetrievedChunks([]);
renderValidation({}, false);
validationSummary.textContent = "Ожидание действий";
validationSummary.classList.add("validation-pill--neutral");
updateResultGlance({ status: "—", used_model: "—", iterations: "—", reflexion_applied: null }, null, 0);

Promise.all([initEditor(), initOptionalLibraries()]).finally(() => {
  refreshServerStatus();
  setInterval(refreshServerStatus, 45000);
});
