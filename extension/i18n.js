const extensionMessages = {
  title: "Flow2API - Trình xử lý mã xác minh",
  routeKey: "Khóa định tuyến",
  clientLabel: "Tên phiên trình duyệt",
  serverUrl: "Địa chỉ WebSocket",
  apiKey: "Khóa API Flow2API",
  description: "Đặt khóa định tuyến riêng cho phiên trình duyệt hiện tại để Flow2API gửi yêu cầu mã xác minh của tài khoản đến đúng phiên.",
  routeKeyPlaceholder: "Ví dụ: 9223",
  clientLabelPlaceholder: "Ví dụ: browser-9223",
  apiKeyPlaceholder: "Khóa API trong bảng quản trị",
  save: "Lưu",
  hint: "Nhập cùng khóa định tuyến trong thông tin mã truy cập của bảng quản trị, ví dụ 9223 tương ứng với 9223. Máy chủ sẽ dùng khóa API để xác thực kết nối WebSocket.",
  wsError: "Địa chỉ WebSocket phải bắt đầu bằng ws:// hoặc wss://.",
  apiKeyRequired: "Vui lòng nhập khóa API Flow2API.",
  saveError: "Lưu thất bại: {message}",
  saved: "Đã lưu, kết nối nền sẽ tự động kết nối lại."
};

window.extensionI18n = {
  t(key, params = {}) {
    return (extensionMessages[key.replace(/^extension\./, "")] || key).replace(/\{([^}]+)\}/g, (_, name) => String(params[name] ?? `{${name}}`));
  },
  apply() {
    document.documentElement.lang = "vi";
    document.querySelectorAll("[data-i18n]").forEach((el) => { el.textContent = this.t(el.dataset.i18n); });
    document.querySelectorAll("[data-i18n-placeholder]").forEach((el) => { el.placeholder = this.t(el.dataset.i18nPlaceholder); });
  }
};
window.extensionI18n.apply();
