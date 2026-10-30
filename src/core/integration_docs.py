"""Human-authored, translated integration notes. No runtime configuration or secrets.

Route schemas remain the source of truth for typed request fields. These notes
explain operational behavior and document untyped dictionary request bodies.
"""


def _text(en, vi, zh):
    return {"en": en, "vi": vi, "zh-CN": zh}


ENDPOINT_NOTES = {}

_ADMIN = _text(
    " Requires a live admin session: Authorization: Bearer <ADMIN_SESSION> or the admin_session cookie from login. The generation API key and plugin connection token do not authorize this route. Sessions live in process memory and are lost on restart. Validation failures may return HTTP 422; read success/message as well as the HTTP status.",
    " Cần phiên quản trị còn hiệu lực: Authorization: Bearer <ADMIN_SESSION> hoặc cookie admin_session từ đăng nhập. Khóa API tạo nội dung và token kết nối plugin không cấp quyền cho đường dẫn này. Phiên được giữ trong bộ nhớ tiến trình và mất khi khởi động lại. Dữ liệu không hợp lệ có thể trả HTTP 422; cần đọc cả success/message và mã HTTP.",
    " 需要有效管理会话：Authorization: Bearer <ADMIN_SESSION>，或登录返回的 admin_session Cookie。生成 API Key 和插件连接令牌不能用于此接口。会话保存在进程内存中，重启后失效。请求校验可能返回 HTTP 422；除 HTTP 状态外还应检查 success/message。",
)
_API = _text(
    " Requires the configured generation API key via Authorization: Bearer <API_KEY>, x-goog-api-key, or ?key=<API_KEY>, in that priority order. Missing/invalid keys return HTTP 401. Admin sessions and plugin connection tokens are separate credentials.",
    " Cần khóa API tạo nội dung qua Authorization: Bearer <API_KEY>, x-goog-api-key hoặc ?key=<API_KEY>, theo thứ tự ưu tiên đó. Thiếu/sai khóa trả HTTP 401. Phiên quản trị và token kết nối plugin là thông tin xác thực riêng.",
    " 需要配置的生成 API Key，依次支持 Authorization: Bearer <API_KEY>、x-goog-api-key、?key=<API_KEY>。缺失或无效返回 HTTP 401。管理会话和插件连接令牌属于不同凭据。",
)
_PLUGIN = _text(
    " Requires the plugin connection_token in Authorization (Bearer <PLUGIN_CONNECTION_TOKEN> or the raw token). Empty, missing or wrong tokens return HTTP 401. This is distinct from the generation API key, admin session, and CAPTCHA WebSocket authentication.",
    " Cần connection_token của plugin trong Authorization (Bearer <PLUGIN_CONNECTION_TOKEN> hoặc token thuần). Token trống, thiếu hoặc sai trả HTTP 401. Token này khác khóa API tạo nội dung, phiên quản trị và xác thực WebSocket CAPTCHA.",
    " Authorization 必须提供插件 connection_token（Bearer <PLUGIN_CONNECTION_TOKEN> 或原始令牌）。未配置、缺失或错误均返回 HTTP 401。它与生成 API Key、管理会话及 CAPTCHA WebSocket 认证不同。",
)


def _add(keys, summaries, details, *, auth="admin", body=None, query=None, fields=None):
    note = {"summary": _text(*summaries), "details": _text(*details)}
    suffix = {"admin": _ADMIN, "api": _API, "plugin": _PLUGIN}.get(auth)
    if suffix:
        note["details"] = {lang: value + suffix[lang] for lang, value in note["details"].items()}
    if body is not None:
        note["body_example"] = body
    if query is not None:
        note["query_example"] = query
    if fields is not None:
        note["body_fields"] = fields
    for key in keys if isinstance(keys, (list, tuple)) else [keys]:
        ENDPOINT_NOTES[key] = note


_add(["GET /openapi.json", "HEAD /openapi.json"],
     ("Machine-readable API contract", "Contract API cho công cụ", "机器可读 API 契约"),
     ("Public FastAPI OpenAPI JSON including request schemas and response declarations. HEAD returns headers only. Routes marked include_in_schema=False, WebSockets and mounted assets are documented separately by this reference.",
      "JSON OpenAPI công khai của FastAPI, gồm schema đầu vào và khai báo phản hồi. HEAD chỉ trả header. Route include_in_schema=False, WebSocket và tài nguyên mount được liệt kê riêng trong tài liệu này.",
      "公开 FastAPI OpenAPI JSON，包含请求 Schema 和响应声明。HEAD 仅返回响应头。include_in_schema=False 的路由、WebSocket 和挂载资源由本参考资料单独列出。"), auth=None)

_add(["GET /docs", "HEAD /docs", "GET /redoc", "HEAD /redoc"],
     ("Interactive API documentation", "Giao diện tài liệu API", "交互式 API 文档"),
     ("Public Swagger UI (/docs) or ReDoc (/redoc) HTML generated from /openapi.json. They do not create an admin session or grant permission to protected API operations. HEAD returns headers only.",
      "HTML Swagger UI (/docs) hoặc ReDoc (/redoc) công khai được tạo từ /openapi.json. Mở tài liệu không tạo phiên admin hay cấp quyền gọi API được bảo vệ. HEAD chỉ trả header.",
      "从 /openapi.json 生成的公开 Swagger UI (/docs) 或 ReDoc (/redoc) HTML。访问文档不会创建管理会话或授权受保护的操作。HEAD 仅返回响应头。"), auth=None)

_add(["GET /docs/oauth2-redirect", "HEAD /docs/oauth2-redirect"],
     ("Swagger OAuth redirect helper", "Trang hỗ trợ chuyển hướng OAuth của Swagger", "Swagger OAuth 重定向辅助页"),
     ("Framework-provided Swagger helper HTML. It is not a Flow2API login/token endpoint and does not replace the documented generation/admin/plugin authentication. HEAD returns headers only.",
      "HTML hỗ trợ Swagger do framework cung cấp. Không phải endpoint đăng nhập/lấy token của Flow2API và không thay thế xác thực API tạo nội dung, admin hay plugin. HEAD chỉ trả header.",
      "框架提供的 Swagger 辅助 HTML，不是 Flow2API 登录或令牌接口，不能替代生成、管理或插件认证。HEAD 仅返回响应头。"), auth=None)

_add("MOUNT /tmp", ("Cached generated media", "Nội dung đã tạo trong bộ nhớ đệm", "生成媒体缓存"),
     ("Public static files under /tmp/<filename>. Use the exact URL returned by generation; there is no directory-listing API. Cache configuration controls availability/retention. This mount is not an upload, generation, polling or arbitrary-video-upscale endpoint.",
      "Tệp tĩnh công khai tại /tmp/<filename>. Dùng đúng URL kết quả tạo; không có API liệt kê thư mục. Cấu hình cache quyết định khả năng truy cập và thời gian lưu. Mount này không phải API tải lên, tạo nội dung, polling hay upscale video bất kỳ.",
      "公开静态文件 /tmp/<filename>。使用生成结果返回的精确 URL，不提供目录列表 API。缓存配置决定可用性和保留时间。此挂载不是上传、生成、轮询或任意视频放大接口。"), auth=None)

_add("MOUNT /static/locales", ("Interface translation catalogs", "Catalog bản dịch giao diện", "界面翻译词典"),
     ("Public JSON files under /static/locales/<catalog>.json with zh-CN, en and vi sections. These are documentation/UI strings, not live account data or credential configuration.",
      "Tệp JSON công khai /static/locales/<catalog>.json với các phần zh-CN, en và vi. Đây là chuỗi tài liệu/giao diện, không phải dữ liệu tài khoản hay cấu hình thông tin xác thực đang dùng.",
      "公开 JSON /static/locales/<catalog>.json，含 zh-CN、en、vi 部分。它们是文档/界面字符串，不是实时账号数据或凭据配置。"), auth=None)


_add(["POST /api/admin/login", "POST /api/login"],
     ("Create an admin session", "Tạo phiên quản trị", "创建管理会话"),
     ("Both paths perform the same login. Submit the configured administrator username/password. Returns success, username and a newly generated token, and sets an HttpOnly, SameSite=Lax admin_session cookie at /. Use that token/cookie for management APIs. Incorrect credentials return HTTP 401. The returned token is not a generation API key.",
      "Hai đường dẫn đăng nhập giống nhau. Gửi tên đăng nhập/mật khẩu quản trị đã cấu hình. Trả success, username, token mới và đặt cookie admin_session HttpOnly, SameSite=Lax tại /. Dùng token/cookie cho API quản trị. Sai thông tin trả HTTP 401. Token trả về không phải khóa API tạo nội dung.",
      "两个路径执行相同登录。提交已配置的管理用户名和密码。返回 success、username 和新 token，并设置路径为 / 的 HttpOnly、SameSite=Lax admin_session Cookie。管理接口使用此 token/Cookie。凭据错误返回 HTTP 401；返回的 token 不是生成 API Key。"),
     auth=None, body={"username": "<ADMIN_USERNAME>", "password": "<ADMIN_PASSWORD>"})
_add(["POST /api/admin/logout", "POST /api/logout"],
     ("End the current admin session", "Kết thúc phiên quản trị", "结束当前管理会话"),
     ("Invalidates the authenticated session token and deletes its browser cookie. Other existing sessions remain valid. Returns success/message; a second call with the invalidated credential needs a fresh login.",
      "Hủy token phiên đang xác thực và xóa cookie trình duyệt. Các phiên khác vẫn có hiệu lực. Trả success/message; gọi lại bằng phiên đã hủy cần đăng nhập mới.",
      "注销本次认证使用的会话令牌并删除浏览器 Cookie，其他会话仍有效。返回 success/message；再次使用已注销令牌需要重新登录。"))
_add(["POST /api/admin/change-password", "POST /api/admin/password"],
     ("Change administrator credentials", "Đổi thông tin quản trị", "修改管理员凭据"),
     ("Both routes verify old_password against the current admin, then save new_password and optionally a nonempty username. A wrong old password returns HTTP 400. Configuration is reloaded immediately and ALL admin sessions are invalidated, including the caller; log in again after success.",
      "Hai đường dẫn xác minh old_password với quản trị hiện tại rồi lưu new_password và username không rỗng nếu có. Sai mật khẩu cũ trả HTTP 400. Cấu hình được nạp ngay và TẤT CẢ phiên quản trị bị hủy, gồm phiên gọi; đăng nhập lại sau khi thành công.",
      "两个路径均验证当前管理员的 old_password，然后保存 new_password 和可选非空 username。旧密码错误返回 HTTP 400。配置立即重载，并使包括当前调用方在内的全部管理会话失效；成功后需重新登录。"),
     body={"username": "<OPTIONAL_NEW_ADMIN_USERNAME>", "old_password": "<CURRENT_ADMIN_PASSWORD>", "new_password": "<NEW_ADMIN_PASSWORD>"})

_add("GET /api/tokens", ("Inspect accounts and scheduling state", "Xem tài khoản và trạng thái điều phối", "查看账号及调度状态"),
     ("Returns the account list with account/project metadata, credits, active/expiry state, image/video permissions and concurrency, proxy/extension routing and refresh results. Use it to obtain numeric token_id values for subsequent operations and diagnose why an account is unavailable. This is privileged account data; do not expose its response in public clients.",
      "Trả danh sách tài khoản cùng dự án, số dư, trạng thái hoạt động/hết hạn, quyền ảnh/video, đồng thời, proxy/định tuyến extension và kết quả làm mới. Lấy token_id số ở đây cho thao tác tiếp theo và chẩn đoán tài khoản không sẵn sàng. Đây là dữ liệu đặc quyền, không đưa phản hồi ra ứng dụng công khai.",
      "返回账号列表及项目、余额、启用/过期状态、图像/视频权限与并发、代理/扩展路由和刷新结果。由此取得后续操作所需的数字 token_id，并排查账号不可用原因。响应属于管理数据，不应暴露给公共客户端。"))

_ACCOUNT_EXAMPLE = {
    "st": "<OPTIONAL_SESSION_IDENTIFIER>", "project_id": "<OPTIONAL_FLOW_PROJECT_ID>",
    "project_name": "<OPTIONAL_PROJECT_NAME>", "remark": "<ACCOUNT_LABEL>",
    "captcha_proxy_url": "<OPTIONAL_CAPTCHA_PROXY_URL>", "extension_route_key": "<OPTIONAL_EXTENSION_ROUTE_KEY>",
    "image_enabled": True, "video_enabled": True, "image_concurrency": -1, "video_concurrency": -1,
    "protocol_mode": "protocol", "google_cookies": "<FULL_GOOGLE_FLOW_COOKIE_STRING>",
    "login_account": "account@example.com", "login_password": "<OPTIONAL_ACCOUNT_PASSWORD>",
    "proxy_url": "<OPTIONAL_ACCOUNT_PROXY_URL>", "auto_refresh_enabled": True, "refresh_interval_minutes": 30,
}
_add("POST /api/tokens", ("Add a Flow account", "Thêm tài khoản Flow", "添加 Flow 账号"),
     ("Validates supplied Google/Flow cookies, acquires access credentials and creates an account/project record. google_cookies is required (1–524288 characters); protocol_mode currently only accepts protocol. login_account is optional and normalized to lowercase; when supplied it must be an email address. The service can detect identity or use a placeholder identity. Set image/video permissions, concurrency (-1 is the unlimited sentinel), per-account proxy and extension route as needed. Refresh interval is 1–10080 minutes. Returns success/message and token {id,email,credits,project_id,project_name}; invalid account data returns HTTP 400 and other failures HTTP 500. Optional example fields can be omitted rather than submitting placeholder text.",
      "Xác minh đầy đủ cookie Google/Flow, lấy thông tin truy cập và tạo tài khoản/dự án. google_cookies bắt buộc (1–524288 ký tự); protocol_mode hiện chỉ nhận protocol. login_account tùy chọn, chuyển chữ thường và phải là email nếu có. Dịch vụ có thể nhận diện tài khoản hoặc dùng danh tính tạm. Có thể đặt quyền ảnh/video, đồng thời (-1 là không giới hạn), proxy và tuyến extension riêng. Chu kỳ làm mới 1–10080 phút. Trả success/message và token {id,email,credits,project_id,project_name}; dữ liệu sai trả HTTP 400, lỗi khác HTTP 500. Có thể bỏ các trường tùy chọn trong ví dụ thay vì gửi chuỗi giữ chỗ.",
      "验证完整 Google/Flow Cookie，获取访问凭据并创建账号/项目记录。google_cookies 必填（1–524288 字符）；protocol_mode 当前仅接受 protocol。login_account 可省略，提供时必须为邮箱并转为小写；服务可识别身份或使用占位身份。可设置图像/视频权限、并发（-1 表示无限制）、账号代理和扩展路由。刷新间隔为 1–10080 分钟。返回 success/message 和 token {id,email,credits,project_id,project_name}；无效账号数据返回 HTTP 400，其他错误 HTTP 500。示例中的可选字段可直接省略，无需提交占位文字。"), body=_ACCOUNT_EXAMPLE)
_add("PUT /api/tokens/{token_id}", ("Update and revalidate an account", "Cập nhật và xác minh lại tài khoản", "更新并重新验证账号"),
     ("Uses numeric account token_id. Revalidates the supplied cookies or the saved cookies even for a metadata-only update, then updates provided account/project, proxy, routing, generation permissions and refresh fields. Omitted optional values generally preserve saved values; empty st/cookies fall back to the saved credentials during validation. Nonempty new cookies are marked validated and concurrency limits are hot-reloaded. Returns success/message; validation ValueError becomes HTTP 400 and other errors HTTP 500. protocol_mode only accepts protocol when present. Do not assume this is an offline metadata patch.",
      "Dùng token_id số của tài khoản. Xác minh cookie mới hoặc cookie lưu sẵn ngay cả khi chỉ sửa thông tin, rồi cập nhật dự án, proxy, tuyến, quyền tạo và trường làm mới đã gửi. Trường tùy chọn bỏ qua thường giữ giá trị cũ; st/cookie rỗng dùng thông tin đã lưu khi xác minh. Cookie mới được đánh dấu hợp lệ và giới hạn đồng thời áp dụng ngay. Trả success/message; ValueError trả HTTP 400, lỗi khác HTTP 500. protocol_mode chỉ nhận protocol nếu gửi. Đây không phải cập nhật metadata ngoại tuyến.",
      "使用数字账号 token_id。即使仅修改备注，也会先用新 Cookie 或已保存 Cookie 重新验证，再更新提供的账号/项目、代理、路由、生成权限和刷新字段。省略可选字段通常保留原值；验证时空 st/Cookie 回退到已保存凭据。新 Cookie 会标记为已验证，并发限制立即刷新。返回 success/message；ValueError 转为 HTTP 400，其他错误 HTTP 500。提供 protocol_mode 时仅可为 protocol。此操作依赖账号在线验证。"), body=_ACCOUNT_EXAMPLE)
_add("DELETE /api/tokens/{token_id}", ("Delete an account", "Xóa tài khoản", "删除账号"),
     ("Deletes the local account record and removes its concurrency-manager state. Returns success/message; failures become HTTP 500. This removes the server's saved account configuration, not the upstream Google account.",
      "Xóa bản ghi tài khoản cục bộ và trạng thái bộ quản lý đồng thời. Trả success/message; lỗi trả HTTP 500. Thao tác xóa cấu hình tài khoản lưu trên máy chủ, không xóa tài khoản Google.",
      "删除本地账号记录并移除并发管理状态。返回 success/message，失败为 HTTP 500。删除的是服务器保存的账号配置，不是 Google 账号。"))
_add("POST /api/tokens/{token_id}/enable", ("Enable account scheduling", "Bật điều phối tài khoản", "启用账号调度"),
     ("Marks the account active for eligible future generation requests and returns success/message. An incomplete browser-pending account returns HTTP 409; complete browser sign-in and Cookie validation first. This does not itself repair expired cookies, increase credits or change image/video permissions; inspect account state and refresh when needed.",
      "Đánh dấu tài khoản hoạt động cho yêu cầu tạo phù hợp sau này và trả success/message. Tài khoản browser-pending chưa hoàn tất trả HTTP 409; cần đăng nhập trình duyệt và xác minh Cookie trước. Thao tác không sửa cookie hết hạn, tăng số dư hoặc đổi quyền ảnh/video; kiểm tra trạng thái và làm mới khi cần.",
      "将账号设为启用，使其可参与后续符合条件的生成请求，并返回 success/message。未完成的 browser-pending 账号返回 HTTP 409，必须先完成浏览器登录和 Cookie 验证。启用不会修复过期 Cookie、增加余额或更改图像/视频权限；需要时另行检查与刷新。"))
_add("POST /api/tokens/{token_id}/disable", ("Disable account scheduling", "Tắt điều phối tài khoản", "停用账号调度"),
     ("Marks the account inactive so it is excluded from future selection while retaining its configuration. Returns success/message. Useful before cookie replacement or account maintenance; use enable to restore availability.",
      "Đánh dấu tài khoản không hoạt động để loại khỏi lựa chọn tiếp theo nhưng giữ cấu hình. Trả success/message. Dùng trước khi đổi cookie hoặc bảo trì; gọi enable để bật lại.",
      "将账号设为停用，在保留配置的同时排除后续调度。返回 success/message。适用于更换 Cookie 或维护账号；通过 enable 恢复。"))
_add("POST /api/tokens/{token_id}/refresh-credits", ("Refresh upstream account credits", "Làm mới số dư tài khoản", "刷新上游账号余额"),
     ("Fetches current upstream credits and persists the account balance. Returns success/message/credits; upstream or account failures return HTTP 500. Use before capacity planning rather than treating the saved dashboard balance as live billing data.",
      "Lấy số dư hiện tại từ dịch vụ và lưu lại. Trả success/message/credits; lỗi dịch vụ hoặc tài khoản trả HTTP 500. Dùng trước khi đánh giá dung lượng thay vì coi số dư dashboard luôn tức thời.",
      "从上游读取当前余额并更新本地记录，返回 success/message/credits。上游或账号错误返回 HTTP 500。规划容量前可主动刷新，面板保存的余额未必实时。"))
_add("POST /api/tokens/{token_id}/refresh-at", ("Refresh and validate complete cookies", "Làm mới và xác minh cookie đầy đủ", "刷新并验证完整 Cookie"),
     ("Despite the historical refresh-at name, forces complete Google/Flow Cookie refresh and session validation regardless of AT expiry. Returns success/message and token {id,email,at_expires}. Failed refresh returns HTTP 500 with the saved sanitized refresh result or an instruction to resync full Google cookies. It is not just an expiry timestamp update.",
      "Dù tên cũ là refresh-at, thao tác buộc làm mới đầy đủ cookie Google/Flow và xác minh phiên bất kể AT đã hết hạn chưa. Trả success/message và token {id,email,at_expires}. Thất bại trả HTTP 500 với kết quả làm mới đã lọc hoặc yêu cầu đồng bộ lại cookie Google đầy đủ. Không chỉ đổi thời điểm hết hạn.",
      "虽然沿用 refresh-at 名称，实际会强制刷新完整 Google/Flow Cookie 并验证登录状态，不取决于 AT 是否到期。返回 success/message 和 token {id,email,at_expires}。失败返回 HTTP 500，附已清理的刷新结果或重新同步完整 Google Cookie 的提示；并非仅修改到期时间。"))

_add("POST /api/browser-sessions/accounts",
     ("Add an account through browser sign-in", "Thêm tài khoản bằng đăng nhập trình duyệt", "通过浏览器登录添加账号"),
     ("Accepts only the Google account email; no Cookie, API key, Google password or existing account ID is required. Works when the account list is empty. The email is an ASCII address of at most 254 characters with a local part of at most 64 characters, trimmed and normalized case-insensitively; extra body fields are rejected. An existing email reuses its account with created=false without replacing credentials or settings. Otherwise creates an inactive browser-pending draft with empty cookies and no access token, then starts the normal Chrome/Edge login flow. The draft is excluded from generation until the observed Flow identity matches this email and current RPC validation succeeds. Complete sign-in and close all windows of the dedicated profile to allow synchronization. Returns {success,created,session}; poll GET /api/tokens/{token_id}/browser-session using session.token_id. Invalid input returns HTTP 422, missing admin authentication HTTP 401, and an unrelated browser Origin HTTP 403. Browser failures are sanitized session error codes; a failed login leaves an inactive draft that can be retried or deleted. This endpoint does not bypass Google verification or change CAPTCHA settings.",
      "Chỉ cần email tài khoản Google; không cần Cookie, khóa API, mật khẩu Google hay ID tài khoản có sẵn. Dùng được khi danh sách chưa có tài khoản. Email là địa chỉ ASCII dài tối đa 254 ký tự, phần trước @ tối đa 64 ký tự, được bỏ khoảng trắng đầu/cuối và chuẩn hóa không phân biệt hoa thường; trường body ngoài email bị từ chối. Nếu email đã tồn tại, dùng lại tài khoản với created=false mà không thay thông tin xác thực hay cấu hình. Nếu chưa có, tạo bản nháp browser-pending đang tắt, cookie rỗng và chưa có access token, rồi mở luồng đăng nhập Chrome/Edge thông thường. Bản nháp không được dùng để tạo nội dung cho đến khi danh tính Flow khớp email và xác minh RPC hiện tại thành công. Hoàn tất đăng nhập rồi đóng toàn bộ cửa sổ của profile riêng để đồng bộ. Trả {success,created,session}; dùng session.token_id để thăm dò GET /api/tokens/{token_id}/browser-session. Dữ liệu sai trả HTTP 422, thiếu phiên admin trả HTTP 401, Origin trình duyệt khác nguồn trả HTTP 403. Lỗi trình duyệt dùng mã đã lọc; đăng nhập thất bại giữ bản nháp đang tắt để thử lại hoặc xóa. Endpoint không bỏ qua xác minh Google hay đổi cấu hình CAPTCHA.",
      "只需 Google 账号邮箱，无需 Cookie、API Key、Google 密码或已有账号 ID，账号列表为空时也可使用。邮箱必须是最多 254 字符的 ASCII 地址，@ 前最多 64 字符，去除首尾空白并按不区分大小写规范化；拒绝 email 以外的请求字段。邮箱已存在时复用该账号并返回 created=false，不替换凭据或配置。否则创建停用的 browser-pending 草稿，Cookie 为空且没有 Access Token，然后启动普通 Chrome/Edge 登录流程。只有 Flow 身份匹配邮箱并通过当前 RPC 验证后，草稿才可用于生成。完成登录后关闭该独立 profile 的所有窗口以同步。返回 {success,created,session}，使用 session.token_id 轮询 GET /api/tokens/{token_id}/browser-session。输入无效返回 HTTP 422，缺少管理认证返回 HTTP 401，浏览器 Origin 不同源返回 HTTP 403。浏览器失败使用清理后的会话错误码；登录失败保留停用草稿供重试或删除。本接口不会绕过 Google 验证或修改验证码配置。"),
     body={"email": "account@example.com"})

_add("GET /api/tokens/{token_id}/browser-session",
     ("Inspect a managed browser session", "Xem phiên trình duyệt được quản lý", "查看托管浏览器会话"),
     ("Returns {success,session:{token_id,enabled,status,browser_open,last_sync_at,error_code,interval_minutes}} without opening a browser. States are not_configured, opening, awaiting_login, syncing, ready, needs_login, error and stopped. last_sync_at is an ISO timestamp or null; error_code is a sanitized code or null. No cookies, passwords, proxy credentials or profile paths are returned. A missing account returns HTTP 404. ready describes the last successful synchronization, not a guarantee that Google will never expire the session.",
      "Trả {success,session:{token_id,enabled,status,browser_open,last_sync_at,error_code,interval_minutes}} mà không mở trình duyệt. Trạng thái gồm not_configured, opening, awaiting_login, syncing, ready, needs_login, error, stopped. last_sync_at là thời điểm ISO hoặc null; error_code là mã lỗi đã lọc hoặc null. Không trả cookie, mật khẩu, thông tin xác thực proxy hay đường dẫn profile. Tài khoản không tồn tại trả HTTP 404. ready mô tả lần đồng bộ thành công gần nhất, không bảo đảm Google sẽ không làm hết hạn phiên.",
      "返回 {success,session:{token_id,enabled,status,browser_open,last_sync_at,error_code,interval_minutes}}，不会打开浏览器。状态包括 not_configured、opening、awaiting_login、syncing、ready、needs_login、error、stopped。last_sync_at 是 ISO 时间或 null；error_code 是经过清理的错误代码或 null。不会返回 Cookie、密码、代理凭据或 profile 路径。账号不存在返回 HTTP 404。ready 仅描述最近一次同步成功，不保证 Google 永不使会话失效。"))

_add("POST /api/tokens/{token_id}/browser-session/login",
     ("Open a normal account browser for manual sign-in", "Mở trình duyệt thông thường để đăng nhập tài khoản", "打开普通账号浏览器手动登录"),
     ("No request body. Opens installed Chrome or Edge as a normal standalone browser on the Flow2API server using an isolated persistent account profile. No automation or remote-debugging connection controls the browser during Google sign-in. The user must complete Google/Flow sign-in and then close all windows of that dedicated profile. Only after the browser exits can the application reopen the profile in the background, verify the Flow account identity and current RPC, and save cookies. Poll GET browser-session; the watcher waits up to ten minutes. Successful explicit login may reactivate this account; background sync never reactivates it. Periodic sync requires the profile, global and account refresh switches. CAPTCHA settings are independent. Login/launch failures use sanitized error_code; a missing account returns HTTP 404. Requires installed Chrome/Edge and an interactive server desktop. Authenticated browser proxies are unsupported for this manual launcher. Google may still require verification or reject sign-in for other reasons.",
      "Không cần body. Mở Chrome hoặc Edge đã cài như trình duyệt thông thường trên máy chạy Flow2API, dùng profile riêng cho tài khoản. Trong lúc đăng nhập Google không có điều khiển tự động hay kết nối gỡ lỗi từ xa. Người dùng cần đăng nhập Google/Flow rồi đóng toàn bộ cửa sổ của profile riêng đó. Sau khi trình duyệt thoát, ứng dụng mới mở lại profile trong nền, kiểm tra đúng danh tính Flow và RPC hiện tại rồi lưu cookie. Thăm dò GET browser-session; bộ theo dõi chờ tối đa mười phút. Đăng nhập chủ động thành công có thể bật lại tài khoản; đồng bộ nền không tự bật tài khoản. Đồng bộ định kỳ cần bật profile, công tắc làm mới chung và riêng tài khoản. Hoạt động độc lập với CAPTCHA. Lỗi đăng nhập/mở trình duyệt dùng error_code đã lọc; tài khoản không tồn tại trả HTTP 404. Cần Chrome/Edge đã cài và màn hình thao tác trên server. Luồng mở thủ công chưa hỗ trợ proxy cần tên đăng nhập/mật khẩu. Google vẫn có thể yêu cầu xác minh hoặc từ chối đăng nhập vì nguyên nhân khác.",
      "无需请求正文。在 Flow2API 服务器使用账号独立持久化 profile，启动已安装的普通 Chrome 或 Edge。Google 登录期间没有自动化控制或远程调试连接。用户完成 Google/Flow 登录后必须关闭该独立 profile 的所有窗口。浏览器退出后，程序才会在后台重新打开 profile，检查 Flow 身份与当前 RPC，然后保存 Cookie。通过 GET browser-session 轮询，最长等待十分钟。主动登录成功可以恢复此账号，后台同步不会自动启用账号。定时同步需启用 profile、全局和账号刷新开关，与验证码配置独立。失败返回清理后的 error_code，账号不存在返回 HTTP 404。需要已安装的 Chrome/Edge 和可操作的服务器桌面。手动启动暂不支持需要用户名密码的浏览器代理。Google 仍可能要求验证或因其他原因拒绝登录。"))

_add("POST /api/tokens/{token_id}/browser-session/sync",
     ("Synchronize cookies from the saved browser profile", "Đồng bộ cookie từ profile trình duyệt đã lưu", "从保存的浏览器 profile 同步 Cookie"),
     ("No request body. Performs an immediate synchronization from this account's managed profile. Reuses its open browser, or may open a temporary headless context from the saved profile and close it afterwards. Never imports another account's profile or exposes raw cookies. Checks Flow identity and validates the current RPC before committing cookie/credential changes. Does not reactivate a disabled account or change CAPTCHA settings. A missing/expired login is reported as needs_login with a sanitized error_code; use the explicit login endpoint when user action is needed. Returns the same session envelope as GET; success=true means the operation was handled, so inspect session.status and error_code rather than assuming authentication was renewed. A missing account returns HTTP 404.",
      "Không cần body. Đồng bộ ngay từ profile được quản lý của tài khoản này. Dùng lại trình duyệt đang mở hoặc có thể mở context không cửa sổ tạm từ profile đã lưu rồi đóng sau đó. Không dùng profile tài khoản khác hay trả cookie thô. Kiểm tra danh tính Flow và xác minh RPC hiện tại trước khi lưu cookie/thông tin truy cập. Không tự bật tài khoản đang tắt và không đổi cấu hình CAPTCHA. Chưa đăng nhập hoặc phiên hết hiệu lực được báo needs_login cùng error_code đã lọc; dùng endpoint login khi cần người dùng thao tác. Trả cùng cấu trúc session như GET; success=true chỉ nghĩa thao tác đã được xử lý, cần đọc session.status và error_code để biết đã gia hạn được hay chưa. Thiếu tài khoản trả HTTP 404.",
      "无需请求正文，立即从该账号的托管 profile 同步。复用已打开浏览器，或从保存的 profile 临时启动无头上下文并在完成后关闭。不会使用其他账号的 profile 或返回原始 Cookie。提交 Cookie/凭据变更前检查 Flow 身份并验证当前 RPC。不会重新启用已禁用账号，也不修改 CAPTCHA 设置。缺失或失效的登录以 needs_login 及清理后的 error_code 表示；需要用户操作时调用主动登录接口。返回与 GET 相同的 session 包装；success=true 仅表示操作已处理，是否续期成功须检查 session.status 和 error_code。账号不存在返回 HTTP 404。"))

_add("POST /api/tokens/{token_id}/browser-session/stop",
     ("Stop browser synchronization and close its window", "Dừng đồng bộ trình duyệt và đóng cửa sổ", "停止浏览器同步并关闭窗口"),
     ("No request body. Cancels the account's pending login watcher, disables managed-profile periodic synchronization and closes its browser context. Preserves the account's existing cookies and on-disk profile so a later login can reuse it; this is not Google logout or recursive profile deletion. Does not change the global refresh switch, account generation permissions or CAPTCHA provider. Returns session with enabled=false and status=stopped. A missing account returns HTTP 404.",
      "Không cần body. Hủy bộ theo dõi đăng nhập đang chờ, tắt đồng bộ profile định kỳ và đóng context trình duyệt của tài khoản. Giữ cookie hiện có của tài khoản và profile trên đĩa để lần đăng nhập sau dùng lại; không đăng xuất Google hay xóa đệ quy profile. Không đổi công tắc làm mới chung, quyền tạo nội dung hay nhà cung cấp CAPTCHA. Trả session với enabled=false, status=stopped. Thiếu tài khoản trả HTTP 404.",
      "无需请求正文。取消该账号待完成的登录监视，禁用托管 profile 定时同步并关闭浏览器上下文。保留账号现有 Cookie 和磁盘 profile，后续登录可以复用；此操作不是 Google 退出登录，也不会递归删除 profile。不修改全局刷新开关、账号生成权限或 CAPTCHA 提供方。返回 session，其中 enabled=false、status=stopped。账号不存在返回 HTTP 404。"))
_add("POST /api/tokens/st2at", ("Validate cookies without saving an account", "Xác minh cookie mà không lưu tài khoản", "验证 Cookie 而不保存账号"),
     ("Calls the current Flow credential validation/conversion path and returns success/message/access_token/email/expires without adding a database account. The historical st field remains accepted, but current account onboarding uses complete google_cookies. Invalid credentials/upstream conversion failures return HTTP 400. Treat the returned access_token as sensitive.",
      "Gọi luồng xác minh/chuyển đổi thông tin Flow hiện tại và trả success/message/access_token/email/expires mà không thêm tài khoản vào cơ sở dữ liệu. Trường st cũ vẫn được nhận nhưng thêm tài khoản hiện dùng google_cookies đầy đủ. Thông tin sai hoặc lỗi chuyển đổi trả HTTP 400. access_token trả về là dữ liệu nhạy cảm.",
      "调用当前 Flow 凭据验证/转换逻辑，返回 success/message/access_token/email/expires，不添加数据库账号。保留历史 st 字段，但当前账号接入使用完整 google_cookies。凭据无效或转换失败返回 HTTP 400。返回的 access_token 属于敏感凭据。"), body={"st": "<OPTIONAL_SESSION_IDENTIFIER>", "google_cookies": "<FULL_GOOGLE_FLOW_COOKIE_STRING>"})

_IMPORT_ITEM = {key: value for key, value in _ACCOUNT_EXAMPLE.items() if key not in {"st", "login_password"}}
_IMPORT_ITEM["is_active"] = True
_add("POST /api/tokens/import", ("Batch import current cookie accounts", "Nhập hàng loạt tài khoản cookie", "批量导入当前 Cookie 账号"),
     ("Accepts a JSON object {tokens:[...]} with 1–100 account objects; it is not a raw cookie list, file upload, legacy ST-only array, or arbitrary token export. Each item requires google_cookies, only permits declared fields (extra fields rejected), and supports the settings shown in the example. login_account may be omitted for identity detection; nonempty emails must be unique case-insensitively within the batch. Cookies are validated one item at a time; existing email identities are updated, new identities added. is_active=false or already-expired credentials disable the account. Returns added/updated counts and per-item errors (or null); partial success can have success=true plus errors, so inspect both. Invalid batch schema returns HTTP 422 before any imports. No transactional all-or-nothing guarantee.",
      "Nhận đối tượng JSON {tokens:[...]} gồm 1–100 tài khoản; không nhận danh sách cookie thuần, tải tệp, mảng chỉ ST cũ hoặc bản xuất token bất kỳ. Mỗi mục bắt buộc google_cookies, chỉ nhận trường khai báo và hỗ trợ cấu hình trong ví dụ. Có thể bỏ login_account để tự nhận diện; email có giá trị phải duy nhất không phân biệt hoa thường trong lô. Cookie được xác minh từng mục; email đã có được cập nhật, mới được thêm. is_active=false hoặc thông tin đã hết hạn sẽ tắt tài khoản. Trả added/updated và lỗi từng mục (hoặc null); thành công một phần có thể success=true kèm errors nên đọc cả hai. Sai schema trả HTTP 422 trước khi nhập. Không bảo đảm giao dịch toàn bộ hoặc không mục nào.",
      "接收 JSON 对象 {tokens:[...]}，包含 1–100 个账号对象；不是纯 Cookie 列表、文件上传、旧版仅 ST 数组或任意 Token 导出格式。每项必填 google_cookies，仅允许声明字段，支持示例中的设置。可省略 login_account 自动识别；批次内非空邮箱忽略大小写后必须唯一。逐项验证 Cookie，按邮箱更新已有账号或新增账号。is_active=false 或凭据已过期时停用账号。返回 added/updated 计数和逐项 errors（无错误为 null）；部分成功可能同时有 success=true 和 errors，应同时检查。批次结构无效会在导入前返回 HTTP 422。此接口不保证整批原子性。"), body={"tokens": [_IMPORT_ITEM]})

_PROXY_BODY = {"proxy_enabled": True, "proxy_url": "<REQUEST_PROXY_URL>", "media_proxy_enabled": True, "media_proxy_url": "<MEDIA_PROXY_URL>"}
_add("GET /api/config/proxy", ("Read request and media proxy settings", "Đọc proxy yêu cầu và media", "读取请求与媒体代理设置"),
     ("Returns {success,config:{enabled,proxy_url,media_proxy_enabled,media_proxy_url}}. Request and media-download proxies are independently configurable. This response shape differs from GET /api/proxy/config, which returns flat proxy_enabled fields.",
      "Trả {success,config:{enabled,proxy_url,media_proxy_enabled,media_proxy_url}}. Proxy yêu cầu và tải media được cấu hình riêng. Dạng phản hồi khác GET /api/proxy/config vốn trả các trường phẳng proxy_enabled.",
      "返回 {success,config:{enabled,proxy_url,media_proxy_enabled,media_proxy_url}}。请求代理与媒体下载代理可分别配置；与返回扁平 proxy_enabled 字段的 GET /api/proxy/config 结构不同。"))
_add("GET /api/proxy/config", ("Read flat proxy settings", "Đọc cấu hình proxy dạng phẳng", "读取扁平代理配置"),
     ("Frontend-compatible read alias returning proxy_enabled, proxy_url, media_proxy_enabled and media_proxy_url directly, without success/config wrapping. Reads the same saved settings as /api/config/proxy.",
      "Đường dẫn tương thích frontend trả trực tiếp proxy_enabled, proxy_url, media_proxy_enabled, media_proxy_url, không bọc success/config. Đọc cùng cấu hình lưu với /api/config/proxy.",
      "前端兼容读取路径，直接返回 proxy_enabled、proxy_url、media_proxy_enabled、media_proxy_url，没有 success/config 包装；读取与 /api/config/proxy 相同的配置。"))
_add(["POST /api/config/proxy", "POST /api/proxy/config"],
     ("Save request and media proxy settings", "Lưu proxy yêu cầu và media", "保存请求与媒体代理"),
     ("Both POST paths accept the same body: required proxy_enabled and optional proxy_url/media_proxy_enabled/media_proxy_url. Proxy validation/normalization is delegated to ProxyManager. Returns success/message; an invalid proxy can return HTTP 200 with success=false, so do not infer success from status alone. Saving does not run the connectivity probe; call /api/proxy/test separately.",
      "Hai đường dẫn POST nhận cùng body: proxy_enabled bắt buộc và proxy_url/media_proxy_enabled/media_proxy_url tùy chọn. ProxyManager xác minh/chuẩn hóa proxy. Trả success/message; proxy sai có thể trả HTTP 200 với success=false, không chỉ dựa vào mã HTTP. Lưu không tự kiểm tra kết nối; gọi riêng /api/proxy/test.",
      "两个 POST 路径接收同一请求：必填 proxy_enabled，可选 proxy_url/media_proxy_enabled/media_proxy_url。由 ProxyManager 验证和规范化代理。返回 success/message；代理无效可能仍是 HTTP 200、success=false，应检查正文。保存不会执行连通性探测，需要另调 /api/proxy/test。"), body=_PROXY_BODY)
_add("POST /api/proxy/test", ("Probe proxy connectivity", "Kiểm tra kết nối proxy", "测试代理连通性"),
     ("Tests the supplied proxy without saving configuration. Defaults target Flow and timeout 15 seconds; timeout is clamped to 5–60 seconds. Follows redirects using a browser impersonation; this probe disables TLS certificate verification. Returns success/message/test_url and, when available, final_url/status_code/elapsed_ms. Target HTTP 200–399 counts as success. Empty/invalid proxies, network errors and target failures are reported in the body rather than necessarily non-2xx status codes.",
      "Kiểm tra proxy gửi lên mà không lưu. Mặc định đích Flow, chờ 15 giây; thời gian được giới hạn 5–60 giây. Theo chuyển hướng với giả lập trình duyệt và tắt xác minh chứng chỉ TLS cho phép thử này. Trả success/message/test_url cùng final_url/status_code/elapsed_ms khi có. HTTP 200–399 của đích là thành công. Proxy rỗng/sai, lỗi mạng và lỗi đích được báo trong body, không nhất thiết mã HTTP ngoài 2xx.",
      "测试传入代理，不保存配置。默认访问 Flow、超时 15 秒，超时会限制在 5–60 秒。探测模拟浏览器并跟随重定向，且关闭 TLS 证书验证。返回 success/message/test_url，以及可用时的 final_url/status_code/elapsed_ms；目标返回 HTTP 200–399 视为成功。空/无效代理、网络和目标错误通常通过正文表达，不一定返回非 2xx。"),
     body={"proxy_url": "<PROXY_URL>", "test_url": "https://flow.google.com/", "timeout_seconds": 15})

_add(["GET /api/config/generation", "GET /api/generation/timeout"],
     ("Read generation timeouts and retry budget", "Đọc thời gian chờ và số lần thử lại", "读取生成超时与重试次数"),
     ("Both paths return {success,config:{image_timeout,video_timeout,max_retries}}. Values control server-side generation, independently of the HTTP client's own timeout. Configure a client/proxy timeout long enough for the selected image/video workload.",
      "Hai đường dẫn trả {success,config:{image_timeout,video_timeout,max_retries}}. Các giá trị điều khiển tạo nội dung phía máy chủ, độc lập thời gian chờ HTTP của máy khách. Cần đặt thời gian chờ máy khách/proxy đủ dài cho tác vụ ảnh/video.",
      "两个路径返回 {success,config:{image_timeout,video_timeout,max_retries}}，控制服务端生成，与 HTTP 客户端超时独立。客户端与反向代理的超时应足够覆盖所选图像/视频任务。"))
_add(["POST /api/config/generation", "POST /api/generation/timeout"],
     ("Update generation timeouts and retry budget", "Cập nhật thời gian chờ và thử lại", "更新生成超时与重试次数"),
     ("Both paths accept optional integer image_timeout/video_timeout (seconds) and max_retries; omitted/null fields are passed as None to the persistence layer. Saves settings and reloads runtime configuration, then returns success/message. These request fields have no explicit numeric range constraints in the route schema; use sensible nonnegative retry counts and positive timeouts.",
      "Hai đường dẫn nhận số nguyên tùy chọn image_timeout/video_timeout (giây) và max_retries; trường bỏ qua/null được chuyển None tới lớp lưu. Lưu và nạp lại cấu hình chạy rồi trả success/message. Schema đường dẫn không giới hạn khoảng số; dùng số lần thử lại không âm và thời gian chờ dương hợp lý.",
      "两个路径接受可选整数 image_timeout/video_timeout（秒）及 max_retries；省略/null 作为 None 传给持久化层。保存并重载运行配置后返回 success/message。路由模型未为这些字段声明数值范围，应使用合理的正超时和非负重试次数。"), body={"image_timeout": 300, "video_timeout": 1500, "max_retries": 3})
_add("GET /api/call-logic/config", ("Read account selection mode", "Đọc chế độ chọn tài khoản", "读取账号选择模式"),
     ("Returns success/config with call_mode (default or polling) and compatibility boolean polling_mode_enabled. Older stored configuration is normalized to one of those modes. This controls selection across eligible accounts, not video job status polling.",
      "Trả success/config gồm call_mode (default hoặc polling) và boolean tương thích polling_mode_enabled. Cấu hình cũ được chuẩn hóa về hai chế độ. Điều khiển lựa chọn tài khoản phù hợp, không phải thăm dò trạng thái tác vụ video.",
      "返回 success/config，含 call_mode（default 或 polling）及兼容布尔值 polling_mode_enabled。旧配置会归一为这两种模式。此处控制候选账号选择，不是视频任务状态轮询。"))
_add("POST /api/call-logic/config", ("Change account selection mode", "Đổi chế độ chọn tài khoản", "更改账号选择模式"),
     ("call_mode must be exactly default or polling; any other value returns HTTP 400. Saves and hot-reloads selection policy, returning success/message/config with both call_mode and polling_mode_enabled. Use polling to rotate through eligible accounts; availability/permissions/concurrency still apply.",
      "call_mode phải chính xác default hoặc polling; giá trị khác trả HTTP 400. Lưu và áp dụng ngay chính sách lựa chọn, trả success/message/config với call_mode và polling_mode_enabled. Dùng polling để luân phiên tài khoản phù hợp; điều kiện hoạt động/quyền/đồng thời vẫn áp dụng.",
      "call_mode 必须精确为 default 或 polling，其他值返回 HTTP 400。保存并立即重载选择策略，返回 success/message/config，含 call_mode 与 polling_mode_enabled。polling 用于轮换符合条件的账号，仍受可用性、权限和并发限制。"), body={"call_mode": "polling"})

_add("GET /api/system/info", ("Read system account totals", "Đọc tổng tài khoản hệ thống", "读取系统账号汇总"),
     ("Returns {success,info:{total_tokens,active_tokens,total_credits,version}} for a compact management overview. The route reports a fixed version string; use release/deployment metadata rather than this field for exact build identification.",
      "Trả {success,info:{total_tokens,active_tokens,total_credits,version}} cho tổng quan quản trị gọn. Đường dẫn báo chuỗi phiên bản cố định; dùng metadata phát hành/triển khai để xác định bản dựng chính xác.",
      "返回 {success,info:{total_tokens,active_tokens,total_credits,version}}，用于精简管理概览。路由中的 version 为固定字符串，识别实际构建版本应参考发布/部署元数据。"))
_add("GET /health", ("Public health and account availability", "Sức khỏe và khả dụng công khai", "公开健康与账号可用性"),
     ("No authentication. Returns the public health snapshot, including backend_running and has_active_tokens. If snapshot construction fails, the fallback still returns backend_running=true and has_active_tokens=false. HTTP 200 alone therefore does not prove a generation account or CAPTCHA provider is usable.",
      "Không cần xác thực. Trả ảnh chụp sức khỏe công khai gồm backend_running và has_active_tokens. Nếu tạo ảnh chụp lỗi, phương án dự phòng vẫn trả backend_running=true và has_active_tokens=false. Vì vậy HTTP 200 chưa chứng minh tài khoản hoặc nhà cung cấp CAPTCHA dùng được.",
      "无需认证。返回公开健康快照，含 backend_running 和 has_active_tokens。构造快照失败时仍回退返回 backend_running=true、has_active_tokens=false。因此仅 HTTP 200 不能证明生成账号或 CAPTCHA 服务可用。"), auth=None)
_add("GET /metrics", ("Public Prometheus metrics", "Chỉ số Prometheus công khai", "公开 Prometheus 指标"),
     ("No route authentication. Returns Prometheus text exposition for the main service, database/account state and concurrency where available, rather than JSON. Suitable for scraping; restrict exposure at the deployment boundary if operational metrics should be private.",
      "Đường dẫn không xác thực. Trả văn bản Prometheus của dịch vụ chính, trạng thái cơ sở dữ liệu/tài khoản và đồng thời khi có, không phải JSON. Dùng để thu thập chỉ số; giới hạn ở lớp triển khai nếu cần giữ chỉ số nội bộ.",
      "路由无需认证。返回主服务、数据库/账号状态及可用并发信息的 Prometheus 文本，而非 JSON。适合采集；若运维指标应保密，可在部署入口限制访问。"), auth=None)
_add("GET /api/stats", ("Read dashboard statistics", "Đọc thống kê dashboard", "读取面板统计"),
     ("Returns the database dashboard statistics object directly, without a success/config envelope. Use for management summaries of account/request activity; combine with logs for individual request diagnostics.",
      "Trả trực tiếp đối tượng thống kê dashboard từ cơ sở dữ liệu, không bọc success/config. Dùng tổng quan tài khoản/yêu cầu; kết hợp logs để chẩn đoán từng yêu cầu.",
      "直接返回数据库面板统计对象，无 success/config 包装。适用于账号/请求活动汇总，单次请求问题应结合日志排查。"))
_add("GET /api/logs", ("List lightweight request logs", "Liệt kê nhật ký yêu cầu gọn", "列出轻量请求日志"),
     ("Returns a JSON array of recent log summaries with account identity, operation, status_code, duration, progress/status_text, timestamps and error_summary for failed requests. limit defaults to 100 and is clamped to 1–100. Full request/response payloads are excluded for list performance; fetch /api/logs/{log_id} on demand. Runtime messages remain in their original language.",
      "Trả mảng JSON tóm tắt log gần đây với danh tính tài khoản, thao tác, status_code, duration, tiến độ/status_text, thời điểm và error_summary khi lỗi. limit mặc định 100, giới hạn 1–100. Không kèm toàn bộ body để danh sách nhẹ; lấy /api/logs/{log_id} khi cần. Thông báo chạy giữ nguyên ngôn ngữ gốc.",
      "返回最近日志摘要数组，含账号身份、操作、status_code、duration、进度/status_text、时间及失败时的 error_summary。limit 默认 100，限制为 1–100。为提高列表性能不加载完整请求/响应正文；按需调用 /api/logs/{log_id}。运行时消息保留原语言。"), query={"limit": 100})
_add("GET /api/logs/{log_id}", ("Read full request log detail", "Đọc chi tiết đầy đủ nhật ký", "读取完整请求日志"),
     ("Returns a single log object with request_body and response_body loaded on demand, plus summary metadata and error_summary. Numeric log_id comes from the log list; nonexistent logs return HTTP 404. Payloads may contain prompts, media references and upstream diagnostics, so handle them as privileged data.",
      "Trả một log với request_body và response_body nạp khi cần, metadata tóm tắt và error_summary. log_id số lấy từ danh sách; không tồn tại trả HTTP 404. Body có thể chứa prompt, tham chiếu media và chẩn đoán dịch vụ nên xử lý như dữ liệu đặc quyền.",
      "按需加载单条日志的 request_body、response_body，同时返回摘要元数据和 error_summary。数字 log_id 来自日志列表，不存在返回 HTTP 404。正文可能包含提示词、媒体引用及上游诊断，属于管理数据。"))
_add("DELETE /api/logs", ("Clear all request logs", "Xóa toàn bộ nhật ký yêu cầu", "清空全部请求日志"),
     ("Deletes all saved request logs; no filter or per-log deletion is supported here. Returns success/message; database failure returns HTTP 500. Export any diagnostics you need before calling.",
      "Xóa toàn bộ log yêu cầu đã lưu; không hỗ trợ bộ lọc hoặc xóa từng log tại đây. Trả success/message; lỗi cơ sở dữ liệu trả HTTP 500. Xuất dữ liệu chẩn đoán cần giữ trước khi gọi.",
      "删除全部已保存请求日志，不支持筛选或逐条删除。返回 success/message，数据库错误返回 HTTP 500。调用前请保留所需诊断。"))

_add("GET /api/admin/config", ("Read admin settings and API key", "Đọc cấu hình quản trị và khóa API", "读取管理设置与 API Key"),
     ("Returns flat admin_username/api_key/error_ban_threshold/debug_enabled fields. api_key is the actual generation API credential, not a masked display value or admin session. debug_enabled reflects current in-memory state. Keep this response within the management interface.",
      "Trả các trường phẳng admin_username/api_key/error_ban_threshold/debug_enabled. api_key là khóa tạo nội dung thật, không phải giá trị che hay phiên quản trị. debug_enabled phản ánh bộ nhớ hiện tại. Chỉ dùng phản hồi trong giao diện quản trị.",
      "直接返回 admin_username/api_key/error_ban_threshold/debug_enabled。api_key 是实际生成凭据，并非脱敏显示或管理会话。debug_enabled 反映当前内存状态。响应应仅供管理界面使用。"))
_add("POST /api/admin/config", ("Set automatic account error threshold", "Đặt ngưỡng lỗi tài khoản", "设置账号错误阈值"),
     ("Updates only integer error_ban_threshold in the saved admin configuration and returns success/message. Other admin settings have separate endpoints. The request schema does not declare a minimum or maximum for this integer.",
      "Chỉ cập nhật số nguyên error_ban_threshold trong cấu hình quản trị đã lưu và trả success/message. Cấu hình khác có đường dẫn riêng. Schema không khai báo mức nhỏ/lớn nhất cho số này.",
      "仅更新已保存管理配置中的整数 error_ban_threshold，返回 success/message。其他管理设置使用各自接口；请求模型未声明此整数的最小或最大值。"), body={"error_ban_threshold": 3})
_add("POST /api/admin/apikey", ("Rotate the generation API key", "Đổi khóa API tạo nội dung", "更换生成 API Key"),
     ("Saves new_api_key and reloads runtime configuration immediately. Existing external clients must switch to the new generation key; this does not replace admin login credentials or the plugin connection token. Returns success/message. No nonempty/minimum-length constraint is declared in the request schema.",
      "Lưu new_api_key và nạp lại cấu hình ngay. Máy khách ngoài cần đổi sang khóa tạo mới; thao tác không đổi đăng nhập quản trị hoặc token plugin. Trả success/message. Schema không khai báo ràng buộc không rỗng/độ dài tối thiểu.",
      "保存 new_api_key 并立即重载配置，外部客户端需改用新生成密钥。此操作不更改管理登录凭据或插件连接令牌。返回 success/message；请求模型未声明非空或最短长度限制。"), body={"new_api_key": "<NEW_GENERATION_API_KEY>"})
_add("POST /api/admin/debug", ("Toggle temporary debug logging", "Bật/tắt log debug tạm thời", "切换临时调试日志"),
     ("Changes boolean enabled in memory only and returns success/message/enabled. It is intentionally not persisted to the database and debug mode is disabled again on restart. Failures return HTTP 500. Use temporarily while reproducing an issue.",
      "Đổi boolean enabled chỉ trong bộ nhớ và trả success/message/enabled. Cố ý không lưu cơ sở dữ liệu; debug tắt lại khi khởi động lại. Lỗi trả HTTP 500. Dùng tạm khi tái hiện sự cố.",
      "仅在内存中更改布尔 enabled，返回 success/message/enabled，不写入数据库，重启后调试模式再次关闭。失败返回 HTTP 500。适合临时复现问题时使用。"), body={"enabled": True})

_add("GET /api/token-refresh/config", ("Read automatic credential refresh settings", "Đọc cấu hình làm mới tự động", "读取自动凭据刷新设置"),
     ("Returns success/config with at_auto_refresh_enabled=true, protocol_refresh_enabled and refresh_interval_minutes. AT automatic refresh is always enabled; the configurable switch governs protocol/Cookie refresh. Per-account intervals are visible in the account list.",
      "Trả success/config với at_auto_refresh_enabled=true, protocol_refresh_enabled, refresh_interval_minutes. Tự làm mới AT luôn bật; công tắc cấu hình điều khiển làm mới protocol/cookie. Chu kỳ riêng từng tài khoản xem trong danh sách tài khoản.",
      "返回 success/config，含固定 true 的 at_auto_refresh_enabled、protocol_refresh_enabled 和 refresh_interval_minutes。AT 自动刷新始终启用；可配置开关控制协议/Cookie 刷新。账号专属间隔可在账号列表查看。"))
_add("POST /api/token-refresh/enabled", ("Toggle protocol credential refresh", "Bật/tắt làm mới protocol", "切换协议凭据刷新"),
     ("Optional JSON body; enabled absent/null makes no change. A supplied enabled value is converted with Python bool(), so send JSON true/false rather than strings. Changes the protocol-refresh switch only; AT refresh stays enabled. Returns success/message.",
      "Body JSON tùy chọn; thiếu/null enabled thì không đổi. Giá trị gửi được chuyển bằng bool() Python, hãy dùng true/false JSON thay vì chuỗi. Chỉ đổi công tắc làm mới protocol; AT vẫn luôn bật. Trả success/message.",
      "JSON 正文可省略；enabled 缺失/null 时不更改。提供的值通过 Python bool() 转换，应发送 JSON true/false 而不是字符串。仅控制协议刷新，AT 刷新始终启用。返回 success/message。"), body={"enabled": True}, fields={"enabled": "Optional boolean; absent/null preserves the setting. Send JSON booleans; nonempty strings are truthy."})
_add("POST /api/token-refresh/config", ("Save refresh interval and apply to accounts", "Lưu chu kỳ và áp dụng tài khoản", "保存刷新间隔并应用到账号"),
     ("Optional enabled and refresh_interval_minutes update global protocol-refresh settings; interval range is 1–10080 minutes. apply_to_tokens defaults false. When true and an interval is supplied, also overwrites all saved accounts' refresh intervals. Returns success/applied_to_tokens/config, including the always-true AT refresh indicator.",
      "enabled và refresh_interval_minutes tùy chọn đổi cấu hình protocol toàn cục; khoảng 1–10080 phút. apply_to_tokens mặc định false. Nếu true và có chu kỳ thì ghi đè chu kỳ của tất cả tài khoản lưu. Trả success/applied_to_tokens/config gồm chỉ báo AT luôn true.",
      "可选 enabled 和 refresh_interval_minutes 更新全局协议刷新设置，间隔范围为 1–10080 分钟。apply_to_tokens 默认 false；设为 true 且提供间隔时，同时覆盖全部已保存账号的刷新间隔。返回 success/applied_to_tokens/config，含始终为 true 的 AT 刷新标志。"), body={"enabled": True, "refresh_interval_minutes": 30, "apply_to_tokens": False})

_add("GET /api/cache/config", ("Read generated media cache settings", "Đọc cấu hình bộ nhớ đệm media", "读取生成媒体缓存设置"),
     ("Returns success/config with enabled, timeout, base_url and effective_base_url. Empty base_url reports the legacy effective fallback http://127.0.0.1:8000; configure a client-reachable public origin when cached URLs must work outside the server. This is generated-file caching, not prompt/response deduplication.",
      "Trả success/config gồm enabled, timeout, base_url, effective_base_url. base_url rỗng báo dự phòng cũ http://127.0.0.1:8000; đặt origin công khai mà máy khách truy cập được khi URL cache cần dùng ngoài máy chủ. Đây là cache tệp tạo ra, không khử trùng lặp prompt/phản hồi.",
      "返回 success/config，含 enabled、timeout、base_url、effective_base_url。base_url 为空时报告历史回退 http://127.0.0.1:8000；缓存链接需供外部客户端访问时，应配置其可访问的公开源地址。这是生成文件缓存，不是提示词/响应去重。"))
_add("POST /api/cache/enabled", ("Toggle generated media caching", "Bật/tắt cache media tạo ra", "切换生成媒体缓存"),
     ("Reads enabled with a default of false, persists it, reloads config and refreshes the cache cleanup task. Sending {} therefore disables caching. Returns success/message; this route does not purge all existing files.",
      "Đọc enabled mặc định false, lưu, nạp lại cấu hình và làm mới tác vụ dọn cache. Gửi {} sẽ tắt cache. Trả success/message; đường dẫn không xóa toàn bộ tệp hiện có.",
      "enabled 默认 false，保存后重载配置并刷新缓存清理任务，因此发送 {} 会关闭缓存。返回 success/message；此接口不清空所有现有文件。"), body={"enabled": True}, fields={"enabled": "Boolean; defaults false when omitted."})
_add("POST /api/cache/config", ("Update complete cache configuration", "Cập nhật cấu hình cache", "更新完整缓存配置"),
     ("Accepts optional enabled, timeout (seconds), base_url. Omitted/null values preserve settings through the persistence layer. timeout is converted to an integer and must be >=0, otherwise HTTP 400. Saves, hot-reloads settings and refreshes cleanup timing; returns success/message. Use base_url for externally reachable generated-file links.",
      "Nhận enabled, timeout (giây), base_url tùy chọn. Giá trị thiếu/null giữ cấu hình qua lớp lưu. timeout chuyển sang số nguyên và phải >=0, nếu sai trả HTTP 400. Lưu, áp dụng ngay và làm mới lịch dọn; trả success/message. Dùng base_url để liên kết tệp tạo truy cập được từ ngoài.",
      "接受可选 enabled、timeout（秒）、base_url，省略/null 由持久化层保留原设置。timeout 会转换为整数且必须 >=0，否则 HTTP 400。保存并立即刷新配置和清理时间，返回 success/message。base_url 用于生成外部可访问的文件链接。"),
     body={"enabled": True, "timeout": 7200, "base_url": "https://<PUBLIC_FLOW2API_HOST>"}, fields={"enabled": "Optional boolean; omitted/null preserves saved value.", "timeout": "Optional integer seconds >=0; conversion or negative values cause HTTP 400.", "base_url": "Optional generated-file public base URL; empty string clears explicit base URL."})
_add("POST /api/cache/base-url", ("Set the generated media public base URL", "Đặt URL công khai của media", "设置生成媒体公开基地址"),
     ("Updates only base_url (default empty string), reloads config and refreshes cleanup task. Returns success/message. Sending {} clears the explicit base URL; include the external scheme/host/port used by consumers when setting it.",
      "Chỉ đổi base_url (mặc định chuỗi rỗng), nạp lại cấu hình và làm mới tác vụ dọn. Trả success/message. Gửi {} xóa URL chỉ định; khi đặt, dùng scheme/host/cổng mà máy khách truy cập.",
      "仅更新 base_url（默认空字符串），重载配置并刷新清理任务。返回 success/message。发送 {} 会清除显式基地址；设置时应使用客户端实际访问的协议、主机及端口。"), body={"base_url": "https://<PUBLIC_FLOW2API_HOST>"}, fields={"base_url": "String; defaults empty, clearing the explicit URL."})

_CAPTCHA_BODY = {
    "captcha_method": "personal", "yescaptcha_api_key": "<OPTIONAL_YESCAPTCHA_KEY>",
    "yescaptcha_base_url": "https://<YESCAPTCHA_HOST>", "yescaptcha_task_type": "RecaptchaV3TaskProxylessM1S9",
    "capmonster_api_key": "<OPTIONAL_CAPMONSTER_KEY>", "capmonster_base_url": "https://<CAPMONSTER_HOST>",
    "ezcaptcha_api_key": "<OPTIONAL_EZCAPTCHA_KEY>", "ezcaptcha_base_url": "https://<EZCAPTCHA_HOST>",
    "capsolver_api_key": "<OPTIONAL_CAPSOLVER_KEY>", "capsolver_base_url": "https://<CAPSOLVER_HOST>",
    "captcharun_api_key": "<OPTIONAL_CAPTCHARUN_KEY>", "captcharun_base_url": "https://<CAPTCHARUN_HOST>",
    "twocaptcha_api_key": "<OPTIONAL_2CAPTCHA_KEY>", "twocaptcha_base_url": "https://<2CAPTCHA_HOST>",
    "remote_browser_base_url": "https://<REMOTE_BROWSER_HOST>", "remote_browser_api_key": "<OPTIONAL_REMOTE_BROWSER_KEY>",
    "remote_browser_timeout": 60, "browser_proxy_enabled": False, "browser_proxy_url": "<OPTIONAL_BROWSER_PROXY_URL>",
    "browser_count": 1, "personal_project_pool_size": 4, "personal_max_resident_tabs": 5,
    "browser_personal_fresh_restart_every_n_solves": 10, "personal_idle_tab_ttl_seconds": 600,
}
_CAPTCHA_FIELDS = {
    "captcha_method": "Supported operational modes: yescaptcha, flow2api_team, captcharun, twocaptcha, capmonster, ezcaptcha, capsolver, browser, personal, remote_browser, extension. Lowercased; empty/missing becomes yescaptcha. Unknown strings are not rejected here and can fail during solving.",
    "yescaptcha_task_type": "One of RecaptchaV3TaskProxyless, RecaptchaV3TaskProxylessM1, RecaptchaV3TaskProxylessM1S7, RecaptchaV3TaskProxylessM1S9; invalid/missing falls back to M1S9 (0.9).",
    "remote_browser_timeout": "Integer seconds, default 60, minimum 5; invalid integer returns success=false.",
    "remote_browser_base_url": "HTTP(S) base URL; required nonempty in remote_browser mode.",
    "remote_browser_api_key": "String API key for remote service; required nonempty in remote_browser mode; distinct from local API key.",
    "browser_proxy_enabled": "Boolean, defaults false on each call; disabled passes None for proxy URL.",
    "browser_proxy_url": "Defaults empty; when enabled/nonempty requires http/https/socks5/socks5h host:port, optional user:password; bare host:port is accepted by local validation.",
    "browser_count": "Integer browser slots; default 1, clamped 1–20.",
    "personal_project_pool_size": "Optional integer; persisted range clamped 1–50; retained if omitted.",
    "personal_max_resident_tabs": "Optional integer; persisted range clamped 1–50; retained if omitted.",
    "browser_personal_fresh_restart_every_n_solves": "Integer >=0; default 10 on each call; 0 disables restart after solve count.",
    "personal_idle_tab_ttl_seconds": "Optional integer seconds; persisted minimum 60; retained if omitted.",
    "twocaptcha_base_url": "Optional HTTP(S) string; blank normalizes to provider default, invalid type/URL returns success=false.",
    "twocaptcha_api_key": "Optional string; invalid type returns success=false.",
}
for _provider in ("yescaptcha", "capmonster", "ezcaptcha", "capsolver", "captcharun"):
    _CAPTCHA_FIELDS[f"{_provider}_api_key"] = "Optional provider credential string; omitted preserves saved value. Use your own key only for the selected provider."
    _CAPTCHA_FIELDS[f"{_provider}_base_url"] = "Optional provider service base URL; omitted preserves saved value."
_add("POST /api/captcha/config", ("Configure CAPTCHA provider and browser runtime", "Cấu hình CAPTCHA và môi trường trình duyệt", "配置 CAPTCHA 服务与浏览器环境"),
     ("Configures API providers, extension, local browser/personal or remote_browser modes. The example lists every accepted dictionary field; replace only fields needed for your selected mode and omit unused provider placeholders. This is not a pure partial update: missing captcha_method normalizes to yescaptcha; browser_proxy_enabled/count/remote timeout/restart count have per-call defaults. Provider keys/base URLs and optional personal pool settings can be retained when omitted. Team service address/key/task type are fixed in code, not writable request fields. remote_browser requires its base URL and key in this request. Returns success/message plus runtime_prepare_started/runtime_prepare_message/runtime_status_method. Browser/personal preparation runs in the background; poll runtime-status instead of treating save success as runtime readiness. Many validation failures return HTTP 200 with success=false. Inspect both body and status.",
      "Cấu hình nhà cung cấp API, extension, browser/personal cục bộ hoặc remote_browser. Ví dụ liệt kê mọi trường dictionary được nhận; chỉ thay trường cần cho chế độ chọn và bỏ giữ chỗ nhà cung cấp không dùng. Đây không phải cập nhật từng phần thuần túy: thiếu captcha_method sẽ thành yescaptcha; browser_proxy_enabled/count, timeout từ xa và số lần giải trước khởi động lại có mặc định mỗi lần gọi. Khóa/URL nhà cung cấp và cấu hình pool personal tùy chọn có thể giữ khi bỏ qua. Địa chỉ/khóa/loại tác vụ dịch vụ nhóm cố định trong mã, không ghi bằng body. remote_browser yêu cầu URL và khóa trong yêu cầu này. Trả success/message cùng runtime_prepare_started/runtime_prepare_message/runtime_status_method. Chuẩn bị browser/personal chạy nền; thăm dò runtime-status, không coi lưu thành công là sẵn sàng. Nhiều lỗi trả HTTP 200 và success=false, cần đọc cả hai.",
      "配置 API 服务、extension、本地 browser/personal 或 remote_browser 模式。示例列出全部字典请求字段；按所选模式填写需要的字段并省略无关服务占位值。此接口不是纯局部更新：缺失 captcha_method 会变成 yescaptcha；browser_proxy_enabled/count、远程超时和重启计数每次调用都有默认值。省略服务密钥/地址及可选 personal 池设置可保留原值。团队服务地址、密钥和任务类型固定在代码中，不能通过请求修改。remote_browser 要求本次请求中提供地址与密钥。返回 success/message 及 runtime_prepare_started/runtime_prepare_message/runtime_status_method。browser/personal 环境准备在后台执行，应轮询 runtime-status，保存成功不代表运行环境已就绪。许多校验失败返回 HTTP 200、success=false，需同时检查正文和状态。"), body=_CAPTCHA_BODY, fields=_CAPTCHA_FIELDS)
_add("GET /api/captcha/config", ("Read CAPTCHA provider configuration", "Đọc cấu hình nhà cung cấp CAPTCHA", "读取 CAPTCHA 服务配置"),
     ("Returns flat provider credentials/base URLs, method, browser/proxy/personal runtime settings and fixed team-service information. Saved provider API keys and the remote-browser key are returned as configured; only the fixed team key is masked. This endpoint is privileged and its payload must not be copied into public examples. Read before editing to preserve fields with per-call defaults.",
      "Trả dạng phẳng khóa/URL nhà cung cấp, chế độ, cấu hình browser/proxy/personal và thông tin dịch vụ nhóm cố định. Khóa nhà cung cấp và khóa trình duyệt từ xa được trả đúng cấu hình; chỉ khóa nhóm cố định được che. Dữ liệu đặc quyền, không sao chép vào ví dụ công khai. Đọc trước khi sửa để giữ các trường có mặc định mỗi lần gọi.",
      "直接返回服务凭据/基地址、模式、浏览器/代理/personal 设置及固定团队服务信息。已保存的服务 API Key 和远程浏览器密钥按配置原样返回，仅固定团队密钥被脱敏。此响应属于管理数据，不应复制进公共示例。编辑前读取配置，有助于保留具有调用默认值的字段。"))
_add("GET /api/captcha/runtime-status", ("Poll local browser runtime readiness", "Thăm dò môi trường trình duyệt", "轮询本地浏览器环境状态"),
     ("method defaults browser and must be browser or personal (case-insensitive after trimming), otherwise HTTP 400. Returns preparation state/progress/messages plus method and task_running. This only inspects an existing background preparation task; it does not install or launch a runtime by itself. Start preparation by saving the relevant CAPTCHA mode.",
      "method mặc định browser và phải browser hoặc personal (sau bỏ khoảng trắng/chuyển chữ thường), nếu khác HTTP 400. Trả trạng thái/tiến độ/thông báo chuẩn bị cùng method, task_running. Chỉ xem tác vụ nền hiện có, không tự cài/chạy môi trường. Bắt đầu chuẩn bị bằng cách lưu chế độ CAPTCHA tương ứng.",
      "method 默认 browser，去空格转小写后必须为 browser 或 personal，否则 HTTP 400。返回准备状态/进度/消息及 method、task_running。仅检查已有后台准备任务，不会自行安装或启动环境；保存对应 CAPTCHA 模式可开始准备。"), query={"method": "personal"})
_add("GET /api/captcha/browser-stats", ("Inspect existing headed-browser slots", "Xem các phiên browser hiện có", "查看现有有头浏览器槽位"),
     ("Inspects existing browser-mode service without initializing it. Returns captcha_method/running/browsers and service statistics when already instantiated. Other CAPTCHA modes or an unstarted browser service return running=false and browsers=[]. It does not report personal-mode tabs or prove provider health.",
      "Xem dịch vụ chế độ browser hiện có mà không khởi tạo. Trả captcha_method/running/browsers và thống kê khi đã tạo phiên. Chế độ khác hoặc browser chưa chạy trả running=false, browsers=[]. Không báo tab personal hay chứng minh sức khỏe nhà cung cấp.",
      "检查已有 browser 模式服务，不会初始化它。已实例化时返回 captcha_method/running/browsers 及服务统计；其他模式或尚未启动时返回 running=false、browsers=[]。不展示 personal 标签页，也不能证明服务健康。"))
_add("POST /api/captcha/score-test", ("Run a live CAPTCHA score diagnostic", "Chạy chẩn đoán điểm CAPTCHA thực", "执行实时 CAPTCHA 分数诊断"),
     ("Optional body selects website_url/website_key/action/verify_url/enterprise. An omitted body uses model defaults (Flow homepage, homepage action, configured public site key, antcpt verification endpoint, enterprise=false); explicit null values can trigger different fallback target values in the handler. The currently configured CAPTCHA method solves a real challenge and can consume provider credit or start browser work. Result includes success/message, token_acquired, a masked token_preview, timing, verify_http_status/verify_result/score and fingerprint/proxy/request metadata where available. success reflects verification, not merely acquiring a token; many failures return HTTP 200 success=false. Browser/personal verification may happen in-page; remote_browser delegates to remote service. This diagnostic score is not a guarantee that Flow generation will succeed, and extension mode may not support the generic score-test target.",
      "Body tùy chọn gồm website_url/website_key/action/verify_url/enterprise. Bỏ body dùng mặc định model (trang Flow, action homepage, site key công khai cấu hình, xác minh antcpt, enterprise=false); giá trị null tường minh có thể kích hoạt đích dự phòng khác trong hàm xử lý. Chế độ CAPTCHA hiện tại giải thử thách thật, có thể tốn số dư hoặc chạy trình duyệt. Trả success/message, token_acquired, token_preview đã che, thời gian, verify_http_status/verify_result/score và fingerprint/proxy/request khi có. success là kết quả xác minh chứ không chỉ lấy token; nhiều lỗi trả HTTP 200 success=false. Browser/personal có thể xác minh trong trang; remote_browser gọi dịch vụ từ xa. Điểm này không bảo đảm tạo Flow thành công; extension có thể không hỗ trợ đích thử điểm chung.",
      "可选正文指定 website_url/website_key/action/verify_url/enterprise。省略正文使用模型默认值（Flow 首页、homepage 动作、配置的公开站点密钥、antcpt 验证地址、enterprise=false）；显式 null 可能触发处理器中不同的回退目标。当前 CAPTCHA 模式会实际求解，可能消耗服务余额或执行浏览器工作。返回 success/message、token_acquired、脱敏 token_preview、耗时、verify_http_status/verify_result/score，以及可用的指纹/代理/请求元数据。success 表示验证成功，而非仅取得 token；许多失败仍返回 HTTP 200、success=false。browser/personal 可能在页面内验证，remote_browser 委托远程服务。诊断分数不保证 Flow 生成成功，extension 模式也未必支持通用分数测试目标。"),
     body={"website_url": "https://<AUTHORIZED_TEST_SITE>/", "website_key": "<PUBLIC_RECAPTCHA_SITE_KEY>", "action": "<PAGE_ACTION>", "verify_url": "https://<AUTHORIZED_VERIFY_HOST>/<VERIFY_PATH>", "enterprise": False})

_add("GET /api/plugin/config", ("Read Token Updater connection settings", "Đọc cấu hình kết nối Token Updater", "读取 Token Updater 连接配置"),
     ("Returns success/config with connection_token, connection_url and auto_enable_on_update. The URL points to /api/plugin/update-token and uses the request host/scheme, honoring first x-forwarded-host and valid x-forwarded-proto values. Configure trusted proxy forwarding to obtain the externally usable URL. The returned token authenticates plugin sync/check calls and is separate from CAPTCHA WebSocket/API keys.",
      "Trả success/config gồm connection_token, connection_url, auto_enable_on_update. URL trỏ /api/plugin/update-token theo host/scheme yêu cầu, dùng giá trị đầu x-forwarded-host và x-forwarded-proto hợp lệ. Cấu hình chuyển tiếp proxy tin cậy để có URL ngoài dùng được. Token xác thực đồng bộ/kiểm tra plugin, khác WebSocket CAPTCHA/khóa API.",
      "返回 success/config，含 connection_token、connection_url、auto_enable_on_update。URL 指向 /api/plugin/update-token，按请求主机/协议构造，并使用首个 x-forwarded-host 和有效 x-forwarded-proto。应正确配置可信反向代理转发以得到外部可用地址。此令牌用于插件同步/检查，与 CAPTCHA WebSocket/API Key 不同。"))
_add("POST /api/plugin/config", ("Configure or rotate plugin sync credentials", "Cấu hình/đổi thông tin đồng bộ plugin", "配置或更换插件同步凭据"),
     ("Accepts connection_token (default empty) and auto_enable_on_update (default true). An empty/omitted token generates a new random connection token; {} therefore rotates the credential and resets auto-enable to true. Returns success/message/connection_token/auto_enable_on_update. Reconfigure external Token Updater clients after rotation. This token does not authorize model generation or /captcha_ws.",
      "Nhận connection_token (mặc định rỗng), auto_enable_on_update (mặc định true). Token rỗng/thiếu tạo token kết nối ngẫu nhiên mới; vì vậy {} đổi token và đặt lại tự bật thành true. Trả success/message/connection_token/auto_enable_on_update. Cập nhật Token Updater ngoài sau khi đổi. Token không cấp quyền tạo model hoặc /captcha_ws.",
      "接受 connection_token（默认空）和 auto_enable_on_update（默认 true）。空/省略令牌会生成随机新令牌，因此 {} 会轮换凭据并将自动启用恢复为 true。返回 success/message/connection_token/auto_enable_on_update。更换后需更新外部 Token Updater 客户端；此令牌不能用于模型生成或 /captcha_ws。"),
     body={"connection_token": "<PLUGIN_CONNECTION_TOKEN_OR_EMPTY_TO_GENERATE>", "auto_enable_on_update": True}, fields={"connection_token": "String; missing/empty generates and saves a fresh random token.", "auto_enable_on_update": "Boolean; defaults true on each call; controls re-enabling updated existing accounts."})
_add("POST /api/plugin/update-token", ("Sync validated cookies from Token Updater", "Đồng bộ cookie đã xác minh từ Token Updater", "从 Token Updater 同步已验证 Cookie"),
     ("Token Updater 1.3+ payload requires full google_cookies (1–524288 characters), optional login_account email and protocol_mode=protocol. Unknown body fields are forbidden. Validates cookies first (HTTP 400 on failure), then finds an existing account by email or cookie-session hash; omitted identity can reuse a matching account or a placeholder email. Updates existing credentials or adds an account with automatic refresh and a 30-minute interval. Existing disabled accounts may be re-enabled according to plugin configuration. Returns success/message/action=updated or added; added includes token_id and an auto-enabled update can include auto_enabled=true. Persistence failures return HTTP 500. Does not accept legacy raw ST/AT-only payloads.",
      "Payload Token Updater 1.3+ bắt buộc google_cookies đầy đủ (1–524288 ký tự), login_account email tùy chọn, protocol_mode=protocol. Cấm trường body không khai báo. Xác minh cookie trước (lỗi HTTP 400), tìm tài khoản theo email hoặc hash phiên cookie; thiếu danh tính có thể dùng tài khoản khớp hoặc email tạm. Cập nhật thông tin hoặc thêm tài khoản tự làm mới chu kỳ 30 phút. Tài khoản tắt có thể tự bật theo cấu hình plugin. Trả success/message/action=updated hoặc added; added có token_id, cập nhật tự bật có thể có auto_enabled=true. Lỗi lưu trả HTTP 500. Không nhận payload cũ chỉ ST/AT thuần.",
      "Token Updater 1.3+ 请求必填完整 google_cookies（1–524288 字符），可选 login_account 邮箱及 protocol_mode=protocol，禁止未声明字段。先验证 Cookie（失败 HTTP 400），再按邮箱或 Cookie 会话哈希查找已有账号；省略身份时可复用匹配账号或生成占位邮箱。更新凭据或新增自动刷新、间隔 30 分钟的账号。已有停用账号可按插件配置自动启用。返回 success/message/action=updated 或 added；新增含 token_id，自动启用更新可含 auto_enabled=true。保存失败返回 HTTP 500。不接受旧版纯 ST/AT 请求。"), auth="plugin",
     body={"google_cookies": "<FULL_GOOGLE_FLOW_COOKIE_STRING>", "login_account": "account@example.com", "protocol_mode": "protocol"})
_add("POST /api/plugin/check-tokens", ("Check account status for external syncers", "Kiểm tra trạng thái cho bộ đồng bộ", "供外部同步器检查账号状态"),
     ("Optional body may include emails:[...] for a trimmed, case-insensitive filter. Omitted body, non-list emails or an empty effective filter returns every account. Returns success/tokens with id,email,is_active,needs_refresh,at_expires,last_used_at,protocol_mode,auto_refresh_enabled,refresh_interval_minutes,last_st_refresh_at,last_st_refresh_result and credits. No raw cookies/access credentials are included in this status response. Use needs_refresh to decide which account to resync; the endpoint itself does not refresh credentials.",
      "Body tùy chọn có emails:[...] để lọc sau bỏ khoảng trắng, không phân biệt hoa thường. Bỏ body, emails không phải danh sách hoặc bộ lọc rỗng sẽ trả mọi tài khoản. Trả success/tokens với id,email,is_active,needs_refresh,at_expires,last_used_at,protocol_mode,auto_refresh_enabled,refresh_interval_minutes,last_st_refresh_at,last_st_refresh_result,credits. Phản hồi trạng thái không chứa cookie/thông tin truy cập thô. Dùng needs_refresh chọn tài khoản cần đồng bộ; đường dẫn không tự làm mới.",
      "可选正文提供 emails:[...]，按去空格、忽略大小写的邮箱筛选。省略正文、emails 非列表或有效筛选为空时返回全部账号。返回 success/tokens，含 id,email,is_active,needs_refresh,at_expires,last_used_at,protocol_mode,auto_refresh_enabled,refresh_interval_minutes,last_st_refresh_at,last_st_refresh_result,credits，不含原始 Cookie/访问凭据。可根据 needs_refresh 决定重新同步哪些账号，接口本身不执行刷新。"), auth="plugin", body={"emails": ["<ACCOUNT_EMAIL>"]}, fields={"emails": "Optional array of email strings; empty/missing/non-list means no filter and returns all accounts."})

_add("GET /v1/models", ("List OpenAI-style concrete model IDs", "Liệt kê model cụ thể dạng OpenAI", "列出 OpenAI 格式具体模型"),
     ("Returns object=list and data entries with id/object/owned_by/description. Discover concrete IDs from the running service rather than hard-coding upstream names. These are image/video generation routes exposed through a chat-shaped API, not a general conversational LLM catalog. Simplified aliases have a separate endpoint.",
      "Trả object=list và data gồm id/object/owned_by/description. Lấy ID cụ thể từ dịch vụ đang chạy thay vì cố định tên upstream. Đây là tạo ảnh/video qua API dạng chat, không phải danh mục LLM hội thoại chung. Bí danh đơn giản có đường dẫn riêng.",
      "返回 object=list 与 data，条目含 id/object/owned_by/description。应从运行中的服务发现具体 ID，而不是写死上游名称。这些是通过聊天格式暴露的图像/视频生成模型，并非通用对话 LLM 目录。简化别名有独立接口。"), auth="api")
_add("GET /v1/models/aliases", ("List simplified model aliases", "Liệt kê bí danh model đơn giản", "列出简化模型别名"),
     ("Returns an OpenAI-style list of base alias IDs with descriptions and is_alias=true. Use an alias with supported generationConfig options to resolve a concrete model; consult model capability notes for valid aspect ratio, resolution and mode combinations. Listing aliases does not perform generation.",
      "Trả danh sách dạng OpenAI gồm bí danh gốc, mô tả và is_alias=true. Dùng bí danh với generationConfig được hỗ trợ để chọn model cụ thể; xem khả năng model cho tổ hợp tỷ lệ, độ phân giải, chế độ hợp lệ. Liệt kê không tạo nội dung.",
      "返回 OpenAI 格式的基础别名列表，含描述与 is_alias=true。可结合支持的 generationConfig 选项解析为具体模型；有效宽高比、分辨率及模式组合应参考模型能力说明。列出别名不执行生成。"), auth="api")
_add(["GET /v1beta/models", "GET /models"], ("List Gemini-compatible models", "Liệt kê model tương thích Gemini", "列出 Gemini 兼容模型"),
     ("Both paths return {models:[...]} using Gemini model resource shapes, including names and supported generation methods. Includes the service's concrete models and simplified aliases. Use the model portion of the returned name in generateContent/streamGenerateContent URLs.",
      "Hai đường dẫn trả {models:[...]} theo tài nguyên model Gemini, gồm tên và phương thức tạo hỗ trợ. Bao gồm model cụ thể và bí danh đơn giản của dịch vụ. Dùng phần model trong tên trả về cho URL generateContent/streamGenerateContent.",
      "两个路径返回 {models:[...]}，使用 Gemini 模型资源格式，含名称和支持的生成方法，包括本服务具体模型与简化别名。生成 URL 中使用返回名称中的模型部分。"), auth="api")
_add(["GET /v1beta/models/{model}", "GET /models/{model}"],
     ("Inspect one Gemini-compatible model", "Xem một model tương thích Gemini", "查看单个 Gemini 兼容模型"),
     ("Looks up the model ID in the local catalog and returns a Gemini model resource. Unknown IDs return HTTP 404 with Gemini-style error {code,message,status}. This does not query Google directly or verify that an eligible account currently has generation capacity.",
      "Tra ID model trong danh mục cục bộ và trả tài nguyên Gemini. ID không biết trả HTTP 404 với lỗi dạng Gemini {code,message,status}. Không truy vấn Google trực tiếp hoặc xác minh tài khoản có dung lượng tạo hiện tại.",
      "在本地目录查找 model ID 并返回 Gemini 模型资源。未知 ID 返回 HTTP 404 与 Gemini 风格 {code,message,status} 错误。不会直接查询 Google，也不验证当前账号是否具有生成容量。"), auth="api")
_add("POST /v1/chat/completions", ("Generate images or videos through OpenAI chat format", "Tạo ảnh/video theo định dạng chat OpenAI", "通过 OpenAI 聊天格式生成图像或视频"),
     ("Unified image/video generation endpoint. model chooses the capability; text and image parts are normalized from messages, with additional supported top-level reference-image fields and generationConfig options defined by the request schema. Supply a nonempty prompt (otherwise HTTP 400). stream=false collects a final OpenAI-style result; stream=true returns SSE deltas and completion framing, so use a streaming parser and allow long-lived connections. This service does not implement general chat reasoning, tool execution or every OpenAI parameter. Upstream/model/account errors may appear in generated result/error payloads; after an SSE response starts, inspect events for failure rather than relying on the initial HTTP 200. Nonstream results expose generated media through the handler's content/media fields, not an Images API data array. Use reference images only with compatible model modes.",
      "Đường dẫn tạo ảnh/video chung. model chọn khả năng; phần văn bản/ảnh được chuẩn hóa từ messages, cùng trường ảnh tham chiếu cấp cao và generationConfig được schema hỗ trợ. Prompt phải không rỗng (nếu không HTTP 400). stream=false gom kết quả dạng OpenAI; stream=true trả delta SSE và khung kết thúc, cần bộ đọc luồng và kết nối dài. Không triển khai suy luận chat chung, thực thi công cụ hay mọi tham số OpenAI. Lỗi upstream/model/tài khoản có thể nằm trong payload lỗi; sau khi SSE bắt đầu phải kiểm tra sự kiện thay vì chỉ HTTP 200 ban đầu. Kết quả không luồng cung cấp media qua content/trường media của handler, không phải mảng data Images API. Chỉ dùng ảnh tham chiếu với chế độ model tương thích.",
      "统一图像/视频生成接口。model 决定能力，messages 中的文字/图像部分会被规范化，同时支持请求模型定义的顶层参考图字段和 generationConfig。提示词不能为空，否则 HTTP 400。stream=false 收集最终 OpenAI 格式结果；stream=true 返回 SSE delta 和结束标记，需使用流式解析并允许长连接。并不实现通用聊天推理、工具执行或全部 OpenAI 参数。上游/模型/账号错误可能出现在结果错误正文；SSE 开始后应检查事件中的错误，不能只看初始 HTTP 200。非流式结果通过处理器的 content/媒体字段提供输出，不是 Images API 的 data 数组。参考图应与模型模式兼容。"), auth="api",
     body={"model": "<MODEL_ID_OR_ALIAS_FROM_CATALOG>", "messages": [{"role": "user", "content": "<GENERATION_PROMPT>"}], "stream": False})
_add(["POST /v1beta/models/{model}:generateContent", "POST /models/{model}:generateContent"],
     ("Generate media with Gemini contents", "Tạo media với contents Gemini", "使用 Gemini contents 生成媒体"),
     ("Both paths normalize Gemini contents (text plus supported inlineData/fileData reference images) and generationConfig into the same image/video generation pipeline. model is supplied in the URL. Empty prompts return HTTP 400 in Gemini error format. Returns candidates/content/parts and modelVersion; generated image data can be represented as inlineData and video output as fileData/direct URL metadata according to output conversion. Handler and normalization failures are translated into Gemini {error:{code,message,status}} responses. Compatibility is limited to implemented image/video behavior; unsupported general Gemini features are not promised. Keep client timeout long enough for generation and use a supported alias/config combination.",
      "Hai đường dẫn chuẩn hóa contents Gemini (text cùng ảnh tham chiếu inlineData/fileData được hỗ trợ) và generationConfig vào cùng luồng tạo ảnh/video. model đặt trong URL. Prompt rỗng trả HTTP 400 dạng lỗi Gemini. Trả candidates/content/parts, modelVersion; ảnh có thể biểu diễn inlineData và video fileData/metadata URL trực tiếp theo chuyển đổi đầu ra. Lỗi handler/chuẩn hóa đổi thành {error:{code,message,status}} Gemini. Tương thích giới hạn ở hành vi ảnh/video đã triển khai, không bảo đảm tính năng Gemini chung. Đặt timeout đủ dài và dùng tổ hợp bí danh/cấu hình được hỗ trợ.",
      "两个路径将 Gemini contents（文字及支持的 inlineData/fileData 参考图）和 generationConfig 规范化后送入同一图像/视频生成流程，model 放在 URL 中。空提示词返回 Gemini 格式 HTTP 400。返回 candidates/content/parts、modelVersion；按输出转换，图像可为 inlineData，视频可为 fileData/直链元数据。处理器和规范化错误转换为 Gemini {error:{code,message,status}}。兼容范围限于已实现的图像/视频行为，不承诺通用 Gemini 功能。客户端应设置足够长的超时，并使用支持的别名/配置组合。"), auth="api",
     body={"contents": [{"role": "user", "parts": [{"text": "<GENERATION_PROMPT>"}]}], "generationConfig": {"responseModalities": ["IMAGE"]}})
_add(["POST /v1beta/models/{model}:streamGenerateContent", "POST /models/{model}:streamGenerateContent"],
     ("Stream Gemini-compatible generation events", "Nhận sự kiện tạo dạng Gemini", "流式接收 Gemini 兼容生成事件"),
     ("Both paths accept the same Gemini body as generateContent and always return text/event-stream. alt is accepted for SDK compatibility (commonly alt=sse), but is not used to switch transport. Events convert the generation stream into Gemini-style candidates/errors, with final media conversion when output is available. Validate prompt/model/reference images before starting; pre-stream normalization errors use Gemini JSON error responses, while in-stream errors must be handled from SSE. A streaming connection does not provide a resumable job ID or separate status-poll endpoint.",
      "Hai đường dẫn nhận cùng body Gemini như generateContent và luôn trả text/event-stream. alt được nhận để tương thích SDK (thường alt=sse) nhưng không đổi phương thức truyền. Sự kiện chuyển luồng thành candidates/lỗi dạng Gemini và chuyển media cuối khi có. Xác minh prompt/model/ảnh trước khi bắt đầu; lỗi chuẩn hóa trước luồng dùng JSON Gemini, lỗi trong luồng cần đọc SSE. Kết nối luồng không cung cấp ID tác vụ tiếp tục hay đường dẫn thăm dò riêng.",
      "两个路径接受与 generateContent 相同的 Gemini 正文，并始终返回 text/event-stream。alt 为 SDK 兼容而接受（通常 alt=sse），不会用于切换传输格式。事件将生成流转换为 Gemini candidates/错误，并在输出可用时转换最终媒体。应在启动前验证提示词、模型和参考图；流开始前的规范化错误用 Gemini JSON 返回，流中错误应从 SSE 处理。流式连接不提供可恢复任务 ID 或独立状态轮询接口。"), auth="api", query={"alt": "sse"},
     body={"contents": [{"role": "user", "parts": [{"text": "<GENERATION_PROMPT>"}]}], "generationConfig": {"responseModalities": ["IMAGE"]}})
_add("WEBSOCKET /captcha_ws", ("Connect a CAPTCHA extension worker", "Kết nối worker extension CAPTCHA", "连接 CAPTCHA 扩展工作端"),
     ("WebSocket control channel for extension CAPTCHA mode, not a generation REST endpoint. Authenticate with the GENERATION API key in ?key=, ?api_key=, x-goog-api-key, or Authorization: Bearer; a Bearer header overrides the other sources. Missing/invalid credentials close with code 1008 before accept. Optional route_key/client_label query parameters identify a browser/account route. Client may send JSON {type:'register',route_key,client_label}; server replies register_ack. Server sends {type:'get_token',req_id,action,project_id,route_key}; the owning socket replies with the same req_id, status:'success',token:<captcha token>, or a failure status/error. Responses from another socket are ignored. Route matching is exact: an empty account route only uses an empty extension route, never borrows a keyed worker. Requests have an internal timeout (default service timeout 20 seconds); disconnected/unmatched workers fail generation. Plugin connection_token does not authenticate this channel.",
      "Kênh điều khiển WebSocket cho chế độ CAPTCHA extension, không phải REST tạo nội dung. Xác thực bằng khóa API TẠO NỘI DUNG trong ?key=, ?api_key=, x-goog-api-key hoặc Authorization: Bearer; header Bearer ghi đè nguồn khác. Thiếu/sai khóa đóng mã 1008 trước accept. Query route_key/client_label tùy chọn nhận diện tuyến trình duyệt/tài khoản. Máy khách gửi JSON {type:'register',route_key,client_label}, máy chủ trả register_ack. Máy chủ gửi {type:'get_token',req_id,action,project_id,route_key}; socket sở hữu trả cùng req_id, status:'success',token:<captcha token> hoặc trạng thái lỗi/error. Bỏ phản hồi từ socket khác. Tuyến phải khớp chính xác: tuyến tài khoản rỗng chỉ dùng extension tuyến rỗng, không mượn worker có khóa. Yêu cầu có timeout nội bộ (mặc định dịch vụ 20 giây); worker ngắt/không khớp làm tạo thất bại. connection_token plugin không xác thực kênh này.",
      "extension CAPTCHA 模式的 WebSocket 控制通道，不是生成 REST 接口。通过 ?key=、?api_key=、x-goog-api-key 或 Authorization: Bearer 提供生成 API Key；Bearer 头会覆盖其他来源。缺失/错误密钥在接受连接前以 1008 关闭。可选 route_key/client_label 查询参数标识浏览器/账号路由。客户端可发送 JSON {type:'register',route_key,client_label}，服务端回复 register_ack。服务端发送 {type:'get_token',req_id,action,project_id,route_key}；拥有该请求的套接字使用相同 req_id 回复 status:'success',token:<captcha token>，或失败状态/error。其他套接字的响应会被忽略。路由精确匹配：空账号路由只能使用空扩展路由，不会借用有键工作端。请求具有内部超时（服务默认 20 秒）；断线或路由不匹配会使生成失败。插件 connection_token 不能认证此通道。"), auth=None,
     query={"key": "<GENERATION_API_KEY>", "route_key": "<OPTIONAL_ACCOUNT_ROUTE_KEY>", "client_label": "<OPTIONAL_WORKER_LABEL>"})

_add(["GET /", "GET /login"], ("Open the admin login page", "Mở trang đăng nhập quản trị", "打开管理登录页"),
     ("Public HTML login UI; / serves the login document directly rather than performing an HTTP redirect. A missing frontend document returns HTTP 404. Use /api/admin/login or /api/login for programmatic authentication.",
      "Giao diện HTML đăng nhập công khai; / phục vụ tài liệu đăng nhập trực tiếp, không chuyển hướng HTTP. Thiếu tài liệu frontend trả HTTP 404. Dùng /api/admin/login hoặc /api/login để xác thực bằng chương trình.",
      "公开 HTML 登录界面；/ 直接提供登录文档，而非执行 HTTP 重定向。缺少前端文件时返回 HTTP 404。程序化认证使用 /api/admin/login 或 /api/login。"), auth=None)
_add("GET /manage", ("Open the management console", "Mở bảng quản trị", "打开管理控制台"),
     ("HTML console guarded specifically by a valid admin_session cookie. Without a live cookie session it redirects to /login with HTTP 302; a Bearer header alone does not satisfy this page guard. The page's management APIs independently accept admin cookie/Bearer authentication. Missing frontend HTML returns HTTP 404 after the session check.",
      "Bảng HTML được bảo vệ riêng bằng cookie admin_session hợp lệ. Không có phiên cookie sống sẽ chuyển /login HTTP 302; chỉ header Bearer không đủ qua bảo vệ trang. API quản trị của trang nhận cookie/Bearer riêng. Thiếu HTML trả HTTP 404 sau kiểm tra phiên.",
      "HTML 控制台页面专门校验有效 admin_session Cookie。没有有效 Cookie 会话时以 HTTP 302 跳转 /login，仅 Bearer 头不能通过页面检查。页面调用的管理 API 则分别支持管理 Cookie/Bearer。通过会话检查后若缺少 HTML 文件则返回 HTTP 404。"), auth=None)
_add("GET /test", ("Open the model testing interface", "Mở giao diện thử model", "打开模型测试界面"),
     ("HTML model-testing UI protected by a live admin_session cookie, with HTTP 302 to /login if missing/expired. A Bearer header alone does not grant page access. Generation requests from the test UI use the configured generation API key. Missing test HTML returns HTTP 404 after authorization.",
      "Giao diện HTML thử model bảo vệ bằng cookie admin_session sống; thiếu/hết hạn chuyển HTTP 302 tới /login. Chỉ Bearer không cấp quyền trang. Yêu cầu tạo từ UI thử dùng khóa API tạo đã cấu hình. Thiếu HTML trả HTTP 404 sau xác thực.",
      "模型测试 HTML 界面，要求有效 admin_session Cookie，缺失/失效时 HTTP 302 跳转 /login。仅 Bearer 头不能访问页面。测试界面的生成请求使用已配置的生成 API Key。授权后若缺少测试 HTML 则返回 HTTP 404。"), auth=None)
_add("GET /static/i18n.js", ("Load interface translations", "Tải bản dịch giao diện", "加载界面翻译"),
     ("Public JavaScript asset for the interface language system, served with no-cache page asset headers and excluded from OpenAPI. It is not a JSON translation API or an authenticated configuration endpoint.",
      "Tệp JavaScript công khai cho ngôn ngữ giao diện, trả header không cache của tài nguyên trang và không nằm OpenAPI. Không phải API bản dịch JSON hay cấu hình có xác thực.",
      "界面语言系统使用的公开 JavaScript 资源，带页面资源无缓存响应头，未列入 OpenAPI。不是 JSON 翻译 API 或认证配置接口。"), auth=None)
_add("GET /static/integration.js", ("Load integration guide interface", "Tải giao diện hướng dẫn tích hợp", "加载集成指南界面"),
     ("Public JavaScript asset powering the integration guide UI, served with no-cache headers and excluded from OpenAPI. This is browser code rather than a generation/configuration API.",
      "Tệp JavaScript công khai vận hành hướng dẫn tích hợp, có header không cache và loại khỏi OpenAPI. Là mã trình duyệt, không phải API tạo/cấu hình.",
      "集成指南界面使用的公开 JavaScript 资源，带无缓存响应头且未列入 OpenAPI。属于浏览器代码，不是生成/配置 API。"), auth=None)

_add("GET /api/integration/reference", ("Read live integration contracts", "Đọc hợp đồng tích hợp hiện tại", "读取实时集成契约"),
     ("Read-only reference generated from the running application's registered routes, request schemas and model registry, enriched with translated operational notes and placeholder examples. Use it to inspect actual endpoint/model availability for this deployment. It contains documentation metadata rather than saved account credentials or configured secrets.",
      "Tài liệu chỉ đọc tạo từ đường dẫn, schema yêu cầu và danh mục model đã đăng ký của ứng dụng đang chạy, bổ sung hướng dẫn đa ngôn ngữ và ví dụ giữ chỗ. Dùng để kiểm tra endpoint/model thực có trong triển khai này. Nội dung là metadata tài liệu, không chứa thông tin tài khoản lưu hoặc bí mật cấu hình.",
      "只读参考资料，根据运行应用已注册路由、请求模型与模型目录生成，并补充翻译说明和占位示例。用于检查当前部署实际可用的接口/模型。内容为文档元数据，不包含已保存账号凭据或配置密钥。"))
_add("GET /static/integration-recipes.js", ("Load integration recipes", "Tải công thức tích hợp", "加载集成示例"),
     ("Public JavaScript documentation asset supplying practical integration workflows and examples. Static placeholder code is not a live account/configuration response. Use the authenticated reference endpoint to inspect the current route/model contract.",
      "Tài nguyên JavaScript công khai cung cấp quy trình và ví dụ tích hợp. Mã giữ chỗ tĩnh không phải phản hồi cấu hình/tài khoản thực. Dùng đường dẫn reference có xác thực để xem hợp đồng route/model hiện tại.",
      "公开 JavaScript 文档资源，提供实用集成流程和示例。静态占位代码不是实时账号/配置响应。检查当前路由/模型契约可使用需认证的参考接口。"), auth=None)

_add("GET /static/managed-browser.js", ("Load managed browser account controls", "Tải điều khiển phiên trình duyệt tài khoản", "加载账号托管浏览器控件"),
     ("Public JavaScript interface asset for the account browser-session dialog. Loading this file or viewing the management page does not launch a login window. Account status and operations use the separately authenticated browser-session endpoints; the asset contains no account cookies, browser profiles or runtime credentials.",
      "Tài nguyên JavaScript công khai cho hộp thoại phiên trình duyệt tài khoản. Tải tệp hoặc xem trang quản trị không tự mở cửa sổ đăng nhập. Trạng thái và thao tác tài khoản dùng các endpoint browser-session có xác thực riêng; tệp không chứa cookie tài khoản, profile trình duyệt hay thông tin xác thực đang dùng.",
      "账号浏览器会话弹窗使用的公开 JavaScript 资源。加载文件或查看管理页面不会自动打开登录窗口。账号状态与操作通过单独认证的 browser-session 接口执行；资源不含账号 Cookie、浏览器 profile 或运行时凭据。"), auth=None)

# Cookie formats are strings inside the outer JSON request, including when the
# string itself contains a serialized browser-cookie JSON export.
_COOKIE_FORMATS = _text(
    " google_cookies is a STRING: either complete semicolon/newline-separated name=value Cookie text, or JSON serialized as a string containing browser-cookie objects (an array, a {cookies:[...]} wrapper, or a single cookie object with name/value and optional scope/attributes). Preserve domain/path/secure metadata when exporting browser cookies. A nested JSON array directly in google_cookies does not satisfy the string schema. A Netscape tab-separated cookies.txt file is not a supported structured import format here. The outer batch format remains {tokens:[...]}; complete Google/Flow cookies are required rather than an isolated legacy session-token value.",
    " google_cookies là CHUỖI: toàn bộ Cookie name=value phân cách chấm phẩy/xuống dòng, hoặc JSON tuần tự hóa thành chuỗi chứa đối tượng cookie trình duyệt (mảng, {cookies:[...]} hoặc một đối tượng name/value có scope/thuộc tính tùy chọn). Giữ domain/path/secure khi xuất cookie. Mảng JSON lồng trực tiếp trong google_cookies không đúng schema chuỗi. Tệp cookies.txt kiểu Netscape phân tách tab không phải dạng nhập có cấu trúc được hỗ trợ ở đây. Lô ngoài vẫn là {tokens:[...]}; cần cookie Google/Flow đầy đủ thay vì một session-token cũ đơn lẻ.",
    " google_cookies 必须为字符串：完整的分号/换行分隔 name=value Cookie 文本，或序列化为字符串的浏览器 Cookie JSON（数组、{cookies:[...]} 包装或单个含 name/value 及可选作用域/属性的对象）。导出时应保留 domain/path/secure 元数据。直接将 JSON 数组放入 google_cookies 不符合字符串模型。此处不支持 Netscape 制表符 cookies.txt 结构导入。外层批量格式仍为 {tokens:[...]}；需要完整 Google/Flow Cookie，而非孤立的旧版会话令牌。",
)
for _key in ("POST /api/tokens", "PUT /api/tokens/{token_id}", "POST /api/tokens/import", "POST /api/tokens/st2at", "POST /api/plugin/update-token"):
    for _language in ("en", "vi", "zh-CN"):
        ENDPOINT_NOTES[_key]["details"][_language] += _COOKIE_FORMATS[_language]


def _response(keys, example):
    for key in keys if isinstance(keys, (tuple, list)) else [keys]:
        ENDPOINT_NOTES[key]["response_example"] = example


# Representative shapes, not real server data. Runtime message/error text stays
# untranslated; placeholders avoid implying that its language is localized.
for _key, _note in ENDPOINT_NOTES.items():
    if _key.startswith(("POST /api/", "PUT /api/", "DELETE /api/")):
        _note["response_example"] = {"success": True, "message": "<RUNTIME_MESSAGE>"}

_response(["POST /api/admin/login", "POST /api/login"], {"success": True, "token": "<ADMIN_SESSION>", "username": "<ADMIN_USERNAME>"})
_response("GET /api/tokens", [{
    "id": 1, "st": "<SAVED_SESSION_IDENTIFIER>", "at": "<SAVED_ACCESS_TOKEN>", "at_expires": "<ISO_8601_TIMESTAMP>",
    "at_expired": False, "at_expiring_within_1h": False, "token": "<SAVED_ACCESS_TOKEN>",
    "email": "<ACCOUNT_EMAIL>", "name": "<ACCOUNT_NAME>", "remark": "<ACCOUNT_LABEL>", "is_active": True,
    "created_at": "<ISO_8601_TIMESTAMP>", "last_used_at": None, "use_count": 0, "credits": 0,
    "user_paygate_tier": "<UPSTREAM_TIER>", "current_project_id": "<FLOW_PROJECT_ID>", "current_project_name": "<PROJECT_NAME>",
    "captcha_proxy_url": "<OPTIONAL_CAPTCHA_PROXY_URL>", "extension_route_key": "<OPTIONAL_ROUTE_KEY>",
    "protocol_mode": "protocol", "google_cookies": "<SAVED_GOOGLE_COOKIES>", "login_account": "<ACCOUNT_EMAIL>",
    "login_password": "<OPTIONAL_SAVED_ACCOUNT_PASSWORD>", "proxy_url": "<OPTIONAL_ACCOUNT_PROXY_URL>",
    "auto_refresh_enabled": True, "refresh_interval_minutes": 30, "last_st_refresh_at": None, "last_st_refresh_result": "",
    "image_enabled": True, "video_enabled": True, "image_concurrency": -1, "video_concurrency": -1,
    "image_count": 0, "video_count": 0, "error_count": 0, "today_error_count": 0, "consecutive_error_count": 0,
    "last_error_at": None, "ban_reason": None, "banned_at": None,
}])
_response("POST /api/tokens", {"success": True, "message": "<RUNTIME_MESSAGE>", "token": {"id": 1, "email": "<ACCOUNT_EMAIL>", "credits": 0, "project_id": "<FLOW_PROJECT_ID>", "project_name": "<PROJECT_NAME>"}})
_response("POST /api/tokens/{token_id}/refresh-credits", {"success": True, "message": "<RUNTIME_MESSAGE>", "credits": 0})
_response("POST /api/tokens/{token_id}/refresh-at", {"success": True, "message": "<RUNTIME_MESSAGE>", "token": {"id": 1, "email": "<ACCOUNT_EMAIL>", "at_expires": "<ISO_8601_TIMESTAMP>"}})
_BROWSER_SESSION_EXAMPLE = {
    "token_id": 1, "enabled": True, "status": "ready", "browser_open": False,
    "last_sync_at": "<ISO_8601_TIMESTAMP>", "error_code": None, "interval_minutes": 30,
}
_response("POST /api/browser-sessions/accounts", {"success": True, "created": True, "session": {**_BROWSER_SESSION_EXAMPLE, "status": "opening", "browser_open": False, "last_sync_at": None}})
_response(["GET /api/tokens/{token_id}/browser-session", "POST /api/tokens/{token_id}/browser-session/sync"], {"success": True, "session": _BROWSER_SESSION_EXAMPLE})
_response("POST /api/tokens/{token_id}/browser-session/login", {"success": True, "session": {**_BROWSER_SESSION_EXAMPLE, "status": "opening", "browser_open": False, "last_sync_at": None}})
_response("POST /api/tokens/{token_id}/browser-session/stop", {"success": True, "session": {**_BROWSER_SESSION_EXAMPLE, "enabled": False, "status": "stopped"}})
_response("POST /api/tokens/st2at", {"success": True, "message": "<RUNTIME_MESSAGE>", "access_token": "<ACCESS_TOKEN>", "email": "<ACCOUNT_EMAIL>", "expires": "<ISO_8601_TIMESTAMP>"})
_response("POST /api/tokens/import", {"success": True, "added": 1, "updated": 0, "errors": None, "message": "<RUNTIME_MESSAGE>"})
_response("GET /api/config/proxy", {"success": True, "config": {"enabled": False, "proxy_url": "", "media_proxy_enabled": False, "media_proxy_url": ""}})
_response("GET /api/proxy/config", {"proxy_enabled": False, "proxy_url": "", "media_proxy_enabled": False, "media_proxy_url": ""})
_response("POST /api/proxy/test", {"success": True, "message": "<RUNTIME_MESSAGE>", "test_url": "https://flow.google.com/", "final_url": "https://<TARGET_HOST>/<PATH>", "status_code": 200, "elapsed_ms": 0})
_response(["GET /api/config/generation", "GET /api/generation/timeout"], {"success": True, "config": {"image_timeout": 300, "video_timeout": 1500, "max_retries": 3}})
_response("GET /api/call-logic/config", {"success": True, "config": {"call_mode": "polling", "polling_mode_enabled": True}})
_response("POST /api/call-logic/config", {"success": True, "message": "<RUNTIME_MESSAGE>", "config": {"call_mode": "polling", "polling_mode_enabled": True}})
_response("GET /api/system/info", {"success": True, "info": {"total_tokens": 0, "active_tokens": 0, "total_credits": 0, "version": "1.0.0"}})
_response("GET /health", {"backend_running": True, "has_active_tokens": False, "total_tokens": 0, "active_tokens": 0, "tokens_missing_at": 0, "tokens_expired": 0, "tokens_expiring_within_1h": 0, "banned_429_tokens": 0, "captcha_method": "<CONFIGURED_METHOD>", "remote_browser_configured": False})
_response("GET /api/stats", {"total_tokens": 0, "active_tokens": 0, "total_images": 0, "total_videos": 0, "total_errors": 0, "today_images": 0, "today_videos": 0, "today_errors": 0})
_LOG_EXAMPLE = {"id": 1, "token_id": 1, "token_email": "<ACCOUNT_EMAIL>", "token_username": "<ACCOUNT_NAME>", "operation": "<OPERATION>", "status_code": 200, "duration": 0, "status_text": "<RUNTIME_STATUS>", "progress": 100, "created_at": "<TIMESTAMP>", "updated_at": "<TIMESTAMP>", "error_summary": ""}
_response("GET /api/logs", [_LOG_EXAMPLE])
_response("GET /api/logs/{log_id}", {**_LOG_EXAMPLE, "request_body": "<SAVED_REQUEST_PAYLOAD>", "response_body": "<SAVED_RESPONSE_PAYLOAD>"})
_response("GET /api/admin/config", {"admin_username": "<ADMIN_USERNAME>", "api_key": "<GENERATION_API_KEY>", "error_ban_threshold": 3, "debug_enabled": False})
_response("POST /api/admin/debug", {"success": True, "message": "<RUNTIME_MESSAGE>", "enabled": True})
_REFRESH_CONFIG = {"at_auto_refresh_enabled": True, "protocol_refresh_enabled": True, "refresh_interval_minutes": 30}
_response("GET /api/token-refresh/config", {"success": True, "config": _REFRESH_CONFIG})
_response("POST /api/token-refresh/config", {"success": True, "applied_to_tokens": 0, "config": _REFRESH_CONFIG})
_response("GET /api/cache/config", {"success": True, "config": {"enabled": True, "timeout": 7200, "base_url": "https://<PUBLIC_FLOW2API_HOST>", "effective_base_url": "https://<PUBLIC_FLOW2API_HOST>"}})
_response("POST /api/captcha/config", {"success": True, "message": "<RUNTIME_MESSAGE>", "runtime_prepare_started": True, "runtime_prepare_message": "<RUNTIME_MESSAGE>", "runtime_status_method": "personal"})
_response("GET /api/captcha/config", {**_CAPTCHA_BODY, "flow2api_team_base_url": "<FIXED_TEAM_SERVICE_URL>", "flow2api_team_client_key": "<MASKED_TEAM_KEY>", "flow2api_team_task_type": "RecaptchaV3TaskProxylessM1S9"})
_response("GET /api/captcha/runtime-status", {"state": "idle", "active": False, "message": "", "error": "", "updated_at": None, "last_completed_at": None, "sequence": 0, "method": "personal", "task_running": False})
_response("GET /api/captcha/browser-stats", {"captcha_method": "browser", "running": False, "browsers": []})
_response("POST /api/captcha/score-test", {
    "success": True, "message": "<RUNTIME_MESSAGE>", "captcha_method": "<CONFIGURED_METHOD>",
    "website_url": "https://<TEST_SITE>/", "website_key": "<PUBLIC_SITE_KEY>", "action": "<PAGE_ACTION>",
    "verify_url": "https://<VERIFY_HOST>/<PATH>", "enterprise": False, "token_acquired": True,
    "token_preview": "<MASKED_CAPTCHA_TOKEN>", "token_elapsed_ms": 0, "verify_elapsed_ms": 0,
    "verify_http_status": 200, "score": 0.9, "verify_result": {"success": True, "score": 0.9},
    "verify_request_meta": {"mode": "server_post", "proxy_used": False, "user_agent": "<USER_AGENT>", "accept_language": "<ACCEPT_LANGUAGE>", "sec_ch_ua": "<CLIENT_HINT>", "sec_ch_ua_mobile": "<CLIENT_HINT>", "sec_ch_ua_platform": "<CLIENT_HINT>", "origin": "<ORIGIN>", "referer": "<REFERER>", "x_requested_with": "XMLHttpRequest", "proxy_source": "none", "proxy_url": "", "impersonate": "chrome"},
    "browser_proxy_enabled": False, "browser_proxy_url": "", "fingerprint": {}, "elapsed_ms": 0,
})
_response("GET /api/plugin/config", {"success": True, "config": {"connection_token": "<PLUGIN_CONNECTION_TOKEN>", "connection_url": "https://<FLOW2API_HOST>/api/plugin/update-token", "auto_enable_on_update": True}})
_response("POST /api/plugin/config", {"success": True, "message": "<RUNTIME_MESSAGE>", "connection_token": "<PLUGIN_CONNECTION_TOKEN>", "auto_enable_on_update": True})
_response("POST /api/plugin/update-token", {"success": True, "message": "<RUNTIME_MESSAGE>", "action": "added", "token_id": 1})
_response("POST /api/plugin/check-tokens", {"success": True, "tokens": [{"id": 1, "email": "<ACCOUNT_EMAIL>", "is_active": True, "needs_refresh": False, "at_expires": "<ISO_8601_TIMESTAMP>", "last_used_at": None, "protocol_mode": "protocol", "auto_refresh_enabled": True, "refresh_interval_minutes": 30, "last_st_refresh_at": None, "last_st_refresh_result": "", "credits": 0}]})
_response("GET /v1/models", {"object": "list", "data": [{"id": "<CONCRETE_MODEL_ID>", "object": "model", "owned_by": "flow2api", "description": "<MODEL_DESCRIPTION>"}]})
_response("GET /v1/models/aliases", {"object": "list", "data": [{"id": "<BASE_ALIAS_ID>", "object": "model", "owned_by": "flow2api", "description": "<MODEL_DESCRIPTION>", "is_alias": True}]})

_GEMINI_MODEL = {"name": "models/<MODEL_ID>", "displayName": "<MODEL_ID>", "description": "<MODEL_DESCRIPTION>", "version": "flow2api", "inputTokenLimit": 0, "outputTokenLimit": 0, "supportedGenerationMethods": ["generateContent", "streamGenerateContent"]}
_response(["GET /v1beta/models", "GET /models"], {"models": [_GEMINI_MODEL]})
_response(["GET /v1beta/models/{model}", "GET /models/{model}"], _GEMINI_MODEL)
_response("POST /v1/chat/completions", {"id": "<CHAT_COMPLETION_ID>", "object": "chat.completion", "created": 0, "model": "flow2api", "choices": [{"index": 0, "message": {"role": "assistant", "content": "![Generated Image](https://<MEDIA_HOST>/<IMAGE_PATH>)"}, "finish_reason": "stop"}]})
_response(["POST /v1beta/models/{model}:generateContent", "POST /models/{model}:generateContent"], {"candidates": [{"content": {"role": "model", "parts": [{"inlineData": {"mimeType": "image/png", "data": "<BASE64_IMAGE_BYTES>"}}]}, "finishReason": "STOP", "index": 0}], "modelVersion": "<RESOLVED_MODEL_ID>"})
_response(["POST /v1beta/models/{model}:streamGenerateContent", "POST /models/{model}:streamGenerateContent"], "data: {\"candidates\":[{\"content\":{\"role\":\"model\",\"parts\":[{\"text\":\"<PROGRESS_OR_OUTPUT>\"}]},\"index\":0}],\"modelVersion\":\"<RESOLVED_MODEL_ID>\"}\n\n")
_response("GET /api/integration/reference", {"version": 1, "endpoints": [], "models": [], "aliases": [], "schemas": {}})



# Authenticated remote desktop for the optional Linux VPS stack.
_add("GET /api/browser-desktop/config",
     ("Inspect remote desktop availability", "Xem khả năng mở màn hình VPS", "查看服务器桌面可用性"),
     ("Returns {success,desktop:{enabled,url}}. The optional VPS environment enables the desktop; local/default installs return enabled=false and url=null. The only enabled viewer URL is /browser-desktop/. No VNC address, password or browser profile is disclosed.",
      "Trả {success,desktop:{enabled,url}}. Môi trường VPS tùy chọn bật màn hình; bản local/mặc định trả enabled=false, url=null. Đường dẫn xem khi bật là /browser-desktop/. Không trả địa chỉ VNC, mật khẩu hay profile trình duyệt.",
      "返回 {success,desktop:{enabled,url}}。可选 VPS 环境启用桌面；本地或默认部署返回 enabled=false、url=null。启用时查看地址仅为 /browser-desktop/。不返回 VNC 地址、密码或浏览器 profile。"))
_add("GET /browser-desktop/",
     ("Open the administrator's VPS desktop", "Mở màn hình VPS của quản trị viên", "打开管理员 VPS 桌面"),
     ("Cookie-admin-session protected HTML viewer. Unauthenticated requests redirect to /login. Disabled or unavailable desktop returns HTTP 503. Uses noVNC over the same authenticated origin; it does not sign into Google automatically. The human operates normal Chrome, then closes the dedicated profile windows to let cookie synchronization run. Closing the viewer tab only disconnects the desktop viewer.",
      "Trang HTML cần cookie phiên quản trị. Chưa đăng nhập chuyển tới /login. Màn hình chưa bật hoặc không sẵn sàng trả HTTP 503. Dùng noVNC cùng origin đã xác thực; không tự đăng nhập Google. Người dùng thao tác Chrome thường rồi đóng các cửa sổ profile riêng để đồng bộ cookie. Đóng tab xem chỉ ngắt kết nối màn hình.",
      "HTML 查看器需要管理会话 Cookie；未登录重定向至 /login。桌面未启用或不可用时返回 HTTP 503。通过同源 noVNC 连接，不自动登录 Google。用户操作普通 Chrome，关闭该独立 profile 的窗口后才同步 Cookie。关闭查看标签页仅断开桌面查看连接。"), auth="public")
_add("GET /browser-desktop/assets/{asset_path:path}",
     ("Load protected noVNC assets", "Tải tài nguyên noVNC được bảo vệ", "加载受保护的 noVNC 资源"),
     ("Serves noVNC ES modules and assets from a fixed configured server directory after admin authentication. Rejects path traversal, absolute paths and symlink escapes. Disabled desktop returns 503 and missing assets return 404. These are viewer dependencies, not account files or exported cookies.",
      "Trả module ES và tài nguyên noVNC từ thư mục server cố định sau khi xác thực quản trị. Từ chối đi ngược thư mục, đường dẫn tuyệt đối và liên kết vượt thư mục. Màn hình chưa bật trả 503, tệp thiếu trả 404. Đây là tài nguyên của trình xem, không phải tệp tài khoản hay cookie xuất ra.",
      "管理验证后从固定服务器目录提供 noVNC ES 模块和资源。拒绝路径遍历、绝对路径和符号链接越界。未启用桌面返回 503，资源不存在返回 404。仅提供查看器依赖，不提供账号文件或导出 Cookie。"))
_add("WEBSOCKET /api/browser-desktop/ws",
     ("Connect the authenticated desktop stream", "Kết nối luồng màn hình đã xác thực", "连接已验证的桌面流"),
     ("Browser WebSocket using only the admin_session cookie and exact same-origin Origin. Query parameters are rejected; do not send API keys, passwords or remote destinations in the URL. Relays binary RFB only to fixed container-loopback port 5900; there is no user-selectable target. Invalid/expired session or origin closes with 1008; unavailable desktop closes with 1013. Revoked admin sessions disconnect within the session-check interval. Viewer disconnect closes only its relay, preserving Chrome and the login watcher. RFB client may offer the binary subprotocol.",
      "WebSocket trình duyệt chỉ dùng cookie admin_session và Origin khớp chính xác cùng nguồn. Từ chối query; không gửi API key, mật khẩu hay đích kết nối qua URL. Chỉ chuyển RFB nhị phân tới cổng 5900 loopback cố định trong container; không chọn đích từ người dùng. Phiên hoặc Origin sai/hết hạn đóng mã 1008; màn hình không sẵn sàng đóng 1013. Phiên quản trị bị thu hồi sẽ ngắt trong chu kỳ kiểm tra. Ngắt trình xem chỉ đóng cầu nối, giữ Chrome và bộ theo dõi đăng nhập. Có thể đề nghị subprotocol binary.",
      "浏览器 WebSocket 仅使用 admin_session Cookie 和完全同源 Origin。拒绝查询参数；不要在 URL 中发送 API Key、密码或远程目标。仅将二进制 RFB 转发至容器固定 loopback 5900，不接受用户指定目标。会话或 Origin 无效/过期以 1008 关闭，桌面不可用以 1013 关闭。管理会话撤销后在检查周期内断开。断开查看器仅关闭转发连接，保留 Chrome 与登录监视。客户端可请求 binary 子协议。"), auth="public")
_add("GET /static/browser-desktop.js",
     ("Load the desktop viewer logic", "Tải mã trình xem màn hình VPS", "加载桌面查看器逻辑"),
     ("Public no-store JavaScript for the translated noVNC viewer; it contains no credentials or VNC connection secret. Actual viewer assets and desktop WebSocket require the administrator session.",
      "JavaScript công khai không lưu cache cho trình xem noVNC đa ngôn ngữ; không chứa thông tin xác thực hoặc bí mật VNC. Tài nguyên noVNC và WebSocket thực tế cần phiên quản trị.",
      "公开且不缓存的多语言 noVNC 查看器 JavaScript，不含凭据或 VNC 连接密钥。实际 noVNC 资源和桌面 WebSocket 需要管理会话。"), auth="public")
