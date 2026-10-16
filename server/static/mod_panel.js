/** 本地 Mod 与存档组合使用同一份服务端诊断结果。 */
let modStatus = null;
let modBusy = false;
let archiveModReport = null;
let extensionViews = [];
let extensionStyles = [];
let extensionsLoading = false;
let extensionsInitialized = false;
let extensionSerial = 0;

function renderModIssues(issues, target = "mod-issues") {
  document.getElementById(target).innerHTML = (issues || []).map(issue => `<div class="mod-issue ${issue.severity === "warning" ? "warning" : ""}"><strong>${escapeHtml(issue.message)}</strong>${issue.mods?.length ? `<div>涉及：${issue.mods.map(escapeHtml).join("、")}</div>` : ""}${issue.resource ? `<div>覆盖项：${escapeHtml(issue.resource)}</div>` : ""}${issue.location ? `<div>${escapeHtml(issue.location)}</div>` : ""}${issue.expected ? `<details><summary>源码校验值</summary><div>${escapeHtml(issue.expected)}</div><div>${escapeHtml(issue.actual)}</div></details>` : ""}</div>`).join("");
}

function renderModStatus(status) {
  modStatus = status;
  renderModIssues(status.issues);
  document.getElementById("mod-list").innerHTML = status.mods.map(mod => {
    const enabled = status.enabled.includes(mod.id);
    const current = status.profile.find(item => item.id === mod.id);
    const changed = enabled && current && (current.rules_hash !== mod.rules_hash || current.version !== mod.version || status.loaded?.[mod.id]?.ui_hash !== mod.ui_hash);
    return `<article class="mod-card"><header><div><h4>${escapeHtml(mod.name)}</h4><span class="field-hint">${escapeHtml(mod.version || "配置错误")} · ${mod.type === "game" ? "游戏" : "扩展"}${changed ? " · 文件已改变" : ""}</span></div><label class="check-option"><input type="checkbox" data-mod-toggle="${escapeHtml(mod.id)}" ${enabled ? "checked" : ""} ${modBusy ? "disabled" : ""} onchange="toggleMod(this.dataset.modToggle, this.checked)">${enabled ? "已启用" : "启用"}</label></header><p>${escapeHtml(mod.description || mod.error || "")}</p><details><summary>依赖与覆盖项</summary><p>编号：${escapeHtml(mod.id)}</p><p>依赖：${Object.entries(mod.dependencies || {}).map(([id, version]) => escapeHtml(`${id} ${version || "任意版本"}`)).join("、") || "未声明"}</p><p>冲突：${(mod.conflicts || []).map(escapeHtml).join("、") || "未声明"}</p><p>覆盖：${(mod.overrides || []).map(escapeHtml).join("、") || "未声明"}</p></details></article>`;
  }).join("") || '<p class="field-hint">将含 mod.json 的模块放入 games 后刷新列表。</p>';
  document.getElementById("mod-load-order").innerHTML = status.order.map(id => `<li>${escapeHtml(id)}</li>`).join("") || "尚未启用 Mod";
}

async function refreshMods() {
  renderModStatus(await adminRequest("/api/admin/mods", undefined, "GET"));
}

async function setEnabledMods(enabled) {
  if (modBusy) return;
  modBusy = true;
  if (modStatus) renderModStatus(modStatus);
  try {
    const status = await adminRequest("/api/admin/mods", { enabled });
    modBusy = false;
    renderModStatus(status);
    showNotice(`Mod 已重载 · ${status.order.join(" → ") || "核心运行环境"}`);
  } catch (error) {
    modBusy = false;
    if (modStatus) renderModStatus(modStatus);
    renderModIssues(error.issues || [{ message: error.message }]);
  }
}

async function toggleMod(id, enabled) {
  if (!modStatus) await refreshMods();
  await setEnabledMods(enabled ? [...modStatus.enabled, id] : modStatus.enabled.filter(value => value !== id));
}

async function reloadMods() {
  if (!modStatus) await refreshMods();
  await setEnabledMods(modStatus.enabled);
}

async function openModSettings() {
  switchControlSection("mods");
  document.getElementById("controls-panel").showPopover();
  await refreshMods();
}

async function inspectArchiveMods(roomId) {
  document.getElementById("archive-restore").disabled = true;
  const report = await adminRequest(`/api/admin/archives/${encodeURIComponent(roomId)}/mods`, undefined, "GET");
  if (document.getElementById("replay-archive").value !== roomId) return;
  archiveModReport = { roomId, ...report };
  const container = document.getElementById("archive-mods");
  container.innerHTML = report.required.map(mod => `<p>${escapeHtml(mod.id)} · ${escapeHtml(mod.version)}${mod.rules_hash ? ` · ${escapeHtml(mod.rules_hash.slice(0, 10))}` : " · 历史源码未记录"}</p>`).join("") || "此存档使用核心规则";
  const issues = document.createElement("div");
  issues.id = "archive-mod-issues";
  container.appendChild(issues);
  renderModIssues(report.issues, issues.id);
  document.getElementById("archive-mod-status").textContent = report.valid ? `${report.required.length} 个 Mod · 可恢复` : "所需 Mod 存在问题";
  document.getElementById("archive-restore").disabled = !report.valid;
}

async function restoreSelectedArchive() {
  const roomId = document.getElementById("replay-archive").value;
  if (!roomId || archiveModReport?.roomId !== roomId || !archiveModReport.valid) return;
  if (!confirm("备份当前对局，并从存档恢复为新对局？所需 Mod 将一起加载，运行中的游戏会暂停，玩家需重新接入。")) return;
  await adminRequest(`/api/admin/archives/${encodeURIComponent(roomId)}/restore`, {});
  await receiveHostSnapshot(await adminRequest("/api/admin/snapshot", undefined, "GET"));
  await switchTimelineView(latestSnapshot.game ? "game" : "live");
  showNotice("存档与所需 Mod 已恢复，可以检查后继续");
}

async function reloadModViews() {
  const serial = ++extensionSerial;
  extensionsLoading = true;
  try {
    const data = await adminRequest("/api/admin/mods/frontend", undefined, "GET");
    if (serial !== extensionSerial) return;
    for (const view of extensionViews) { try { view.destroy?.(); } catch (error) { console.warn("扩展界面清理失败", error); } }
    extensionViews = [];
    extensionStyles.forEach(style => style.remove());
    extensionStyles = [];
    document.getElementById("mod-widgets").replaceChildren();
    gameViewKey = null;
    if (latestSnapshot) renderHostStage(latestSnapshot);
    for (const frontend of data.frontends) {
      try {
        const module = await import(frontend.module);
        if (serial !== extensionSerial) return;
        if (frontend.stylesheet) {
          const link = document.createElement("link");
          link.rel = "stylesheet";
          link.href = frontend.stylesheet;
          document.head.appendChild(link);
          extensionStyles.push(link);
        }
        const container = document.createElement("section");
        container.dataset.modWidget = frontend.id;
        document.getElementById("mod-widgets").appendChild(container);
        const view = module.mount(container, { adminRequest, showNotice, root: document.getElementById("arena-dashboard") });
        extensionViews.push(view);
        view.update?.(latestSnapshot);
      } catch (error) { showNotice(`${frontend.id} 界面加载失败：${error.message}`, true); }
    }
    extensionsInitialized = true;
  } finally {
    if (serial === extensionSerial) extensionsLoading = false;
  }
}

function updateModViews(snapshot) {
  if (!extensionsInitialized && !extensionsLoading) reloadModViews().catch(error => showNotice(error.message, true));
  for (const view of extensionViews) {
    try { view.update?.(snapshot); }
    catch (error) { console.warn("扩展界面更新失败", error); }
  }
}

