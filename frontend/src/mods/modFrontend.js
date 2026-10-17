export function createModFrontend({ onNotice, onPresenter, container, stylesheetRef }) {
  let view = null;
  let activeModule = null;

  const removeStylesheet = () => {
    stylesheetRef.current?.remove();
    stylesheetRef.current = null;
  };

  return {
    async mount(frontend, payload) {
      await this.destroy();
      if (!frontend?.module) return null;
      if (frontend.stylesheet) {
        const stylesheet = document.createElement("link");
        stylesheet.rel = "stylesheet";
        stylesheet.href = frontend.stylesheet;
        document.head.appendChild(stylesheet);
        stylesheetRef.current = stylesheet;
      }
      try {
        const module = await import(/* @vite-ignore */ frontend.module);
        activeModule = module;
        view = module.mount?.(container, { adminRequest: payload.adminRequest, showNotice: onNotice }) || null;
        onPresenter(typeof module.describeEvent === "function" ? module.describeEvent : null);
        view?.update?.(payload);
        return module;
      } catch (error) {
        await this.destroy();
        onNotice(`游戏界面加载失败：${error.message}`, true);
        return null;
      }
    },
    update(payload) {
      view?.update?.(payload);
    },
    inspector() {
      return activeModule?.getInspector?.() ?? null;
    },
    async destroy() {
      try {
        await view?.destroy?.();
      } catch (error) {
        onNotice(`游戏界面卸载失败：${error.message}`, true);
      }
      view = null;
      activeModule = null;
      onPresenter(null);
      removeStylesheet();
      container.replaceChildren();
    }
  };
}
