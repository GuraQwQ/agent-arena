/** Mod 设置表单：只处理 schema 到控件的映射，不参与 Mod 生命周期。 */
function modSettingInputId(modId, key) {
  return `mod-setting-${encodeURIComponent(modId)}-${encodeURIComponent(key)}`;
}

function renderModSettings(status) {
  const byMod = new Map((status.settings || []).map(item => [item.id, item]));
  for (const card of document.querySelectorAll("[data-mod-card]")) {
    const modId = card.dataset.modCard;
    const host = card.querySelector("[data-mod-settings]");
    const item = byMod.get(modId);
    if (!item) { host.replaceChildren(); continue; }
    const fields = Object.entries(item.schema).map(([key, schema]) => {
      const inputId = modSettingInputId(modId, key);
      const value = item.values[key];
      const description = schema.description ? `<p class="mod-setting-help">${escapeHtml(schema.description)}${schema.restart_required ? " · 修改后重载 Mod" : ""}</p>` : schema.restart_required ? '<p class="mod-setting-help">修改后重载 Mod</p>' : "";
      if (schema.type === "boolean") return `<label class="mod-setting-toggle" for="${inputId}"><input id="${inputId}" type="checkbox" data-setting-key="${escapeHtml(key)}" ${value ? "checked" : ""}> <span>${escapeHtml(schema.label)}</span></label>${description}`;
      if (schema.type === "select") return `<label class="mod-setting-field"><span>${escapeHtml(schema.label)}</span><select id="${inputId}" data-setting-key="${escapeHtml(key)}">${schema.options.map(option => `<option value="${escapeHtml(String(option.value))}" ${String(option.value) === String(value) ? "selected" : ""}>${escapeHtml(option.label)}</option>`).join("")}</select>${description}</label>`;
      if (schema.type === "color") return `<label class="mod-setting-field"><span>${escapeHtml(schema.label)}</span><input id="${inputId}" type="color" data-setting-key="${escapeHtml(key)}" value="${escapeHtml(value)}">${description}</label>`;
      if (schema.type === "text") return `<label class="mod-setting-field"><span>${escapeHtml(schema.label)}</span><textarea id="${inputId}" data-setting-key="${escapeHtml(key)}" rows="3">${escapeHtml(value)}</textarea>${description}</label>`;
      const number = schema.type === "integer" || schema.type === "number";
      return `<label class="mod-setting-field"><span>${escapeHtml(schema.label)}</span><input id="${inputId}" type="${number ? "number" : "text"}" data-setting-key="${escapeHtml(key)}" value="${escapeHtml(value)}" ${schema.min !== undefined ? `min="${schema.min}"` : ""} ${schema.max !== undefined ? `max="${schema.max}"` : ""} ${schema.step !== undefined ? `step="${schema.step}"` : ""}>${description}</label>`;
    }).join("");
    host.innerHTML = `<div class="mod-settings-heading"><span>Mod 设置</span><button class="btn btn-secondary btn-sm" onclick="saveModSettings('${escapeHtml(modId)}')">保存设置</button></div><div class="mod-setting-fields">${fields}</div>`;
  }
}

function readModSettingValue(input, schema) {
  if (schema.type === "boolean") return input.checked;
  if (schema.type === "integer") return Number.parseInt(input.value, 10);
  if (schema.type === "number") return Number(input.value);
  if (schema.type === "select") return schema.options.find(option => String(option.value) === input.value)?.value ?? input.value;
  return input.value;
}

async function saveModSettings(modId) {
  const item = (modStatus?.settings || []).find(setting => setting.id === modId);
  if (!item) return;
  const values = {};
  for (const [key, schema] of Object.entries(item.schema)) {
    const input = document.querySelector(`#${CSS.escape(modSettingInputId(modId, key))}`);
    values[key] = readModSettingValue(input, schema);
  }
  const status = await adminRequest(`/api/admin/mods/${encodeURIComponent(modId)}/settings`, { values }, "PUT");
  renderModStatus(status);
  showNotice(`${modId} 设置已保存${status.enabled?.includes(modId) ? "，Mod 已重新加载" : ""}`);
}
