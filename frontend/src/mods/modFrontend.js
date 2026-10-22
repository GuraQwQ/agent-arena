export function createModFrontend({ onNotice, onPresenter, container, stylesheetRef }) {
  let view = null;
  let activeModule = null;
  let generation = 0;
  let latestPayload = null;
  let root = null;

  const release = async () => {
    const previous = view;
    view = null;
    activeModule = null;
    root?.remove();
    root = null;
    stylesheetRef.current?.remove();
    stylesheetRef.current = null;
    onPresenter(null);
    try { await previous?.destroy?.(); }
    catch (error) { onNotice(`游戏界面卸载失败：${error.message}`, true); }
  };

  return {
    async mount(frontend, payload) {
      const current = ++generation;
      latestPayload = payload;
      await release();
      if (current !== generation || !frontend?.module) return null;
      try {
        const module = await import(/* @vite-ignore */ frontend.module);
        if (current !== generation) return null;
        if (frontend.stylesheet) {
          const stylesheet = document.createElement("link");
          stylesheet.rel = "stylesheet";
          stylesheet.href = frontend.stylesheet;
          document.head.appendChild(stylesheet);
          stylesheetRef.current = stylesheet;
        }
        root = document.createElement("div");
        root.className = "mod-root";
        container.replaceChildren(root);
        activeModule = module;
        view = module.mount?.(root, { adminRequest: payload.adminRequest, showNotice: onNotice }) || null;
        onPresenter(typeof module.describeEvent === "function" ? module.describeEvent : null);
        view?.update?.(latestPayload);
        return module;
      } catch (error) {
        if (current === generation) {
          await release();
          onNotice(`游戏界面加载失败：${error.message}`, true);
        }
        return null;
      }
    },
    update(payload) {
      latestPayload = payload;
      view?.update?.(payload);
    },
    inspector() { return activeModule?.getInspector?.() ?? null; },
    async destroy() { generation += 1; await release(); }
  };
}
