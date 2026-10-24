const $ = (id) => document.getElementById(id);
let conversationId = null;
let controller = null;
let statusData = null;
let memoryOffset = 0;
let oldestSeq = null;
let noticeTimer = null;
let profileVersion = null;

const expressionFeatures = {
  warmth: ["温暖程度", "克制 → 温暖关切"],
  humor: ["幽默倾向", "少用玩笑 → 适时诙谐"],
  curiosity: ["好奇倾向", "跟随话题 → 愿意探索"],
  directness: ["直接程度", "委婉 → 直接清楚"],
  detail: ["展开程度", "简短 → 详细"],
  initiative: ["话题主动程度", "跟随用户 → 适时提议"],
};
const importanceFeatures = {
  explicit_emphasis: ["用户明确重视", "你说这件事很重要"],
  personal_significance: ["个人意义", "与你的经历和关系有关"],
  lasting_relevance: ["长期相关性", "未来仍可能有用或值得回看"],
};

function fillWeights(container, section, definitions, values) {
  $(container).replaceChildren(
    ...Object.entries(definitions).map(([key, [title, hint]]) => {
      const row = document.createElement("label");
      row.className = "feature-control";
      const label = document.createElement("span");
      label.textContent = title;
      const value = document.createElement("output");
      value.textContent = Math.round(values[key] * 100);
      const slider = document.createElement("input");
      slider.type = "range";
      slider.min = "0";
      slider.max = "1";
      slider.step = "0.05";
      slider.value = values[key];
      slider.id = `feature-${section}-${key}`;
      slider.setAttribute("aria-label", title);
      slider.addEventListener("input", () => {
        value.textContent = Math.round(Number(slider.value) * 100);
      });
      const help = document.createElement("small");
      help.textContent = hint;
      row.append(label, value, slider, help);
      return row;
    }),
  );
}

function fillProfile(data, history) {
  profileVersion = data.version;
  $("profile-version").textContent = `版本 ${data.version}`;
  fillWeights(
    "profile-expression",
    "expression",
    expressionFeatures,
    data.document.expression,
  );
  fillWeights(
    "profile-importance",
    "importance",
    importanceFeatures,
    data.document.importance,
  );
  $("behavior-notes").value = data.document.behavior_notes;
  $("profile-examples").replaceChildren(
    ...[0, 1, 2].map((index) => {
      const row = document.createElement("div");
      row.className = "example-pair";
      for (const role of ["user", "assistant"]) {
        const label = document.createElement("label");
        label.textContent = `样例 ${index + 1} · ${role === "user" ? "用户的话" : "理想回应"}`;
        const input = document.createElement("textarea");
        input.rows = 2;
        input.id = `profile-example-${index}-${role}`;
        input.maxLength = role === "user" ? 200 : 400;
        input.value = data.document.examples[index]?.[role] || "";
        label.append(input);
        row.append(label);
      }
      return row;
    }),
  );
  $("profile-history").replaceChildren(
    ...history.map((item) => {
      const option = document.createElement("option");
      option.value = item.version;
      option.textContent = `版本 ${item.version} · ${when(item.created_at)}${item.version === data.version ? "（当前）" : ""}`;
      return option;
    }),
  );
}

function notice(text, sticky = false) {
  clearTimeout(noticeTimer);
  $("notice").textContent = text;
  $("notice").hidden = !text;
  if (text && !sticky)
    noticeTimer = setTimeout(() => {
      $("notice").hidden = true;
    }, 7000);
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { "Content-Type": "application/json", ...options.headers },
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(
      typeof data.detail === "string"
        ? data.detail
        : `请求未完成（${response.status}），请检查输入或服务状态。`,
    );
  }
  return response;
}
async function json(path, options) {
  return (await api(path, options)).json();
}
function button(label, action, className = "") {
  const element = document.createElement("button");
  element.type = "button";
  element.textContent = label;
  element.className = className;
  element.addEventListener("click", () =>
    Promise.resolve()
      .then(action)
      .catch((error) => notice(error.message)),
  );
  return element;
}
function paragraph(text, className = "") {
  const p = document.createElement("p");
  p.textContent = text;
  p.className = className;
  return p;
}
function when(value) {
  return value ? new Date(value).toLocaleDateString("zh-CN") : "日期未知";
}

async function showPage(page) {
  if (page === "chat") {
    $("side-panel").close();
    return;
  }
  for (const name of ["memories", "settings"])
    $(name + "-page").hidden = name !== page;
  document
    .querySelectorAll(".nav")
    .forEach((item) =>
      item.classList.toggle("active", item.dataset.page === page),
    );
  $("page-title").textContent = {
    chat: "聊一会儿",
    memories: "我们的回忆",
    settings: "偏好与连接",
  }[page];
  if (!$("side-panel").open) $("side-panel").showModal();
  if (page === "memories") await loadMemories();
  if (page === "settings") await refreshStatus(true);
}

async function connectCompanion() {
  const companion = await json("/api/companion", { method: "POST" });
  conversationId = companion.id;
  await loadMessages();
}

function companionState(state) {
  document.body.dataset.companionState = state;
  $("avatar-state").textContent = {
    idle: "我在，慢慢说。",
    thinking: "让我想一想……",
    answering: "正在回应你……",
    unavailable: "连接暂时没跟上。",
  }[state];
}

function addMessage(role, content, state = "completed", prepend = false) {
  const item = document.createElement("div");
  item.className = "message " + role;
  $("welcome").hidden = true;
  const speaker = document.createElement("span");
  speaker.className = "speaker";
  speaker.textContent = role === "user" ? "你" : "yf";
  const bubble = document.createElement("div");
  bubble.className = "bubble";
  bubble.textContent = content || "…";
  item.append(speaker, bubble);
  if (!["completed", "pending"].includes(state))
    item.append(
      paragraph(
        {
          failed: "回答未完成",
          cancelled: "已停止",
          interrupted: "服务中断",
          deleted: "已清理",
        }[state] || state,
        "message-state",
      ),
    );
  if (prepend) $("messages").prepend(item);
  else $("messages").append(item);
  return bubble;
}

async function loadMessages(before = null) {
  if (!conversationId) return;
  const previousHeight = $("messages").scrollHeight;
  const rows = await json(
    `/api/conversations/${conversationId}/messages` +
      (before ? `?before=${before}` : ""),
  );
  if (!before) $("messages").replaceChildren();
  $("load-older")?.remove();
  if (before)
    for (const row of [...rows].reverse())
      addMessage(row.role, row.content, row.status, true);
  else for (const row of rows) addMessage(row.role, row.content, row.status);
  if (rows.length) oldestSeq = rows[0].seq;
  if (rows.length === 80) {
    const older = button("查看更早的对话", () => loadMessages(oldestSeq));
    older.id = "load-older";
    $("messages").prepend(older);
  }
  $("welcome").hidden = $("messages").childElementCount > 0;
  $("messages").classList.toggle("has-messages", $("welcome").hidden);
  if (!before) $("messages").scrollTop = $("messages").scrollHeight;
  if (before)
    $("messages").scrollTop += $("messages").scrollHeight - previousHeight;
}

async function refreshStatus(fillForm = false) {
  statusData = await json("/api/status");
  $("model-status").textContent = statusData.model_configured
    ? (statusData.model_name || "模型") + " · 已配置"
    : "尚未配置聊天模型";
  $("model-status").classList.toggle("ready", statusData.model_configured);
  $("connection-detail").textContent = statusData.model_configured
    ? `当前模型：${statusData.model_name}（连接结果以实际请求为准）`
    : "尚未配置。可以先体验手动记忆、反馈与档案管理。";
  $("retrieval-detail").textContent = statusData.retrieval;
  const counts = {};
  for (const job of statusData.jobs)
    counts[job.status] = (counts[job.status] || 0) + 1;
  $("job-status").textContent =
    (statusData.model_configured ? "" : "连接模型后才会自动整理。") +
    ` 最近任务：完成 ${counts.done || 0}，等待 ${counts.pending || 0}，处理中 ${counts.running || 0}，失败 ${counts.failed || 0}。`;
  $("preferences").replaceChildren(
    ...statusData.memory_preferences.map((item) =>
      paragraph(
        `${item.tag}：${item.examples} 条事件反馈；${item.examples < 3 ? "暂不泛化为整类偏好" : "已用于后续同类记忆的重要性判断"}`,
        "muted",
      ),
    ),
  );
  if (fillForm) {
    $("memory-enabled").checked = statusData.settings.memory_enabled;
    $("auto-memory").checked = statusData.settings.auto_memory;
    $("personality").value = statusData.settings.personality;
    fillProfile(statusData.feature_profile, statusData.profile_history);
  }
}

async function sendMessage(event) {
  event.preventDefault();
  const content = $("chat-input").value.trim();
  if (!content || controller) return;
  if (!statusData?.model_configured) {
    notice("先配置模型再聊天；在“偏好与连接”中查看方法。", true);
    return;
  }
  controller = new AbortController();
  notice("");
  companionState("thinking");
  $("send").hidden = true;
  $("stop").hidden = false;
  $("chat-input").disabled = true;
  let responseText = "",
    bubble = null;
  try {
    if (!conversationId) await connectCompanion();
    addMessage("user", content);
    bubble = addMessage("assistant", "");
    $("messages").classList.add("has-messages");
    $("messages").scrollTop = $("messages").scrollHeight;
    const response = await api(`/api/conversations/${conversationId}/chat`, {
      method: "POST",
      body: JSON.stringify({ content, request_id: crypto.randomUUID() }),
      signal: controller.signal,
    });
    $("chat-input").value = "";
    const reader = response.body.getReader(),
      decoder = new TextDecoder();
    let buffer = "";
    while (true) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value, { stream: !done }).replace(/\r\n/g, "\n");
      let boundary;
      while ((boundary = buffer.indexOf("\n\n")) !== -1) {
        const part = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        const kind = part
          .split("\n")
          .find((line) => line.startsWith("event:"))
          ?.slice(6)
          .trim();
        const payload = part
          .split("\n")
          .filter((line) => line.startsWith("data:"))
          .map((line) => line.slice(5).trimStart())
          .join("\n");
        if (!payload) continue;
        const data = JSON.parse(payload);
        if (kind === "delta") {
          companionState("answering");
          responseText += data.text;
          bubble.textContent = responseText;
          $("messages").scrollTop = $("messages").scrollHeight;
        }
        if (kind === "error") {
          companionState("unavailable");
          bubble.textContent =
            responseText || "连接暂时没有成功，你的话已经保存。";
          bubble.parentElement.append(paragraph("回答未完成", "message-state"));
          notice(data.message, true);
        }
        if (kind === "done") companionState("idle");
      }
      if (done) break;
    }
  } catch (error) {
    companionState(error.name === "AbortError" ? "idle" : "unavailable");
    notice(
      error.name === "AbortError"
        ? "已停止回答；收到的内容会保留。"
        : error.message,
    );
    if (bubble && !responseText)
      bubble.textContent =
        error.name === "AbortError" ? "已停止" : "暂时没能生成回答。";
  } finally {
    controller = null;
    $("send").hidden = false;
    $("stop").hidden = true;
    $("chat-input").disabled = false;
    $("chat-input").focus();
    if (document.body.dataset.companionState === "thinking")
      companionState("idle");
  }
}

const levels = {
  full: "保留已知细节",
  fragment: "保留主要片段",
  outline: "保留轮廓",
  archived: "已淡出日常召回",
};
async function loadMemories(append = false) {
  if (!append) memoryOffset = 0;
  const query = $("memory-query").value.trim();
  const rows = await json(
    query
      ? "/api/memories?archive=true&q=" + encodeURIComponent(query)
      : "/api/memories?offset=" + memoryOffset,
  );
  if (!append) $("memory-results").replaceChildren();
  for (const memory of rows) {
    const card = document.createElement("article");
    card.className = "memory-card";
    const meta = document.createElement("div");
    meta.className = "memory-meta";
    const importance =
      memory.importance >= 0.7
        ? "重要"
        : memory.importance < 0.3
          ? "短暂"
          : "普通";
    meta.textContent = `${memory.pinned ? "✧ 珍藏 · " : ""}${importance} · ${levels[memory.detail_level]} · ${memory.occurred_on || when(memory.created_at)}`;
    const title = document.createElement("h2");
    title.textContent = memory.outline;
    card.append(meta, title);
    if (memory.detail) card.append(paragraph(memory.detail));
    if (memory.tags.length)
      card.append(paragraph(memory.tags.join(" · "), "muted"));
    const actions = document.createElement("div");
    actions.className = "memory-actions";
    actions.append(
      button("查看原始细节", () => showMemory(memory.id)),
      button("更重要", () => feedback(memory.id, "more")),
      button("不太重要", () => feedback(memory.id, "less")),
      button(memory.pinned ? "取消珍藏" : "珍藏", async () => {
        await json(`/api/memories/${memory.id}/pin`, {
          method: "PATCH",
          body: JSON.stringify({ pinned: !memory.pinned }),
        });
        await loadMemories();
      }),
      button("删除", () => forget(memory.id), "danger"),
    );
    card.append(actions);
    $("memory-results").append(card);
  }
  if (!rows.length && !append)
    $("memory-results").append(
      paragraph(
        query
          ? "还没有找到相关记忆，可以换个关键词或查原始对话。"
          : "这里还没有回忆。可以先记下一件事，或连接模型后在对话中慢慢积累。",
        "empty",
      ),
    );
  memoryOffset += rows.length;
  $("more-memories").hidden = !!query || rows.length < 60;
}

async function showMemory(id) {
  const memory = await json("/api/memories/" + id);
  $("detail-title").textContent = memory.outline;
  $("detail-content").replaceChildren(
    paragraph(memory.archived_detail || "没有更多已记录的细节。"),
    paragraph(
      `重要性 ${(memory.importance * 100).toFixed(0)} / 100 · 模型置信度 ${(memory.confidence * 100).toFixed(0)} / 100（未经校准）`,
      "muted",
    ),
    paragraph("判断依据：" + memory.reason, "muted"),
  );
  if (memory.missing_details.length)
    $("detail-content").append(
      paragraph("尚不清楚：" + memory.missing_details.join("、"), "muted"),
    );
  for (const source of memory.sources)
    $("detail-content").append(
      paragraph(
        `${when(source.created_at)} · 用户原话\n${source.content}`,
        "source",
      ),
    );
  if (!memory.sources.length)
    $("detail-content").append(paragraph("这条记忆由你直接记录。", "muted"));
  $("memory-detail").showModal();
}
async function feedback(id, direction) {
  await json(`/api/memories/${id}/feedback`, {
    method: "POST",
    body: JSON.stringify({ direction, reason: "用户在记忆页明确调整" }),
  });
  await loadMemories();
  notice("已调整这件事的重要性；多条同类反馈会逐渐影响后续判断。");
}
async function forget(id) {
  const preview = await json(`/api/memories/${id}/deletion-preview`);
  if (
    !confirm(
      `删除范围：${preview.memory_ids.length} 条相关记忆、${preview.message_ids.length} 条关联消息。\n本版会整体清理相关对话轮次，可能包含其他细节；已有导出和备份不会自动删除。\n确认清理？`,
    )
  )
    return;
  await json(`/api/memories/${id}/forget`, {
    method: "POST",
    body: JSON.stringify({ expected_memory_ids: preview.memory_ids }),
  });
  await loadMemories();
  notice("已清理在线记录。旧导出和备份需要单独管理。");
}

document
  .querySelectorAll(".nav")
  .forEach((item) =>
    item.addEventListener("click", () =>
      showPage(item.dataset.page).catch((error) => notice(error.message)),
    ),
  );
document
  .querySelectorAll(".close-dialog")
  .forEach((item) =>
    item.addEventListener("click", () => item.closest("dialog").close()),
  );
document.querySelectorAll("[data-suggestion]").forEach((item) =>
  item.addEventListener("click", () => {
    $("chat-input").value = item.dataset.suggestion;
    $("chat-input").focus();
  }),
);
$("side-panel").addEventListener("close", () => {
  document
    .querySelectorAll(".nav")
    .forEach((item) => item.classList.remove("active"));
});
$("chat-form").addEventListener("submit", sendMessage);
$("chat-input").addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    $("chat-form").requestSubmit();
  }
});
$("stop").addEventListener("click", () => controller?.abort());
$("search-memory").addEventListener("click", () =>
  loadMemories().catch((error) => notice(error.message)),
);
$("memory-query").addEventListener("keydown", (event) => {
  if (event.key === "Enter")
    loadMemories().catch((error) => notice(error.message));
});
$("more-memories").addEventListener("click", () =>
  loadMemories(true).catch((error) => notice(error.message)),
);
$("add-memory").addEventListener("click", () => $("memory-editor").showModal());
$("memory-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    await json("/api/memories", {
      method: "POST",
      body: JSON.stringify({
        outline: $("outline").value,
        detail: $("detail").value,
        importance: Number($("importance").value),
        tags: $("tags")
          .value.split(/[,，]/)
          .map((tag) => tag.trim())
          .filter(Boolean)
          .slice(0, 8),
        occurred_on: $("occurred-on").value || null,
        pinned: $("pinned").checked,
      }),
    });
    $("memory-editor").close();
    $("memory-form").reset();
    $("memory-query").value = "";
    await loadMemories();
  } catch (error) {
    notice(error.message);
  }
});
$("search-archive").addEventListener("click", async () => {
  const query = $("memory-query").value.trim();
  if (!query) {
    notice("先输入一个想找的关键词。");
    return;
  }
  try {
    const rows = await json("/api/archive?q=" + encodeURIComponent(query));
    $("memory-results").replaceChildren(
      ...rows.map((row) => {
        const card = document.createElement("article");
        card.className = "memory-card";
        card.append(
          paragraph(when(row.created_at), "muted"),
          paragraph(row.content),
          button("查看当时的记录", async () => {
            const history = await json(
              `/api/conversations/${row.conversation_id}/messages?before=${row.seq + 1}&limit=12`,
            );
            $("detail-title").textContent = "当时的记录";
            $("detail-content").replaceChildren(
              ...history.map((message) =>
                paragraph(
                  `${message.role === "user" ? "你" : "yf"} · ${when(message.created_at)}\n${message.content}`,
                  "source",
                ),
              ),
            );
            $("memory-detail").showModal();
          }),
        );
        return card;
      }),
    );
    if (!rows.length)
      $("memory-results").append(paragraph("没有找到原始记录。", "empty"));
    $("more-memories").hidden = true;
  } catch (error) {
    notice(error.message);
  }
});
$("settings-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    await json("/api/settings", {
      method: "PATCH",
      body: JSON.stringify({
        memory_enabled: $("memory-enabled").checked,
        auto_memory: $("auto-memory").checked,
        personality: $("personality").value,
      }),
    });
    notice("偏好已保存。");
    await refreshStatus();
  } catch (error) {
    notice(error.message);
  }
});
$("profile-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const weights = (section, definitions) =>
    Object.fromEntries(
      Object.keys(definitions).map((key) => [
        key,
        Number($(`feature-${section}-${key}`).value),
      ]),
    );
  const examples = [0, 1, 2].map((index) => ({
    user: $(`profile-example-${index}-user`).value.trim(),
    assistant: $(`profile-example-${index}-assistant`).value.trim(),
  }));
  if (
    examples.some(
      (example) => Boolean(example.user) !== Boolean(example.assistant),
    )
  ) {
    notice("风格样例需要同时填写用户的话和理想回应，或将这组全部留空。");
    return;
  }
  try {
    await json("/api/profile", {
      method: "PUT",
      body: JSON.stringify({
        expected_version: profileVersion,
        document: {
          expression: weights("expression", expressionFeatures),
          importance: weights("importance", importanceFeatures),
          behavior_notes: $("behavior-notes").value,
          examples: examples.filter(
            (example) => example.user && example.assistant,
          ),
        },
      }),
    });
    await refreshStatus(true);
    notice("已保存为新版本，下一次回答将使用这份特征档案。");
  } catch (error) {
    notice(error.message);
  }
});
$("restore-profile").addEventListener("click", async () => {
  const version = Number($("profile-history").value);
  if (version === profileVersion) {
    notice("已经在使用这个版本。");
    return;
  }
  if (
    !confirm(
      "将使用选中的特征档案，并保留为一个新版本。页面上未保存的特征调整会被替换，继续吗？",
    )
  )
    return;
  try {
    await json("/api/profile/restore", {
      method: "POST",
      body: JSON.stringify({ version, expected_version: profileVersion }),
    });
    await refreshStatus(true);
    notice("已恢复所选档案；模型和记忆没有重置。");
  } catch (error) {
    notice(error.message);
  }
});
$("backup").addEventListener("click", async () => {
  try {
    const response = await api("/api/backup", { method: "POST" });
    const url = URL.createObjectURL(await response.blob()),
      link = document.createElement("a");
    link.href = url;
    link.download =
      "yf-backup-" + new Date().toISOString().slice(0, 10) + ".sqlite3";
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 2000);
    notice("备份已生成并开始下载。");
  } catch (error) {
    notice(error.message);
  }
});
function clock() {
  $("device-time").textContent = new Date().toLocaleString("zh-CN", {
    month: "long",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}
clock();
setInterval(clock, 30000);
Promise.all([refreshStatus(true), connectCompanion()]).catch((error) =>
  notice("本机服务暂不可用：" + error.message, true),
);
setInterval(() => {
  if (!document.hidden) refreshStatus().catch(() => {});
}, 15000);
