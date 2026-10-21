import vi from "./vi.js";

const catalogs = { vi };

export class I18n {
  constructor(locale = "vi") {
    this.locale = locale;
  }

  t(key, params = {}) {
    const catalog = catalogs[this.locale] || catalogs.vi;
    let value = catalog.messages[key] ?? catalogs.vi.messages[key] ?? key;
    return value.replace(/\{([^}]+)\}/g, (_, name) => String(params[name] ?? `{${name}}`));
  }

  apply(root = document) {
    root.querySelectorAll("[data-i18n]").forEach((element) => {
      element.textContent = this.t(element.dataset.i18n);
    });
    root.querySelectorAll("[data-i18n-placeholder]").forEach((element) => {
      element.placeholder = this.t(element.dataset.i18nPlaceholder);
    });
    root.querySelectorAll("[data-i18n-title]").forEach((element) => {
      element.title = this.t(element.dataset.i18nTitle);
    });
    document.documentElement.lang = this.locale;
  }
}

export const i18n = new I18n(localStorage.getItem("locale") || "vi");
window.i18n = i18n;
