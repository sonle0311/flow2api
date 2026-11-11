(function () {
    'use strict';

    // Documentation only: building this string never contacts the server.
    const prose = {
        en: {
            geminiVideo: ['Gemini video: the same separate parameters', 'Use a simple model name in the URL and the same generationConfig.videoConfig body as OpenAI. Save the body as video.json and POST it to the endpoint below with x-goog-api-key. I2V/R2V use image fileData or inlineData parts as shown above; extension requires OpenAI.'],
            title: 'Runnable integration recipes',
            intro: 'These examples describe this repository, not the full OpenAI or Google API. Discover the deployed catalog first. The representative IDs below exist in the current registry; availability still depends on account tier, credits, captcha and upstream access. The complete registry and capability tables appear elsewhere in this guide.',
            setup: ['Environment and discovery', 'Use the server API key configured by the administrator, never a Google Cookie, account token or admin password. Replace the placeholder locally. ROOT is the service origin, including any reverse-proxy prefix, without /v1. An OpenAI SDK base_url ends in /v1; Gemini requests use /v1beta/models. Do not append /v1 twice. Headers are preferable to ?key= because URLs may be logged. Authentication accepts Bearer, x-goog-api-key, or ?key=; if several are supplied, Bearer takes precedence, then x-goog-api-key. A wrong Bearer key is not rescued by a correct query key.'],
            image: ['Text to image: curl and a request file', 'Save this JSON as request.json (UTF-8). Run the curl command below from Bash or PowerShell using curl.exe on Windows. stream:false waits for the final response. The result is choices[0].message.content containing Markdown, not an OpenAI Images data array. A simple string prompt generates media; this service is not a general conversational or function-calling LLM.'],
            edit: ['Image to image: URL or local file', 'A multimodal message combines a nonempty text prompt and image_url objects. Use an HTTPS image URL reachable by the server, or a data URI containing the actual base64 image bytes. The URL is downloaded by the server, so localhost refers to that server. The Python script below creates edit.json from a local reference.png; then use the same curl command with @edit.json. Replace the data URI with an HTTPS URL for URL input. Do not pass a raw local filesystem path or just the filename. Only the last OpenAI message supplies the main prompt and direct images; image models can additionally recover the most recent image from earlier assistant Markdown. Send explicit references for predictable behavior.'],
            dimensions: ['Aspect ratio, resolution and aliases', 'Use a simplified image alias plus generationConfig.imageConfig to select a variant. For example the request below resolves to gemini-3.1-flash-image-portrait-2k. Ratios are 16:9, 9:16, 1:1, 4:3, 3:4; names landscape, portrait, square, four-three, three-four are also accepted. imageSize is 1K (base output), 2K or 4K. Upsampling can fall back to the original image; inspect the actual output. If no ratio is supplied, aliases infer it from the first input image or default to landscape. Explicit variant IDs keep their configured shape/resolution, so do not expect configuration fields to override them.', 'The resolver also accepts generationConfig.aspectRatio/imageSize, snake_case image_config/aspect_ratio/image_size, raw JSON extra_body.generationConfig (or extraBody), and top-level aspect_ratio/image_size. OpenAI SDK extra_body merges fields into the outgoing JSON; use extra_body={"generationConfig": ...}. Top-level size such as 1024x1792 approximates the closest supported ratio; quality medium maps to 2k and high/hd/ultra to 4k, while low/standard request base output. These are compatibility mappings, not arbitrary pixel dimensions. Resolution applies only where the selected alias has a matching variant. Prefer one spelling and avoid conflicting fields.'],
            video: ['Video recipes: simple model names and separate parameters', 'Every body below goes to POST /v1/chat/completions with the same Bearer header. Save one as request.json and use the previous curl command with --max-time 3600. Use veo-3.1-fast, veo-3.1-lite, veo-3.1-quality, omni-1.1-flash or omni-1.2-flash with generationConfig.videoConfig.durationSeconds, aspectRatio and mode. Defaults are 8 seconds, 16:9, t2v for Veo and auto for Omni; selecting i2v defaults to 4 seconds, while r2v and extend default to 8. Choose only combinations registered for that model: quality has no R2V; extension uses 8 seconds. Unsupported combinations return validation errors. T2V has no images; I2V takes 1–2 ordered first/last frames. Use 1–3 references for R2V, not first/last interpolation. The R2V registry minimum is 1, although the local handler permits 0 and falls back to text generation; upstream acceptance is not guaranteed. Omni auto takes 0–3 images and selects the reference path when supplied. Explicit compatibility IDs retain their fixed settings. Catalog presence does not guarantee account access.'],
            extend: ['Extend an existing Flow video', 'Use the Flow mediaGenerationId, not a chatcmpl ID, operation/task ID, MP4 URL or uploaded arbitrary video. The current public extension model below accepts extend:// in an OpenAI image_url slot; this marker is not an image download. The streaming video content can contain data-media-id; administrators can also inspect generated_assets.mediaGenerationId in generation logs. The ordinary nonstream completion returns a video URL without exposing a structured source media ID, so retain the ID when available or obtain it from authorized Flow/admin records. There is no public upload-video or media-ID lookup endpoint in this adapter. Gemini normalization does not forward an extension ID; use the OpenAI route for extension.'],
            upscale: ['Video upsampling and legacy compatibility', 'Current public hyphenated video IDs do not configure video upsampling. Hidden legacy IDs such as veo_3_1_t2v_4s_1080p and veo_3_1_i2v_s_4s_4k remain accepted by this source registry and generate a new video before upsampling it. They are not a standalone upscale endpoint for an arbitrary MP4. Use only if the deployed version supports them and the account can access their upstream models. The legacy alias veo_3_1_t2v with generationConfig.imageConfig.imageSize="1080p" or "4K" selects an available legacy upscale variant; this does not apply automatically to veo-3.1-fast. An upscale failure may return the original video. There is no /videos/upscale route.'],
            gemini: ['Gemini-compatible requests', 'Save the JSON below as gemini.json. contents.parts.text is the prompt. inlineData contains base64 only (no data: prefix); fileData.fileUri accepts a reachable image URL or data URI with an image MIME type. To use a local file, reuse the Python base64 conversion above and put the encoded bytes in inlineData.data. The server uses the last user content, not a full Gemini reasoning conversation. For text-only image generation, remove the image part. POST :generateContent returns candidates[].content.parts with inlineData or fileData for media; :streamGenerateContent uses SSE (optional ?alt=sse is tolerated). Gemini progress is returned as text parts; this adapter does not add a thought:true flag. This is an adapter: response modalities, tools, structured output and unrelated Gemini methods are not promised.'],
            js: ['JavaScript: robust fetch and SSE', 'Run this in a modern browser or Node.js with fetch (Node 18+). Set environment variables in Node; in a browser the fallback key is a placeholder to replace only in trusted local use. Production applications should proxy through their own backend so the service key is not embedded in public frontend code. The parser buffers UTF-8 and SSE frames across network chunks, handles CRLF, [DONE], final partial frames, HTTP errors and in-stream JSON errors. reasoning_content is generation progress, not the final media result. AbortController closes the client request; it does not guarantee upstream cancellation or refund.'],
            python: ['Python: requests, httpx and optional OpenAI SDK', 'Install only the library needed: python -m pip install requests, httpx, or openai. Both plain HTTP examples disable automatic generation retries. The optional SDK uses chat.completions.create and max_retries=0. SDK images.generate, images.edit, Responses, assistants, tools, embeddings, audio and a generic text chat are not implemented routes in this repository. Extra fields accepted by a request schema do not imply their semantics are implemented.'],
            adapter: ['Connecting any tool or building an adapter', '1. Pick the OpenAI-compatible provider/custom endpoint if the tool can send chat/completions, or Gemini-compatible if it supports a custom Gemini root. Set base URL, server key, and a verified model ID manually if discovery is unavailable.\n2. Discover /v1/models and /v1/models/aliases; preserve capability distinctions. Display only suitable image/video models in each workflow. Do not rename an image model to gpt-4o and assume text chat works.\n3. Translate the user prompt and actual image bytes/URLs into the request format shown above. Preserve ordered first/last frames and reference-count limits. The tool must allow image attachments, custom model IDs, long timeouts and custom JSON for advanced settings.\n4. Parse the final OpenAI content or Gemini media parts. Preserve progress separately. An HTTP 200 SSE stream can still carry an error. If a tool ignores reasoning_content, generation may appear silent until completion; that is normal.\n5. For images, extract Markdown image destinations; for video, parse the video src attribute from the returned content (nonstream wraps it in an html code fence). Never insert the returned HTML with innerHTML. Treat all model text and URLs as untrusted: use textContent for text, create img/video elements yourself, validate URL schemes (HTTPS or approved HTTP; bounded image data URIs when needed), restrict origins according to your application, and set video.controls=true. Retain data-media-id separately for extension. Gemini inlineData should become a Blob with a validated image MIME type.\n6. Serve cache URLs through a reachable public root when remote clients need them; /tmp links and localhost links may be inaccessible outside the deployment. Signed upstream URLs and cache entries can expire. Save required output promptly according to deployment policy.'],
            errors: ['Errors, waiting, cancellation and retries', 'Authentication failures use HTTP 401 with {"detail":"Invalid API key"}. Validation may use {"detail":...} (400/422). Generation errors use the OpenAI error envelope below; Gemini uses error.code/message/status. Handle both HTTP status and payload. A successful TCP/HTTP connection is not proof that generation succeeded. 400 usually means unsupported model, missing prompt or wrong image count; 403 may indicate model/account access; 503 may mean no usable token; 502/504 may indicate upstream failure or timeout. Inspect the actual error message and administrator logs rather than retrying every error.', 'Default generation configuration is 300 seconds for images and 1500 seconds for video, but administrators can change it and polling/upscaling can extend the effective wait. Configure the client, reverse proxy and load balancer timeouts together; the examples use a generous 3600-second limit. Disable proxy SSE buffering. Closing a stream or timing out can leave upstream work already submitted. No public cancellation, job-status polling or idempotency-key contract is provided by these generation routes. A retry may create another paid job. Retry discovery GETs safely; for POST, decide from logs/output first, then use bounded backoff for genuinely transient failures. Never loop automatically on 400/401/403.']
        },
        vi: {
            geminiVideo: ['Video Gemini: cùng các tham số riêng', 'Dùng tên model ngắn trong URL và generationConfig.videoConfig như OpenAI. Lưu body thành video.json, POST tới endpoint dưới với x-goog-api-key. I2V/R2V dùng part ảnh fileData hoặc inlineData như trên; nối dài cần OpenAI.'],
            title: 'Công thức tích hợp có thể chạy',
            intro: 'Các ví dụ mô tả mã nguồn này, không phải toàn bộ API OpenAI hay Google. Hãy đọc danh sách model của máy chủ trước. ID minh họa có trong registry hiện tại; quyền sử dụng còn phụ thuộc gói tài khoản, credits, captcha và upstream. Bảng registry và khả năng đầy đủ nằm ở phần khác của hướng dẫn.',
            setup: ['Môi trường và khám phá model', 'Dùng API key máy chủ do quản trị viên cấu hình, không dùng Google Cookie, token tài khoản hay mật khẩu admin. Thay placeholder trên máy của bạn. ROOT là gốc dịch vụ, có thể gồm tiền tố reverse proxy, không có /v1. base_url của OpenAI SDK kết thúc bằng /v1; Gemini gọi /v1beta/models. Tránh lặp /v1. Ưu tiên header thay cho ?key= vì URL có thể bị ghi log. Hệ thống nhận Bearer, x-goog-api-key hoặc ?key=; nếu cùng xuất hiện thì ưu tiên Bearer rồi x-goog-api-key. Bearer sai không được cứu bởi query key đúng.'],
            image: ['Văn bản thành ảnh: curl và file yêu cầu', 'Lưu JSON thành request.json (UTF-8). Chạy lệnh curl bên dưới trong Bash hoặc PowerShell, dùng curl.exe trên Windows. stream:false đợi kết quả cuối. Kết quả là Markdown trong choices[0].message.content, không phải mảng data của OpenAI Images. Prompt chuỗi tạo nội dung đa phương tiện; dịch vụ không phải LLM hội thoại tổng quát hay function calling.'],
            edit: ['Ảnh thành ảnh: URL hoặc file cục bộ', 'Một tin nhắn đa phương thức gồm prompt văn bản không rỗng và các đối tượng image_url. Dùng URL HTTPS mà máy chủ tải được hoặc data URI chứa base64 thực của ảnh. localhost trong URL là máy chủ, không phải máy của người dùng. Script Python bên dưới tạo edit.json từ reference.png; sau đó dùng lệnh curl với @edit.json. Muốn dùng URL thì thay data URI bằng URL HTTPS. Không gửi đường dẫn file cục bộ hay chỉ tên file. Tin nhắn OpenAI cuối cung cấp prompt và ảnh trực tiếp; model ảnh còn có thể lấy ảnh gần nhất từ Markdown assistant trước đó. Gửi ảnh tham chiếu tường minh để có kết quả ổn định.'],
            dimensions: ['Tỉ lệ, độ phân giải và alias', 'Dùng alias ảnh rút gọn cùng generationConfig.imageConfig để chọn biến thể. Ví dụ dưới phân giải thành gemini-3.1-flash-image-portrait-2k. Các tỉ lệ: 16:9, 9:16, 1:1, 4:3, 3:4; tên landscape, portrait, square, four-three, three-four cũng hợp lệ. imageSize nhận 1K (ảnh gốc), 2K hoặc 4K. Phóng ảnh có thể thất bại và trả ảnh gốc; kiểm tra kết quả thực. Nếu không chỉ định tỉ lệ, alias suy từ ảnh đầu tiên hoặc mặc định ngang. ID biến thể tường minh giữ tỉ lệ/độ phân giải cấu hình sẵn, không bị ghi đè bởi các trường này.', 'Resolver còn nhận generationConfig.aspectRatio/imageSize, image_config/aspect_ratio/image_size, JSON extra_body.generationConfig (hoặc extraBody), và aspect_ratio/image_size ở cấp ngoài cùng. OpenAI SDK gộp extra_body vào JSON gửi đi; dùng extra_body={"generationConfig": ...}. size như 1024x1792 được ánh xạ tới tỉ lệ gần nhất; quality medium thành 2k, high/hd/ultra thành 4k, low/standard dùng ảnh gốc. Đây là ánh xạ tương thích, không phải kích thước pixel tùy ý. Độ phân giải chỉ áp dụng khi alias có biến thể tương ứng. Dùng một kiểu tên và tránh các trường mâu thuẫn.'],
            video: ['Video: tên model ngắn và tham số riêng', 'Mỗi body gửi tới POST /v1/chat/completions với cùng header Bearer. Lưu thành request.json rồi chạy curl ở trên với --max-time 3600. Dùng veo-3.1-fast, veo-3.1-lite, veo-3.1-quality, omni-1.1-flash hoặc omni-1.2-flash cùng generationConfig.videoConfig.durationSeconds, aspectRatio và mode. Mặc định 8 giây, 16:9; Veo dùng t2v, Omni dùng auto. Chọn i2v mặc định 4 giây; r2v và extend mặc định 8. Chỉ dùng tổ hợp được đăng ký: quality không có R2V; nối dài dùng 8 giây. Tổ hợp không hỗ trợ trả lỗi kiểm tra dữ liệu. T2V không có ảnh; I2V nhận 1–2 khung theo thứ tự đầu/cuối. Nên dùng 1–3 ảnh cho R2V, không phải nội suy đầu/cuối. Registry R2V khai báo tối thiểu 1 ảnh nhưng handler cục bộ cho 0 và chuyển sang tạo từ văn bản; không bảo đảm upstream chấp nhận. Omni auto nhận 0–3 ảnh và chọn nhánh tham chiếu khi có ảnh. ID tương thích đầy đủ giữ cấu hình cố định. Có trong registry không bảo đảm tài khoản có quyền dùng.'],
            extend: ['Nối dài video Flow có sẵn', 'Dùng mediaGenerationId của Flow, không phải chatcmpl ID, task/operation ID, URL MP4 hay video tải lên tùy ý. Model public dưới nhận extend:// trong image_url của OpenAI; đây là marker, không phải URL tải ảnh. Nội dung video streaming có thể chứa data-media-id; quản trị viên cũng có thể xem generated_assets.mediaGenerationId trong log tạo nội dung. Phản hồi nonstream thông thường chỉ trả URL video, không có trường source media ID có cấu trúc. Hãy giữ ID khi nhận được hoặc lấy từ hồ sơ Flow/admin được phép truy cập. Adapter không có endpoint public để tải video lên hay tra media ID. Gemini không chuyển tiếp extension ID; dùng route OpenAI để nối dài.'],
            upscale: ['Phóng video và tương thích legacy', 'ID video public có dấu gạch nối hiện tại không cấu hình phóng video. ID legacy ẩn như veo_3_1_t2v_4s_1080p và veo_3_1_i2v_s_4s_4k vẫn được registry mã nguồn nhận và tạo video mới trước khi phóng. Chúng không phải endpoint phóng một MP4 bất kỳ. Chỉ dùng khi phiên bản triển khai còn hỗ trợ và tài khoản truy cập được model upstream. Alias legacy veo_3_1_t2v với generationConfig.imageConfig.imageSize="1080p" hoặc "4K" chọn biến thể phóng tương ứng; không tự áp dụng cho veo-3.1-fast. Phóng thất bại có thể trả video gốc. Không có route /videos/upscale.'],
            gemini: ['Yêu cầu tương thích Gemini', 'Lưu JSON dưới thành gemini.json. contents.parts.text là prompt. inlineData chứa base64 thuần, không có tiền tố data:; fileData.fileUri nhận URL ảnh hoặc data URI với MIME ảnh. Với file cục bộ, dùng phép chuyển base64 trong Python ở trên và đặt chuỗi mã hóa vào inlineData.data. Máy chủ dùng user content cuối, không thực hiện toàn bộ hội thoại suy luận Gemini. Để tạo ảnh chỉ bằng văn bản, bỏ part ảnh. POST :generateContent trả media trong candidates[].content.parts dưới dạng inlineData hoặc fileData; :streamGenerateContent dùng SSE (?alt=sse tùy chọn vẫn được nhận). Tiến trình Gemini được trả bằng text parts; adapter không thêm cờ thought:true. Đây là adapter; không hứa hỗ trợ response modalities, tools, structured output hay các phương thức Gemini khác.'],
            js: ['JavaScript: fetch và SSE có bộ đệm', 'Chạy trong trình duyệt mới hoặc Node.js có fetch (Node 18+). Đặt biến môi trường ở Node; trong trình duyệt key dự phòng là placeholder, chỉ thay khi chạy cục bộ đáng tin cậy. Ứng dụng production nên gọi qua backend riêng để không nhúng key vào frontend công khai. Parser ghép UTF-8 và khung SSE qua nhiều chunk, xử lý CRLF, [DONE], khung cuối thiếu dấu ngắt, lỗi HTTP và JSON lỗi trong stream. reasoning_content là tiến trình tạo nội dung, không phải media cuối. AbortController đóng yêu cầu phía client, không bảo đảm hủy upstream hay hoàn credits.'],
            python: ['Python: requests, httpx và OpenAI SDK tùy chọn', 'Chỉ cài thư viện cần dùng: python -m pip install requests, httpx hoặc openai. Hai ví dụ HTTP thuần không tự retry tạo nội dung. SDK tùy chọn dùng chat.completions.create và max_retries=0. SDK images.generate, images.edit, Responses, assistants, tools, embeddings, audio và chat văn bản tổng quát không phải route được triển khai ở đây. Schema nhận một trường không đồng nghĩa chức năng của trường đó được thực thi.'],
            adapter: ['Kết nối công cụ bất kỳ hoặc viết adapter', '1. Chọn provider OpenAI-compatible/custom endpoint nếu công cụ gửi được chat/completions, hoặc Gemini-compatible nếu cho đổi gốc Gemini. Đặt base URL, key máy chủ và model ID đã kiểm tra; nhập model thủ công nếu không khám phá được.\n2. Đọc /v1/models và /v1/models/aliases; giữ đúng khác biệt khả năng. Chỉ hiện model ảnh/video phù hợp từng luồng. Đừng đổi tên model ảnh thành gpt-4o rồi kỳ vọng chat văn bản.\n3. Chuyển prompt và bytes/URL ảnh thực theo định dạng trên. Giữ thứ tự khung đầu/cuối và giới hạn số ảnh. Công cụ phải cho đính kèm ảnh, dùng model tùy chỉnh, timeout dài và JSON bổ sung cho thiết lập nâng cao.\n4. Đọc content OpenAI cuối hoặc media parts Gemini. Tách tiến trình khỏi kết quả. SSE HTTP 200 vẫn có thể chứa lỗi. Nếu công cụ bỏ reasoning_content, có thể không thấy gì trước kết quả cuối.\n5. Với ảnh, lấy đích của Markdown ảnh; với video, đọc thuộc tính src (nonstream bọc video trong code fence html). Không đưa HTML trả về vào innerHTML. Xem văn bản và URL là dữ liệu chưa tin cậy: dùng textContent, tự tạo img/video, kiểm tra scheme (HTTPS hoặc HTTP được duyệt; data URI ảnh có giới hạn dung lượng), hạn chế origin theo ứng dụng và đặt video.controls=true. Lưu data-media-id riêng để nối dài. inlineData Gemini nên chuyển thành Blob với MIME ảnh đã kiểm tra.\n6. Dùng gốc public truy cập được cho URL cache khi có client từ xa; /tmp hay localhost có thể không truy cập được bên ngoài. URL upstream có chữ ký và cache có thể hết hạn. Lưu đầu ra cần thiết sớm theo chính sách triển khai.'],
            errors: ['Lỗi, thời gian chờ, hủy và retry', 'Sai xác thực trả HTTP 401 với {"detail":"Invalid API key"}. Lỗi validation có thể là {"detail":...} (400/422). Lỗi tạo nội dung dùng envelope OpenAI dưới; Gemini dùng error.code/message/status. Kiểm tra cả HTTP status lẫn payload. Kết nối TCP/HTTP thành công chưa chứng minh đã tạo xong. 400 thường là model không hỗ trợ, thiếu prompt hoặc sai số ảnh; 403 có thể do quyền model/tài khoản; 503 có thể không còn token dùng được; 502/504 có thể do lỗi upstream/timeout. Đọc thông báo và log quản trị trước khi retry.', 'Cấu hình mặc định là 300 giây cho ảnh và 1500 giây cho video, nhưng admin có thể đổi và polling/phóng có thể làm thời gian chờ thực dài hơn. Cấu hình timeout client, reverse proxy và load balancer đồng bộ; ví dụ dùng 3600 giây. Tắt buffering SSE ở proxy. Đóng stream hay timeout có thể xảy ra sau khi upstream đã nhận công việc. Các route này không có hợp đồng public về hủy, polling trạng thái job hay idempotency key. Retry có thể tạo thêm job tốn phí. GET khám phá có thể retry an toàn; với POST hãy kiểm tra log/đầu ra trước rồi mới backoff có giới hạn cho lỗi tạm thời. Không lặp tự động với 400/401/403.']
        },
        'zh-CN': {
            geminiVideo: ['Gemini 视频：相同的独立参数', 'URL 使用简洁模型名，请求体使用与 OpenAI 相同的 generationConfig.videoConfig。将 body 保存为 video.json，使用 x-goog-api-key 向下方端点 POST。I2V/R2V 用上面的 fileData 或 inlineData 图片 parts；续写需使用 OpenAI。'],
            title: '可运行的集成示例',
            intro: '以下示例描述本仓库，而非完整的 OpenAI 或 Google API。请先查询部署服务器的模型目录。示例 ID 均存在于当前 registry；实际可用性仍取决于账号等级、积分、验证码及上游权限。完整模型与能力表位于本指南其他部分。',
            setup: ['环境变量与模型发现', '使用管理员配置的服务器 API key，不要使用 Google Cookie、账号 token 或管理员密码。请在本机替换占位值。ROOT 是服务根地址，可包含反向代理路径前缀，但不带 /v1。OpenAI SDK 的 base_url 以 /v1 结尾；Gemini 使用 /v1beta/models。避免重复 /v1。优先使用请求头，因为 ?key= 可能出现在 URL 日志中。认证支持 Bearer、x-goog-api-key、?key=，同时存在时依次优先 Bearer、x-goog-api-key。错误的 Bearer 不会被正确的查询参数补救。'],
            image: ['文生图：curl 与请求文件', '将 JSON 保存为 UTF-8 的 request.json。在 Bash 或 PowerShell 运行下面的 curl，Windows 请使用 curl.exe。stream:false 等待最终结果。结果位于 choices[0].message.content，是 Markdown，而不是 OpenAI Images 的 data 数组。字符串提示词用于生成媒体；本服务不是通用对话或函数调用 LLM。'],
            edit: ['图生图：URL 或本地文件', '多模态消息由非空文本提示词与 image_url 对象组成。使用服务器可访问的 HTTPS 图片 URL，或包含真实图片 base64 字节的 data URI。URL 中的 localhost 指服务器自身。下面的 Python 脚本从 reference.png 生成 edit.json，然后使用相同 curl 命令并改为 @edit.json。URL 输入可将 data URI 换为 HTTPS URL。不要传本地路径或只有文件名。主要提示词和直接图片取自最后一条 OpenAI 消息；图片模型还可能从之前 assistant 的 Markdown 恢复最近图片。明确传入参考图片更可靠。'],
            dimensions: ['宽高比、分辨率与别名', '使用简化图片别名和 generationConfig.imageConfig 选择变体。下面示例解析为 gemini-3.1-flash-image-portrait-2k。支持比例 16:9、9:16、1:1、4:3、3:4，也支持 landscape、portrait、square、four-three、three-four。imageSize 可为 1K（基础输出）、2K、4K。放大失败可能回退原图，请检查实际结果。别名未指定比例时从第一张参考图推断，否则默认横向。完整变体 ID 保留自身配置，不应期待这些字段覆盖其比例或分辨率。', '解析器还接受 generationConfig.aspectRatio/imageSize、image_config/aspect_ratio/image_size、原始 JSON 的 extra_body.generationConfig（或 extraBody）以及顶层 aspect_ratio/image_size。OpenAI SDK 会把 extra_body 合并到发出的 JSON；应使用 extra_body={"generationConfig": ...}。顶层 size 如 1024x1792 会近似映射为最接近的支持比例；quality medium 对应 2k，high/hd/ultra 对应 4k，low/standard 使用基础输出。这是兼容映射，并非任意像素尺寸。只有别名存在对应变体时才应用分辨率。建议统一字段格式，避免冲突。'],
            video: ['视频示例：简洁模型名与独立参数', '以下 body 均发送至 POST /v1/chat/completions，使用相同 Bearer 请求头。保存为 request.json 并运行上面的 curl，视频使用 --max-time 3600。模型选择 veo-3.1-fast、veo-3.1-lite、veo-3.1-quality、omni-1.1-flash 或 omni-1.2-flash，参数通过 generationConfig.videoConfig.durationSeconds、aspectRatio、mode 单独传入。默认 8 秒、16:9；Veo 为 t2v，Omni 为 auto。i2v 默认 4 秒，r2v 与 extend 默认 8 秒。仅选择已注册组合：quality 无 R2V，续写使用 8 秒。不支持的组合会返回校验错误。T2V 不带图片；I2V 接受按首尾顺序排列的 1–2 张图片。R2V 建议使用 1–3 张参考图，不等同于首尾插值。R2V 注册表最少 1 张，但本地处理器允许 0 张并回退文生视频；不保证上游接受。Omni auto 支持 0–3 张图片，有图片时自动使用参考路径。完整兼容 ID 保留固定配置。目录存在模型不代表当前账号有权限。'],
            extend: ['续写已有 Flow 视频', '使用 Flow 的 mediaGenerationId，不是 chatcmpl ID、任务/operation ID、MP4 URL，也不是任意上传视频。下面的公开续写模型通过 OpenAI image_url 接受 extend:// 标记，该标记不会下载图片。流式视频内容可能含 data-media-id；管理员也可在生成日志中查看 generated_assets.mediaGenerationId。普通非流式响应只返回视频 URL，不提供结构化源媒体 ID，因此请在获得 ID 时保存，或从有权访问的 Flow/管理记录取得。适配器没有公开的视频上传或媒体 ID 查询端点。Gemini 规范化不会转发续写 ID，请用 OpenAI 路由续写。'],
            upscale: ['视频放大与旧版兼容', '当前公开的连字符视频 ID 不配置视频放大。隐藏旧 ID 如 veo_3_1_t2v_4s_1080p、veo_3_1_i2v_s_4s_4k 在源码 registry 中仍被接受，其流程是先生成新视频再放大，而非放大任意 MP4 的独立端点。仅在部署版本支持且账号有相应上游权限时使用。旧别名 veo_3_1_t2v 配合 generationConfig.imageConfig.imageSize="1080p" 或 "4K" 可选择相应旧放大变体；不自动适用于 veo-3.1-fast。放大失败可能返回原视频。没有 /videos/upscale 路由。'],
            gemini: ['Gemini 兼容请求', '将下面 JSON 保存为 gemini.json。contents.parts.text 是提示词。inlineData 是纯 base64，不含 data: 前缀；fileData.fileUri 接受可访问的图片 URL 或图片 MIME 的 data URI。本地文件可用前面的 Python base64 转换，再填入 inlineData.data。服务器使用最后一条 user content，不实现完整 Gemini 推理对话。纯文生图时删掉图片 part。POST :generateContent 在 candidates[].content.parts 中返回 inlineData 或 fileData；:streamGenerateContent 使用 SSE（可附加 ?alt=sse）。Gemini 进度以文本 parts 返回；适配器不会添加 thought:true 标记。这是兼容适配器，不承诺 response modalities、tools、structured output 或其他 Gemini 方法。'],
            js: ['JavaScript：fetch 与健壮 SSE 解析', '在现代浏览器或带 fetch 的 Node.js（18+）运行。Node 使用环境变量；浏览器中的备用 key 是占位值，只能在可信本地场景替换。生产应用应通过自己的后端代理，避免把服务 key 放到公开前端。解析器跨网络 chunk 缓冲 UTF-8 和 SSE 帧，处理 CRLF、[DONE]、最后一个不完整帧、HTTP 错误和流内 JSON 错误。reasoning_content 是生成进度，不是最终媒体。AbortController 关闭客户端请求，不保证上游取消或退还积分。'],
            python: ['Python：requests、httpx 与可选 OpenAI SDK', '只安装所需库：python -m pip install requests、httpx 或 openai。两个原生 HTTP 示例都不自动重试生成请求。可选 SDK 使用 chat.completions.create，并设置 max_retries=0。SDK images.generate、images.edit、Responses、assistants、tools、embeddings、audio 及通用文本对话不是本仓库已实现的路由。请求 schema 接受字段不代表实现该字段的语义。'],
            adapter: ['连接任意工具或编写适配器', '1. 工具能发送 chat/completions 时选择 OpenAI-compatible/custom endpoint；能自定义 Gemini 根地址时也可选 Gemini-compatible。设置服务地址、服务器 key 和已验证模型 ID；不能自动发现时手动填写。\n2. 查询 /v1/models 和 /v1/models/aliases，保留能力差异，为各流程仅显示适用图片/视频模型。不要把图片模型改名为 gpt-4o 并期待普通文本聊天。\n3. 将提示词及真实图片字节/URL 转换为上面的格式。保留首尾帧顺序与参考图数量限制。工具需要支持附件、自定义模型、长超时，以及高级设置用的自定义 JSON。\n4. 解析最终 OpenAI content 或 Gemini 媒体 parts，单独保留进度。HTTP 200 的 SSE 仍可能携带错误。工具忽略 reasoning_content 时，完成之前可能一直没有可见文本。\n5. 图片提取 Markdown 图片目标；视频解析 src 属性（非流式有 html 代码围栏）。不要将返回 HTML 填入 innerHTML。将文字与 URL 视为不可信：文字用 textContent，自己创建 img/video，校验 URL 协议（HTTPS 或获准 HTTP；必要时限制大小的图片 data URI），按应用策略限制来源，设置 video.controls=true。单独保存 data-media-id 供续写使用。Gemini inlineData 应在校验图片 MIME 后转为 Blob。\n6. 远程客户端需要可访问的公开缓存根地址；/tmp 或 localhost 链接在部署之外可能不可达。上游签名链接及缓存可能过期，按部署策略及时保存必要输出。'],
            errors: ['错误、等待、取消与重试', '认证失败返回 HTTP 401 和 {"detail":"Invalid API key"}。校验错误可能为 {"detail":...}（400/422）。生成错误使用下面的 OpenAI envelope；Gemini 使用 error.code/message/status。同时检查 HTTP 状态与 payload。TCP/HTTP 连接成功不代表生成成功。400 常见于模型不支持、提示词缺失、图片数量错误；403 可能是模型/账号权限；503 可能是无可用 token；502/504 可能是上游故障或超时。请查看实际错误和管理日志，不要对所有错误盲目重试。', '默认生成配置为图片 300 秒、视频 1500 秒，但管理员可修改，轮询/放大也可能延长实际等待。统一配置客户端、反向代理及负载均衡器超时；示例使用较宽裕的 3600 秒。关闭代理 SSE 缓冲。关闭连接或超时时，上游可能已经提交任务。这些生成路由没有公开取消、任务状态轮询或 idempotency key 契约。重试可能再次产生付费任务。发现模型的 GET 可安全重试；POST 应先核对日志/结果，再对临时故障采用有限退避。不要自动循环重试 400/401/403。']
        }
    };

    const fence = (language, value) => '\n```' + language + '\n' + value + '\n```\n';
    const json = value => fence('json', JSON.stringify(value, null, 2));
    const textPart = text => ({ type: 'text', text });
    const imagePart = url => ({ type: 'image_url', image_url: { url } });
    const imageModel = 'gemini-3.1-flash-image';
    const body = (model, content, generationConfig = model === imageModel ? { imageConfig: { aspectRatio: '16:9', imageSize: '1K' } } : null) => ({ model, messages: [{ role: 'user', content }], stream: false, ...(generationConfig ? { generationConfig } : {}) });
    const videoBody = (model, content, durationSeconds, aspectRatio, mode) => body(model, content, { videoConfig: { durationSeconds, aspectRatio, mode } });

    function build(root, locale, recipeOptions = {}) {
        const p = prose[locale] || prose.en;
        const origin = String(root || 'http://localhost:8000');
        const parts = ['\n## ' + p.title + '\n\n' + (recipeOptions.intro || p.intro)];
        function section(key, snippets) {
            const copy = recipeOptions.copy?.[key] || p[key];
            parts.push('\n### ' + copy[0] + '\n\n' + copy.slice(1).join('\n\n') + '\n' + (snippets || ''));
        }
        section('setup', fence('bash', 'export FLOW2API_BASE_URL=' + "'" + origin.replace(/'/g, "'\\''") + "'" + '\nexport FLOW2API_API_KEY="REPLACE_WITH_SERVER_API_KEY"\ncurl --fail-with-body "$FLOW2API_BASE_URL/v1/models" -H "Authorization: Bearer $FLOW2API_API_KEY"\ncurl --fail-with-body "$FLOW2API_BASE_URL/v1/models/aliases" -H "Authorization: Bearer $FLOW2API_API_KEY"\ncurl --fail-with-body "$FLOW2API_BASE_URL/v1beta/models" -H "x-goog-api-key: $FLOW2API_API_KEY"') + fence('powershell', '$env:FLOW2API_BASE_URL = ' + "'" + origin.replace(/'/g, "''") + "'" + '\n$env:FLOW2API_API_KEY = "REPLACE_WITH_SERVER_API_KEY"\n$headers = @{ Authorization = "Bearer $env:FLOW2API_API_KEY" }\nInvoke-RestMethod "$env:FLOW2API_BASE_URL/v1/models" -Headers $headers\nInvoke-RestMethod "$env:FLOW2API_BASE_URL/v1/models/aliases" -Headers $headers'));
        section('image', json(body(imageModel, 'Create a cinematic photograph of a red bicycle beside a lake at sunrise.')) + fence('bash', 'curl --fail-with-body --max-time 3600 "$FLOW2API_BASE_URL/v1/chat/completions" \\\n  -H "Authorization: Bearer $FLOW2API_API_KEY" \\\n  -H "Content-Type: application/json" --data-binary @request.json') + fence('powershell', 'curl.exe --fail-with-body --max-time 3600 "$env:FLOW2API_BASE_URL/v1/chat/completions" -H "Authorization: Bearer $env:FLOW2API_API_KEY" -H "Content-Type: application/json" --data-binary "@request.json"'));
        section('edit', json(body(imageModel, [textPart('Keep the bicycle; change the background to a snowy forest.'), imagePart('https://YOUR_REACHABLE_HOST/reference.png')])) + fence('python', 'import base64, json\nfrom pathlib import Path\nencoded = base64.b64encode(Path("reference.png").read_bytes()).decode("ascii")\nrequest = {"model": "' + imageModel + '", "stream": False,\n    "generationConfig": {"imageConfig": {"aspectRatio": "16:9", "imageSize": "1K"}},\n    "messages": [{"role": "user", "content": [\n        {"type": "text", "text": "Keep the subject; change the background to a snowy forest."},\n        {"type": "image_url", "image_url": {"url": "data:image/png;base64," + encoded}}]}]}\nPath("edit.json").write_text(json.dumps(request), encoding="utf-8")'));
        section('dimensions', json({ ...body('gemini-3.1-flash-image', 'A vertical watercolor poster of a mountain village.'), generationConfig: { imageConfig: { aspectRatio: '9:16', imageSize: '2K' } } }));
        const frame = 'https://YOUR_REACHABLE_HOST/first.png';
        const last = 'https://YOUR_REACHABLE_HOST/last.png';
        section('video', '**T2V**\n' + json(videoBody('veo-3.1-fast', 'A red bicycle rolls slowly beside a lake, cinematic tracking shot.', 8, '16:9', 't2v')) + '**I2V: 1 image**\n' + json(videoBody('veo-3.1-lite', [textPart('Slowly orbit the subject.'), imagePart(frame)], 4, '16:9', 'i2v')) + '**I2V: first + last**\n' + json(videoBody('veo-3.1-quality', [textPart('Create a smooth transition from the first frame to the last frame.'), imagePart(frame), imagePart(last)], 6, '9:16', 'i2v')) + '**R2V: 1–3 images**\n' + json(videoBody('veo-3.1-fast', [textPart('Use these subjects in a coherent cinematic scene.'), imagePart(frame), imagePart(last)], 8, '16:9', 'r2v')) + '**Omni: 0–3 images**\n' + json(videoBody('omni-1.2-flash', [textPart('Animate this scene with a slow camera pan.'), imagePart(frame)], 8, '16:9', 'auto')) + '**Omni 1.1**\n' + json(videoBody('omni-1.1-flash', 'A cinematic mountain landscape at dawn.', 4, '9:16', 'auto')));
        section('extend', json(videoBody('veo-3.1-fast', [textPart('Continue the movement naturally, maintaining the same scene.'), imagePart('extend://REPLACE_WITH_FLOW_MEDIA_GENERATION_ID')], 8, '16:9', 'extend')));
        if (!recipeOptions.skipUpscale) section('upscale', json(body('veo_3_1_t2v_4s_1080p', 'A cinematic mountain landscape at dawn.')));
        section('gemini', json({ contents: [{ role: 'user', parts: [{ text: 'Paint the subject as a watercolor portrait.' }, { fileData: { mimeType: 'image/png', fileUri: frame } }] }], generationConfig: { imageConfig: { aspectRatio: '1:1', imageSize: '2K' } } }) + fence('json', '{"inlineData":{"mimeType":"image/png","data":"REPLACE_WITH_ACTUAL_BASE64_BYTES"}}') + fence('bash', 'curl --fail-with-body --max-time 3600 "$FLOW2API_BASE_URL/v1beta/models/gemini-3.1-flash-image:generateContent" \\\n  -H "x-goog-api-key: $FLOW2API_API_KEY" \\\n  -H "Content-Type: application/json" --data-binary @gemini.json\n# SSE: use :streamGenerateContent?alt=sse and curl -N') + fence('powershell', 'curl.exe --fail-with-body --max-time 3600 "$env:FLOW2API_BASE_URL/v1beta/models/gemini-3.1-flash-image:generateContent" -H "x-goog-api-key: $env:FLOW2API_API_KEY" -H "Content-Type: application/json" --data-binary "@gemini.json"'));
        section('geminiVideo', 'POST ' + origin + '/v1beta/models/omni-1.2-flash:generateContent\n' + json({ contents: [{ role: 'user', parts: [{ text: 'A slow cinematic flight over a mountain village.' }] }], generationConfig: { videoConfig: { durationSeconds: 8, aspectRatio: '16:9', mode: 'auto' } } }));
        section('js', fence('javascript', jsExample(origin)));
        section('python', fence('python', pythonExample()) + fence('python', 'import os\nfrom openai import OpenAI\nclient = OpenAI(api_key=os.environ["FLOW2API_API_KEY"],\n    base_url=os.environ["FLOW2API_BASE_URL"].rstrip("/") + "/v1",\n    timeout=3600.0, max_retries=0)\nresult = client.chat.completions.create(\n    model="omni-1.2-flash",\n    messages=[{"role": "user", "content": "A slow cinematic flight over a mountain village."}],\n    stream=False,\n    extra_body={"generationConfig": {"videoConfig": {"durationSeconds": 8, "aspectRatio": "16:9", "mode": "auto"}}})\nprint(result.choices[0].message.content)'));
        section('adapter', fence('javascript', String.raw`function renderMedia(content, target, serviceRoot) {
  // Accept only known output wrappers. Never execute returned HTML.
  const image = /!\[[^\]]*\]\(([^\r\n]+)\)/.exec(content);
  const video = /<video\b[^>]*\bsrc\s*=\s*(['"])(.*?)\1/i.exec(content);
  const raw = image ? image[1] : video ? video[2] : null;
  if (!raw) { target.textContent = content; return; }
  if (raw.startsWith('data:') &&
      (!image || !/^data:image\/(png|jpeg|webp|gif);base64,[a-z0-9+/=]+$/i.test(raw) || raw.length > 30_000_000))
    throw new Error('Unsupported inline media');
  const url = new URL(raw, serviceRoot + '/');
  const allowedOrigins = new Set([new URL(serviceRoot).origin]);
  // Add explicitly trusted upstream/CDN origins for your deployment here.
  if (url.protocol !== 'data:' &&
      (!['https:', 'http:'].includes(url.protocol) || !allowedOrigins.has(url.origin)))
    throw new Error('Media origin is not approved: ' + url.origin);
  const element = document.createElement(image ? 'img' : 'video');
  element.src = url.href;
  if (image) element.alt = 'Generated image';
  else element.controls = true;
  target.replaceChildren(element);
}
// renderMedia(finalContent, document.querySelector('#result'), ROOT);`));
        section('errors', json({ error: { message: 'Generation failed (example; inspect the actual message)', type: 'server_error', code: 'generation_failed', status_code: 503 } }) + json({ error: { code: 503, message: 'Generation failed (example)', status: 'UNAVAILABLE' } }));
        return parts.join('\n');
    }

    function jsExample(origin) {
        return `async function main() {
  const env = typeof process !== "undefined" ? process.env : {};
  const root = (env.FLOW2API_BASE_URL || ${JSON.stringify(origin)}).replace(new RegExp("/+$"), "");
  const key = env.FLOW2API_API_KEY || "REPLACE_WITH_SERVER_API_KEY";
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 3600_000);
  let finalContent = "";
  let sawDone = false;
  try {
    const response = await fetch(root + "/v1/chat/completions", {
      method: "POST", signal: controller.signal,
      headers: { Authorization: "Bearer " + key, "Content-Type": "application/json" },
      body: JSON.stringify({model: "gemini-3.1-flash-image", stream: true,
        generationConfig: {imageConfig: {aspectRatio: "16:9", imageSize: "1K"}},
        messages: [{role: "user", content: "A cinematic lake at sunrise."}]})
    });
    if (!response.ok) throw new Error("HTTP " + response.status + ": " + await response.text());
    if (!response.body || !response.headers.get("content-type")?.includes("text/event-stream"))
      throw new Error("Expected an SSE response");
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    function frame(block) {
      const data = block.split(/\\r?\\n/).filter(line => line.startsWith("data:"))
        .map(line => line.slice(5).replace(/^ /, "")).join("\\n");
      if (!data) return;
      if (data === "[DONE]") { sawDone = true; return; }
      const event = JSON.parse(data);
      if (event.error) throw new Error(JSON.stringify(event.error));
      for (const choice of event.choices || []) {
        const delta = choice.delta || {};
        if (typeof delta.reasoning_content === "string") console.log("progress:", delta.reasoning_content);
        if (typeof delta.content === "string") finalContent += delta.content;
      }
    }
    function drain(final = false) {
      let match;
      while ((match = /\\r?\\n\\r?\\n/.exec(buffer))) {
        frame(buffer.slice(0, match.index));
        buffer = buffer.slice(match.index + match[0].length);
      }
      if (final && buffer.trim()) { frame(buffer); buffer = ""; }
    }
    try {
      while (!sawDone) {
        const {value, done} = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, {stream: true});
        drain();
      }
      buffer += decoder.decode();
      drain(true);
    } finally { await reader.cancel().catch(() => {}); reader.releaseLock(); }
    if (!sawDone) throw new Error("Stream ended before [DONE]; inspect partial result before retrying");
    if (!finalContent) throw new Error("No final media content");
    console.log(finalContent); // Keep as text until media URLs are validated.
    return finalContent;
  } finally { clearTimeout(timer); }
}
main().catch(error => console.error(error));`;
    }

    function pythonExample() {
        return `import os
import requests

root = os.environ["FLOW2API_BASE_URL"].rstrip("/")
headers = {"Authorization": "Bearer " + os.environ["FLOW2API_API_KEY"]}
body = {"model": "gemini-3.1-flash-image", "stream": False,
        "generationConfig": {"imageConfig": {"aspectRatio": "16:9", "imageSize": "1K"}},
        "messages": [{"role": "user", "content": "A cinematic lake at sunrise."}]}
response = requests.post(root + "/v1/chat/completions", headers=headers,
                         json=body, timeout=(15, 3600))
if not response.ok:
    raise RuntimeError(f"HTTP {response.status_code}: {response.text}")
result = response.json()
if result.get("error"):
    raise RuntimeError(result["error"])
print(result["choices"][0]["message"]["content"])

# Alternative async adapter (run separately instead of the request above).
# import asyncio, httpx
# async def generate():
#     async with httpx.AsyncClient(timeout=httpx.Timeout(3600, connect=15)) as client:
#         r = await client.post(root + "/v1/chat/completions", headers=headers, json=body)
#         r.raise_for_status()
#         data = r.json()
#         if data.get("error"): raise RuntimeError(data["error"])
#         return data["choices"][0]["message"]["content"]
# print(asyncio.run(generate()))`;
    }

    const agentProse = {
        en: {
            title: 'Implement Flow2API in my existing application',
            mission: 'You are the coding agent working in my existing application. Inspect the current repository, identify its stack, provider architecture, generation workflows, configuration conventions and test commands, then actually implement a working Flow2API integration that fits this app. Do not stop at a plan, an explanation, a server setup guide or a standalone request example. Make the code changes and verify them. Preserve existing providers and unrelated behavior; choose reasonable implementation details from the repository and ask only for an essential missing product decision.',
            boundary: 'This handoff authorizes application integration work. Use the supplied service root and the generation API key placeholder below. Never read, print, copy or embed actual secret values from this machine, environment files, browser storage or server/account data. Add documented variable names and placeholders to the app’s existing secure configuration mechanism. Keep the API key on the application backend and redact it from logs; expose only nonsecret settings in browser UI. Do not deploy or operate the Flow2API server as part of this task.',
            stepsTitle: 'Implementation deliverables',
            steps: [
                'Inspect the app before editing: find existing OpenAI/Gemini adapters, provider registration, server/client boundaries, upload handling, result components, validation, error handling and tests. Reuse these extension points and the app’s language/framework instead of introducing a parallel demo.',
                'Implement and register a Flow2API provider/adapter. Support image generation, image editing and the video capabilities below through the app’s existing generation interface. If the app lacks a relevant surface, add the smallest coherent generation workflow in its current UI. Use server-side FLOW2API_BASE_URL and FLOW2API_API_KEY configuration with startup validation, example placeholders and a connection/discovery check using GET only.',
                'Implement configuration UI with all eight clean model families, clear image/video grouping, prompt and attachment controls, and separate typed aspect ratio, image size, video duration and mode selectors. Derive dependent choices from the exact rows below. Validate reference counts, frame order and extension source IDs before submission; hide or disable invalid combinations and explain validation errors. Do not ask users to assemble long concrete model IDs or edit JSON.',
                'Implement request mapping, long-running loading/progress states, completion and error states, safe image/video result rendering, download/open behavior and application cancellation controls. Keep progress separate from final media, preserve useful source media IDs for extension, and explain that closing the client request does not guarantee upstream cancellation.',
                'Add meaningful mock/fixture tests for provider registration, secure configuration, payload mapping, dependent selector validation, attachment handling, response/SSE parsing, safe rendering and error states. Run the relevant existing checks and new tests. Do not submit paid image/video generation during integration tests; mock HTTP/SSE responses. Live generation requires a separate explicit user request.',
                'Finish with a concise report of files changed, setup variables, supported workflows, checks run and any verified limitations. Include a small usage walkthrough in the app’s normal documentation. Continue until the implementation and checks are complete; report a concrete blocker if one truly prevents completion.'
            ],
            connectionTitle: 'Connection and protocol contract',
            connection: 'ROOT includes any reverse-proxy prefix and excludes /v1. Preserve this prefix when joining every route. Prefer OpenAI-compatible POST /v1/chat/completions with Authorization: Bearer <generation API key>; an OpenAI SDK base_url is ROOT + /v1. Gemini-compatible POST /v1beta/models/{family}:generateContent or :streamGenerateContent uses x-goog-api-key and the same generationConfig. Discover with GET /v1/models, /v1/models/aliases or /v1beta/models using generation credentials. Discovery may fail independently of generation: show a useful connection error and allow explicit supported family selection. Availability can still depend on upstream account access. This adapter generates media; do not route normal chat, tools, embeddings, Responses or OpenAI Images methods to it.',
            modelsTitle: 'Model families and exact selectable combinations',
            models: 'Use the clean family as model and send options separately. These compact tables are derived from the supplied model_parameters registry snapshot, not from independent value lists. Every combination within one row is registered; combinations across rows are not implied. Keep these correlations when implementing dependent selectors and validation. Unspecified reference maxima mean the registry does not declare a ceiling, not an unlimited upstream guarantee. The literal local min annotation reports a weaker local check; keep the advertised R2V minimum in UI.',
            typesTitle: 'Typed parameters',
            types: 'Image: generationConfig.imageConfig.aspectRatio is a string; imageSize is a string enum (1K, 2K, 4K where listed). Video: generationConfig.videoConfig.durationSeconds is an integer, aspectRatio is a string and mode is a string enum (t2v, i2v, r2v, auto, extend where listed). Do not send imageConfig to a video family or videoConfig to an image family. Canonical videoConfig accepts only durationSeconds/aspectRatio/mode. In the OpenAI SDK, use extra_body={"generationConfig": ...}; the SDK merges it into the outgoing body. Unsupported video tuples return HTTP 400; malformed typed bodies return HTTP 422. Present server validation errors and preserve the user’s input; never silently coerce a request to a different mode, duration or family.',
            imageHeaders: ['Image family', 'aspectRatio', 'imageSize', 'Reference images'],
            videoHeaders: ['Video family', 'mode', 'aspectRatio', 'durationSeconds (integer)', 'Reference images'],
            defaultsTitle: 'Registered defaults',
            defaults: 'Apply the defaults below, changing dependent options when mode changes. Image aliases without an explicit aspect can infer shape from the first reference image, otherwise they default to 16:9; send explicit selections for a predictable UI. Explicit concrete/legacy model IDs retain their configured behavior. The current clean video families do not expose arbitrary output resolution or standalone video upscaling.',
            inputsTitle: 'Inputs, outputs and operational behavior of the client',
            inputs: 'Send a nonempty prompt. OpenAI attachments are message content parts with type=image_url and image_url.url containing a server-reachable HTTPS URL or a data:image/...;base64,... URI with actual bytes; never send a client filesystem path. Convert local files in the app and validate MIME type/size. Gemini uses fileData.fileUri or inlineData {mimeType,data}, with raw base64 in inlineData.data. Only the last OpenAI message supplies the main prompt/direct images and the last Gemini user content is used. I2V accepts 1–2 ordered first/last frames; R2V uses subject/style references, not frame interpolation. Omni auto chooses the text/reference path from 0–3 images. T2V takes no images. Extension takes an existing Flow mediaGenerationId in an OpenAI image_url marker extend://ID; no arbitrary video upload/MP4 URL or Gemini extension is supported. Keep data-media-id from streaming output when available; a normal nonstream response has no structured source ID, and there is no public media-ID lookup endpoint. Disable extension until a valid retained source ID is available.',
            runtime: 'OpenAI nonstream results use choices[0].message.content containing Markdown images or a video HTML wrapper (sometimes fenced), not an Images data array. SSE carries delta.reasoning_content progress, delta.content final media and [DONE]; buffer UTF-8 and SSE frame boundaries across network chunks, handle CRLF and final partial frames, and detect missing completion, empty output and in-stream errors even with HTTP 200. Gemini uses candidates[].content.parts inlineData/fileData and text progress. Parse media destinations and create safe img/video elements with controls; never execute returned HTML with innerHTML. Validate URL schemes/origins and bounded image data URIs; handle relative cache URLs, unreachable localhost, expiring links and downloads according to the app’s policy.',
            reliability: 'Use long generation timeouts (examples: 3600 seconds; server defaults are commonly 300 image/1500 video seconds), coordinate app/proxy timeouts and avoid SSE buffering. Handle 401 authentication, 400/422 validation, 403 access, 429 rate limits and 5xx upstream/unavailable failures using actual error payloads ({detail:...}, OpenAI error, Gemini error). Surface actionable errors without keys. No public job polling, upstream cancellation or idempotency-key guarantee is provided. Disable automatic generation POST retries, including SDK retries; a timeout/disconnect can leave paid work running. Do not blindly retry POST or promise that a retry is free/deduplicated. Bounded GET discovery retries are suitable; let users inspect state before deliberately submitting again.',
            acceptanceTitle: 'Acceptance criteria',
            acceptance: 'The app exposes a usable Flow2API provider, secure configuration and a visible generation workflow; all eight family names are supported independently of the example currently shown in this guide; separate controls admit only registered tuples and valid references; final media and progress/errors render correctly; secrets stay server-side; mocked success, validation/auth failure, fragmented SSE, in-stream error and cancellation/timeout behavior pass relevant checks. Report any application-specific limitation explicitly. No paid generation is required to complete this integration.',
            recipesIntro: 'Use the following runnable requests and parsers as implementation fixtures. Adapt them to the existing app’s stack, provider interface and secure backend; they are not the deliverable by themselves. Choose only combinations from the tables above. Commands that submit generation are reference examples, not instructions to run paid integration tests.',
            setup: ['Backend environment and discovery fixtures', 'Add FLOW2API_BASE_URL and FLOW2API_API_KEY to the app’s existing backend configuration, with the supplied root and a placeholder in example files. Complete implementation and mock tests without requesting or inspecting a real key; the operator can inject the generation API key securely afterwards. The runtime adapter may load it through the normal server configuration API. ROOT includes any proxy prefix, without /v1; OpenAI SDK base_url appends /v1 once. Use Bearer or x-goog-api-key headers. Query key authentication is accepted but URLs may be logged; precedence is Bearer, then x-goog-api-key, then ?key=. A wrong Bearer key is not rescued by a correct query key. The shell examples below illustrate configuration and read-only discovery.'],
            js: ['JavaScript: backend fetch and SSE fixture', 'Adapt this parser to the app’s backend fetch implementation (Node 18+ or an equivalent runtime). Keep the service key in server configuration; the fallback key is only a placeholder for this fixture. The parser buffers UTF-8 and SSE frames across chunks, handles CRLF, [DONE], final partial frames, HTTP errors and in-stream JSON errors. reasoning_content is progress, not final media. AbortController closes the client request without guaranteeing upstream cancellation or refund.'],
            extend: ['Extend a retained Flow video', 'Use an existing Flow mediaGenerationId, not a chatcmpl ID, task ID, MP4 URL or arbitrary uploaded video. Send extend://ID in an OpenAI image_url part. Retain data-media-id from streaming output when available. Ordinary nonstream output has no structured source media ID, and this adapter has no public upload-video or media-ID lookup route. If no valid retained source ID exists, explain the limitation and disable extension. Gemini does not forward this marker; use OpenAI.']
        },
        vi: {
            title: 'Triển khai Flow2API vào ứng dụng hiện có của tôi',
            mission: 'Bạn là coding agent làm việc trong ứng dụng hiện có của tôi. Hãy đọc repository, xác định stack, kiến trúc provider, luồng tạo nội dung, quy ước cấu hình và lệnh kiểm tra, rồi thực sự triển khai tích hợp Flow2API phù hợp với ứng dụng. Không dừng ở kế hoạch, giải thích, tài liệu quản trị máy chủ hay ví dụ request riêng lẻ. Hãy sửa mã và xác minh kết quả. Giữ các provider hiện có và hành vi không liên quan; tự quyết các chi tiết hợp lý theo repository, chỉ hỏi khi thiếu quyết định sản phẩm thiết yếu.',
            boundary: 'Phạm vi này cho phép tích hợp vào ứng dụng. Dùng gốc dịch vụ và placeholder generation API key bên dưới. Không đọc, in, sao chép hoặc nhúng giá trị secret thật từ máy, file môi trường, browser storage hay dữ liệu tài khoản/máy chủ. Chỉ thêm tên biến được mô tả và placeholder vào cơ chế cấu hình bảo mật hiện có. Giữ API key tại backend ứng dụng, che key trong log; UI trình duyệt chỉ hiển thị cấu hình không bí mật. Không triển khai hay vận hành máy chủ Flow2API trong tác vụ này.',
            stepsTitle: 'Các phần phải triển khai',
            steps: [
                'Đọc ứng dụng trước khi sửa: tìm adapter OpenAI/Gemini, đăng ký provider, ranh giới server/client, upload, component kết quả, validation, xử lý lỗi và tests. Dùng điểm mở rộng và ngôn ngữ/framework hiện có thay vì tạo demo tách rời.',
                'Triển khai và đăng ký provider/adapter Flow2API. Hỗ trợ tạo ảnh, sửa ảnh và các khả năng video dưới đây qua giao diện tạo nội dung hiện có. Nếu chưa có màn hình phù hợp, thêm luồng nhỏ nhất nhưng hoàn chỉnh theo UI hiện tại. Dùng FLOW2API_BASE_URL và FLOW2API_API_KEY phía server, kiểm tra cấu hình khi khởi động, thêm placeholder mẫu và kiểm tra kết nối/khám phá model chỉ bằng GET.',
                'Triển khai UI cấu hình đủ tám dòng model ngắn, phân nhóm ảnh/video rõ ràng, prompt, đính kèm ảnh và các control riêng có kiểu cho tỉ lệ, kích thước ảnh, thời lượng video, mode. Suy ra lựa chọn phụ thuộc từ các hàng hợp lệ bên dưới. Kiểm tra số ảnh, thứ tự khung và ID nguồn nối dài trước khi gửi; ẩn hoặc vô hiệu hóa tổ hợp sai và giải thích lỗi. Không bắt người dùng ghép ID model dài hay sửa JSON.',
                'Triển khai ánh xạ request, trạng thái chờ/tiến trình dài, thành công/lỗi, render ảnh/video an toàn, tải xuống/mở kết quả và thao tác hủy phía ứng dụng. Tách tiến trình khỏi media cuối, giữ media ID nguồn hữu ích cho nối dài và giải thích rằng đóng request không bảo đảm hủy tác vụ upstream.',
                'Thêm tests mock/fixture có ý nghĩa cho đăng ký provider, cấu hình bảo mật, payload, lựa chọn phụ thuộc, ảnh đính kèm, parser response/SSE, render an toàn và trạng thái lỗi. Chạy kiểm tra hiện có liên quan và tests mới. Không tạo ảnh/video tính phí trong tests tích hợp; mock HTTP/SSE. Tạo thật cần yêu cầu rõ ràng riêng của người dùng.',
                'Hoàn tất bằng báo cáo ngắn về file đã sửa, biến cấu hình, luồng hỗ trợ, kiểm tra đã chạy và giới hạn đã xác minh. Thêm hướng dẫn dùng ngắn vào tài liệu thông thường của ứng dụng. Tiếp tục tới khi mã và kiểm tra hoàn tất; nếu thực sự bị chặn, báo nguyên nhân cụ thể.'
            ],
            connectionTitle: 'Hợp đồng kết nối và giao thức',
            connection: 'ROOT gồm tiền tố reverse proxy nếu có và không gồm /v1. Giữ nguyên tiền tố khi ghép mọi route. Ưu tiên OpenAI-compatible POST /v1/chat/completions với Authorization: Bearer <generation API key>; base_url OpenAI SDK là ROOT + /v1. Gemini-compatible POST /v1beta/models/{family}:generateContent hoặc :streamGenerateContent dùng x-goog-api-key và cùng generationConfig. Khám phá qua GET /v1/models, /v1/models/aliases hoặc /v1beta/models bằng generation key. Khám phá có thể lỗi riêng: hiển thị lỗi kết nối hữu ích và cho chọn dòng hợp lệ tường minh. Quyền truy cập còn phụ thuộc upstream. Adapter tạo media; không gửi hội thoại thường, tools, embeddings, Responses hay phương thức OpenAI Images vào đây.',
            modelsTitle: 'Dòng model và tổ hợp lựa chọn chính xác',
            models: 'Dùng tên dòng ngắn làm model và gửi tham số riêng. Bảng gọn này được suy từ snapshot registry model_parameters đã cung cấp, không phải ghép các danh sách giá trị độc lập. Mọi tổ hợp trong một hàng có đăng ký; không suy thêm tổ hợp giữa các hàng. Giữ quan hệ này trong control phụ thuộc và validation. Max ảnh unspecified nghĩa registry chưa khai báo giới hạn, không bảo đảm upstream vô hạn. Chú thích local min là mức kiểm tra cục bộ yếu hơn; UI vẫn giữ tối thiểu R2V được công bố.',
            typesTitle: 'Tham số có kiểu',
            types: 'Ảnh: generationConfig.imageConfig.aspectRatio là string; imageSize là string enum (1K, 2K, 4K nếu có trong bảng). Video: generationConfig.videoConfig.durationSeconds là integer, aspectRatio là string và mode là string enum (t2v, i2v, r2v, auto, extend nếu có trong bảng). Không gửi imageConfig cho video hay videoConfig cho ảnh. videoConfig chuẩn chỉ nhận durationSeconds/aspectRatio/mode. Với OpenAI SDK, dùng extra_body={"generationConfig": ...}; SDK gộp vào body gửi đi. Tổ hợp video không hỗ trợ trả HTTP 400; body sai kiểu trả HTTP 422. Hiển thị lỗi validation của server, giữ input người dùng; không tự đổi mode, thời lượng hay dòng model.',
            imageHeaders: ['Dòng ảnh', 'aspectRatio', 'imageSize', 'Ảnh tham chiếu'],
            videoHeaders: ['Dòng video', 'mode', 'aspectRatio', 'durationSeconds (integer)', 'Ảnh tham chiếu'],
            defaultsTitle: 'Mặc định đã đăng ký',
            defaults: 'Áp dụng mặc định bên dưới, đổi lựa chọn phụ thuộc khi mode đổi. Alias ảnh thiếu tỉ lệ có thể suy từ ảnh đầu tiên, nếu không có thì dùng 16:9; gửi lựa chọn tường minh để UI nhất quán. ID biến thể/legacy tường minh giữ hành vi đã cấu hình. Các dòng video ngắn hiện không cung cấp độ phân giải tùy ý hoặc phóng một video có sẵn.',
            inputsTitle: 'Đầu vào, đầu ra và hành vi phía ứng dụng',
            inputs: 'Gửi prompt không rỗng. Ảnh OpenAI là content part type=image_url, image_url.url chứa HTTPS mà server tải được hoặc data:image/...;base64,... chứa byte thật; không gửi đường dẫn file trên máy client. Chuyển file cục bộ trong ứng dụng, kiểm tra MIME/kích thước. Gemini dùng fileData.fileUri hoặc inlineData {mimeType,data}, inlineData.data chỉ chứa base64 thuần. Chỉ tin nhắn OpenAI cuối cung cấp prompt/ảnh trực tiếp và Gemini dùng user content cuối. I2V nhận 1–2 khung theo thứ tự đầu/cuối; R2V dùng ảnh tham chiếu chủ thể/phong cách, không phải nội suy khung. Omni auto chọn nhánh chữ/ảnh theo 0–3 ảnh. T2V không nhận ảnh. Nối dài cần mediaGenerationId Flow hiện có qua marker OpenAI image_url extend://ID; không hỗ trợ upload video bất kỳ, URL MP4 hay nối dài Gemini. Giữ data-media-id khi có trong stream; nonstream thường không có source ID có cấu trúc và không có endpoint public tra media ID. Vô hiệu hóa nối dài khi chưa có source ID hợp lệ đã giữ lại.',
            runtime: 'Kết quả OpenAI nonstream nằm trong choices[0].message.content, chứa Markdown ảnh hoặc HTML video (đôi khi trong code fence), không phải mảng data của Images. SSE có delta.reasoning_content cho tiến trình, delta.content cho media cuối và [DONE]; buffer UTF-8 và khung SSE qua các network chunk, xử lý CRLF, khung cuối chưa ngắt dòng, thiếu hoàn tất, output rỗng và lỗi trong stream dù HTTP 200. Gemini dùng candidates[].content.parts inlineData/fileData và text tiến trình. Parse URL media rồi tạo img/video an toàn có controls; không chạy HTML trả về bằng innerHTML. Kiểm tra scheme/origin và giới hạn data URI ảnh; xử lý URL cache tương đối, localhost không truy cập được, link hết hạn và tải xuống theo chính sách ứng dụng.',
            reliability: 'Dùng timeout tạo nội dung dài (ví dụ 3600 giây; mặc định server thường là 300 giây ảnh/1500 giây video), phối hợp timeout ứng dụng/proxy và tránh buffer SSE. Xử lý 401 xác thực, 400/422 validation, 403 quyền, 429 giới hạn tốc độ và 5xx upstream/không sẵn sàng theo payload thật ({detail:...}, OpenAI error, Gemini error). Hiển thị lỗi có hành động xử lý, không lộ key. Không có bảo đảm public về polling job, hủy upstream hay idempotency-key. Tắt retry POST tạo nội dung tự động kể cả SDK; timeout/mất kết nối có thể để tác vụ tính phí tiếp tục. Không retry POST mù quáng hoặc hứa miễn phí/khử trùng lặp. GET khám phá có thể retry giới hạn; cho người dùng xem trạng thái trước khi chủ động gửi lại.',
            acceptanceTitle: 'Tiêu chí nghiệm thu',
            acceptance: 'Ứng dụng có provider Flow2API dùng được, cấu hình bảo mật và luồng tạo nội dung nhìn thấy được; hỗ trợ đủ tám tên dòng độc lập với ví dụ đang hiển thị trong hướng dẫn; control riêng chỉ cho tổ hợp đã đăng ký và ảnh hợp lệ; media cuối, tiến trình/lỗi hiển thị đúng; secret ở server; các kiểm tra mock thành công, lỗi validation/xác thực, SSE bị chia nhỏ, lỗi trong stream và hủy/timeout đều đạt. Báo rõ giới hạn riêng của ứng dụng. Không cần tạo nội dung tính phí để hoàn tất tích hợp.',
            recipesIntro: 'Dùng request và parser chạy được dưới đây làm fixture triển khai. Điều chỉnh theo stack, giao diện provider và backend bảo mật của ứng dụng; riêng ví dụ không phải sản phẩm bàn giao. Chỉ chọn tổ hợp từ bảng trên. Lệnh tạo nội dung là tài liệu tham khảo, không phải yêu cầu chạy tests tích hợp tính phí.',
            setup: ['Fixture môi trường backend và khám phá model', 'Thêm FLOW2API_BASE_URL và FLOW2API_API_KEY vào cấu hình backend hiện có, dùng gốc dịch vụ đã cho và placeholder trong file mẫu. Hoàn tất mã và tests mock mà không yêu cầu hoặc xem key thật; người vận hành có thể cấu hình generation API key an toàn sau đó. Adapter lúc chạy có thể nạp key qua API cấu hình server thông thường. ROOT gồm tiền tố proxy, không có /v1; base_url OpenAI SDK chỉ thêm /v1 một lần. Dùng header Bearer hoặc x-goog-api-key. Hệ thống nhận query key nhưng URL có thể bị log; ưu tiên Bearer, rồi x-goog-api-key, rồi ?key=. Bearer sai không được cứu bởi query key đúng. Ví dụ shell dưới minh họa cấu hình và khám phá chỉ đọc.'],
            js: ['JavaScript: fixture fetch backend và SSE', 'Điều chỉnh parser theo fetch backend của ứng dụng (Node 18+ hoặc runtime tương đương). Giữ key dịch vụ trong cấu hình server; key dự phòng chỉ là placeholder của fixture. Parser buffer UTF-8 và khung SSE qua các chunk, xử lý CRLF, [DONE], khung cuối, lỗi HTTP và lỗi JSON trong stream. reasoning_content là tiến trình, không phải media cuối. AbortController đóng request phía client, không bảo đảm hủy upstream hay hoàn phí.'],
            extend: ['Nối dài video Flow đã giữ ID', 'Dùng mediaGenerationId Flow hiện có, không dùng chatcmpl ID, task ID, URL MP4 hay video upload bất kỳ. Gửi extend://ID trong part OpenAI image_url. Giữ data-media-id từ stream khi có. Nonstream thường không có source media ID có cấu trúc; adapter không có route public upload-video hoặc tra media ID. Khi chưa có source ID hợp lệ đã giữ, giải thích giới hạn và vô hiệu hóa nối dài. Gemini không chuyển marker này; dùng OpenAI.']
        },
        'zh-CN': {
            title: '将 Flow2API 实际集成到我的现有应用',
            mission: '你是在我的现有应用中工作的 coding agent。先检查当前 repository，确定技术栈、provider 架构、生成流程、配置惯例和测试命令，然后实际实现符合该应用的 Flow2API 集成。不要停留在计划、解释、服务器运维文档或单独的请求示例。修改代码并验证结果。保留现有 provider 和无关行为；根据仓库合理决定实现细节，仅在缺少必要产品决策时提问。',
            boundary: '本任务授权应用集成工作。使用下面给出的服务根地址和 generation API key 占位符。不要读取、打印、复制或嵌入本机、环境文件、浏览器存储或服务器/账户数据中的真实 secret。仅在应用现有安全配置机制中加入已说明的变量名和占位符。API key 保留在应用后端，日志应脱敏；浏览器 UI 仅显示非秘密设置。本任务不包括部署或运维 Flow2API 服务器。',
            stepsTitle: '必须交付的实现',
            steps: [
                '修改前先检查应用：查找现有 OpenAI/Gemini adapter、provider 注册、服务端/客户端边界、上传、结果组件、校验、错误处理和测试。复用现有扩展点及语言/框架，将集成融入应用。',
                '实现并注册 Flow2API provider/adapter。通过现有生成接口支持图片生成、图片编辑及下方视频能力。若缺少相关界面，按当前 UI 增加最小但完整的生成流程。服务端使用 FLOW2API_BASE_URL 和 FLOW2API_API_KEY，校验启动配置、提供示例占位符，并仅用 GET 检查连接和发现模型。',
                '实现配置 UI，包含全部八个简洁模型系列、清晰的图片/视频分组、提示词、图片附件，以及独立且有类型的宽高比、图片尺寸、视频时长和 mode 控件。根据下方准确表格生成联动选项。提交前校验图片数量、帧顺序和续写源 ID；隐藏或禁用非法组合并说明校验错误。不要要求用户拼接长模型 ID 或编辑 JSON。',
                '实现请求映射、长时间等待/进度、成功/错误状态、安全图片/视频展示、下载/打开行为及应用取消控件。将进度与最终媒体分开，保留可用于续写的源媒体 ID，并说明关闭客户端请求不能保证取消上游任务。',
                '为 provider 注册、安全配置、请求映射、联动选项校验、附件处理、response/SSE 解析、安全展示和错误状态加入有意义的 mock/fixture 测试。运行相关现有检查和新测试。集成测试不得提交付费图片/视频生成；使用 mock HTTP/SSE 响应。真实生成需要用户另行明确要求。',
                '最终简要报告修改文件、配置变量、支持流程、运行检查及已验证限制。在应用常规文档中加入简短使用说明。持续完成实现和检查；如果确实无法继续，报告具体阻塞原因。'
            ],
            connectionTitle: '连接与协议约定',
            connection: 'ROOT 包含反向代理前缀，不包含 /v1。拼接所有路由时保留此前缀。优先使用 OpenAI-compatible POST /v1/chat/completions，设置 Authorization: Bearer <generation API key>；OpenAI SDK base_url 为 ROOT + /v1。Gemini-compatible POST /v1beta/models/{family}:generateContent 或 :streamGenerateContent 使用 x-goog-api-key 和相同 generationConfig。使用 generation key 请求 GET /v1/models、/v1/models/aliases 或 /v1beta/models 发现模型。发现请求可能单独失败：显示有用的连接错误并允许明确选择受支持系列。可用性还受上游账户权限影响。该 adapter 用于媒体生成，不应接收普通聊天、tools、embeddings、Responses 或 OpenAI Images 方法。',
            modelsTitle: '模型系列与准确可选组合',
            models: 'model 使用简洁系列名，选项单独传递。下方紧凑表格来自提供的 model_parameters 注册快照，不是独立值列表的任意组合。同一行内的组合均已注册，不代表可以跨行组合。联动选项和校验必须保留这些关联。图片上限 unspecified 表示 registry 未声明上限，不保证上游无限制。local min 字样表示较宽松的本地检查；UI 仍应采用公布的 R2V 最少图片数。',
            typesTitle: '有类型的参数',
            types: '图片：generationConfig.imageConfig.aspectRatio 为 string；imageSize 为 string enum（仅表中列出的 1K、2K、4K）。视频：generationConfig.videoConfig.durationSeconds 为 integer，aspectRatio 为 string，mode 为 string enum（仅表中列出的 t2v、i2v、r2v、auto、extend）。不要向视频系列发送 imageConfig，也不要向图片系列发送 videoConfig。标准 videoConfig 仅接受 durationSeconds/aspectRatio/mode。OpenAI SDK 使用 extra_body={"generationConfig": ...}，SDK 会将其合并至发送正文。不支持的视频组合返回 HTTP 400；类型或结构错误返回 HTTP 422。显示服务器校验错误并保留用户输入；不要悄悄更改 mode、时长或系列。',
            imageHeaders: ['图片系列', 'aspectRatio', 'imageSize', '参考图片数'],
            videoHeaders: ['视频系列', 'mode', 'aspectRatio', 'durationSeconds (integer)', '参考图片数'],
            defaultsTitle: '已注册默认值',
            defaults: '采用下方默认值，切换 mode 时更新联动选项。图片别名未明确提供宽高比时可从第一张参考图推断，否则默认 16:9；为可预测的 UI 应明确传入选择。具体变体/旧 ID 保留已有配置行为。当前简洁视频系列不提供任意输出分辨率或独立视频放大接口。',
            inputsTitle: '输入、输出及客户端行为',
            inputs: '发送非空提示词。OpenAI 附件为 type=image_url 的 message content part，image_url.url 包含服务器可访问的 HTTPS 地址或带真实字节的 data:image/...;base64,... URI；不要发送客户端文件路径。在应用中转换本地文件并校验 MIME/大小。Gemini 使用 fileData.fileUri 或 inlineData {mimeType,data}，inlineData.data 只放原始 base64。OpenAI 仅最后一条消息提供主要提示词/直接图片，Gemini 使用最后一条 user content。I2V 接受按首帧/末帧顺序排列的 1–2 张图；R2V 使用主体/风格参考图，不是首尾帧插值。Omni auto 根据 0–3 张图片选择文生/参考图路径。T2V 不接收图片。续写需要现有 Flow mediaGenerationId，通过 OpenAI image_url 标记 extend://ID 传入；不支持任意视频上传、MP4 URL 或 Gemini 续写。流式结果提供 data-media-id 时应保留；普通非流式没有结构化源 ID，也无公开媒体 ID 查询端点。没有保留的有效源 ID 时禁用续写。',
            runtime: 'OpenAI 非流式结果位于 choices[0].message.content，包含 Markdown 图片或 video HTML 包装（可能在代码围栏中），不是 Images data 数组。SSE 通过 delta.reasoning_content 发送进度、delta.content 发送最终媒体，并以 [DONE] 结束；跨网络块缓存 UTF-8 和 SSE 帧，处理 CRLF、最后未分隔帧、未完成、空输出和 HTTP 200 中的流内错误。Gemini 使用 candidates[].content.parts 的 inlineData/fileData 及进度文本。解析媒体地址并创建带 controls 的安全 img/video 元素；不要通过 innerHTML 执行返回的 HTML。校验 URL scheme/origin 和受限图片 data URI；按照应用策略处理相对缓存 URL、不可达 localhost、过期链接和下载。',
            reliability: '配置长生成超时（示例 3600 秒；服务器常见默认值为图片 300 秒/视频 1500 秒），协调应用/代理超时并避免 SSE 缓冲。根据实际错误正文（{detail:...}、OpenAI error、Gemini error）处理 401 认证、400/422 校验、403 权限、429 限流及 5xx 上游/不可用错误。提供可操作提示，避免泄露 key。没有公开 job polling、上游取消或 idempotency-key 保证。禁用生成 POST 自动重试，包括 SDK 重试；超时/断线可能留下正在付费运行的任务。不要盲目重试 POST，也不要承诺免费或去重。发现 GET 可有限重试；让用户检查状态后再主动重新提交。',
            acceptanceTitle: '验收标准',
            acceptance: '应用具有可用的 Flow2API provider、安全配置和可见生成流程；全部八个系列均可用，不受本指南当前示例选择影响；独立控件只允许已注册组合和有效参考图片；正确显示最终媒体、进度和错误；secret 保留在服务端；mock 成功、校验/认证失败、碎片化 SSE、流内错误及取消/超时行为通过相关检查。明确报告应用特定限制。完成集成不需要付费生成。',
            recipesIntro: '将下方可运行请求和 parser 作为实现 fixture，按现有应用的技术栈、provider 接口及安全后端调整；单独示例本身不是交付结果。仅使用上表列出的组合。生成命令是参考示例，不是运行付费集成测试的指令。',
            setup: ['后端环境与发现 fixture', '在应用现有后端配置中加入 FLOW2API_BASE_URL 和 FLOW2API_API_KEY，示例文件使用给定根地址及占位符。完成代码和 mock 测试时不要索取或查看真实 key；操作人员之后可安全注入 generation API key。运行时 adapter 可通过常规服务器配置 API 加载它。ROOT 包含代理前缀，不含 /v1；OpenAI SDK base_url 只追加一次 /v1。使用 Bearer 或 x-goog-api-key header。也接受 query key，但 URL 可能被记录；优先级为 Bearer、x-goog-api-key、?key=。错误 Bearer 不能被正确 query key 补救。下方 shell 示例用于说明配置和只读发现。'],
            js: ['JavaScript：后端 fetch 与 SSE fixture', '将 parser 适配到应用后端 fetch 实现（Node 18+ 或等价运行时）。服务 key 保留在服务器配置中；回退 key 仅为 fixture 占位符。parser 跨 chunk 缓存 UTF-8 和 SSE 帧，处理 CRLF、[DONE]、最后部分帧、HTTP 错误及流内 JSON 错误。reasoning_content 是进度，不是最终媒体。AbortController 仅关闭客户端请求，不能保证取消上游或退款。'],
            extend: ['续写已保留 ID 的 Flow 视频', '使用现有 Flow mediaGenerationId，不要使用 chatcmpl ID、任务 ID、MP4 URL 或任意上传视频。在 OpenAI image_url part 中发送 extend://ID。有流式 data-media-id 时保留它。普通非流式没有结构化源媒体 ID；adapter 无公开 upload-video 或媒体 ID 查询路由。没有已保留的有效源 ID 时说明限制并禁用续写。Gemini 不转发该标记；请使用 OpenAI。']
        }
    };

    const cleanFamilies = [
        'gemini-3.0-pro-image', 'gemini-3.1-flash-image', 'gemini-3.1-flash-lite-image',
        'veo-3.1-fast', 'veo-3.1-lite', 'veo-3.1-quality', 'omni-1.1-flash', 'omni-1.2-flash'
    ];
    const contractRatios = ['16:9', '9:16', '1:1', '4:3', '3:4'];
    const contractModes = ['t2v', 'i2v', 'r2v', 'auto', 'extend'];

    function serviceRoot(value) {
        // A shared prompt must not leak a URL password, query key, or fragment.
        // Encoding backticks also prevents a crafted prefix closing code fences.
        const url = new URL(String(value || 'http://localhost:8000'));
        if (!['http:', 'https:'].includes(url.protocol)) throw new TypeError('Flow2API root must be HTTP(S)');
        url.username = '';
        url.password = '';
        url.search = '';
        url.hash = '';
        url.pathname = url.pathname.replace(/`/g, '%60').replace(/\/+$/, '').replace(/\/(?:v1|v1beta)$/, '');
        return url.href.replace(/\/+$/, '');
    }

    function markdownTable(headers, rows) {
        return [headers, headers.map(() => '---'), ...rows]
            .map(row => '| ' + row.join(' | ') + ' |').join('\n');
    }

    function referenceBounds(variant) {
        const minimum = Number.isInteger(variant.min_images) && variant.min_images >= 0 ? variant.min_images : 0;
        const maximum = Number.isInteger(variant.max_images) && variant.max_images >= minimum ? variant.max_images : 'unspecified';
        const local = Number.isInteger(variant.locally_validated_min_images) && variant.locally_validated_min_images >= 0
            ? variant.locally_validated_min_images : minimum;
        return minimum + '–' + maximum + (local !== minimum ? ' (local min ' + local + ')' : '');
    }

    function compactContractRows(contract) {
        const video = contract.type === 'video';
        const variants = contract.variants.filter(item => contractRatios.includes(item.aspectRatio)
            && (video ? contractModes.includes(item.mode) && Number.isInteger(item.durationSeconds) && item.durationSeconds > 0
                : ['1K', '2K', '4K'].includes(item.imageSize)));
        const rows = [];
        // Group within one aspect first, then combine aspects only when their
        // full value sets AND reference bounds match. Sparse registries cannot
        // accidentally become a Cartesian product of independent parameters.
        for (const mode of video ? contractModes : ['image']) {
            const groups = new Map();
            for (const ratio of contractRatios) {
                const bounds = new Map();
                for (const item of variants.filter(item => item.aspectRatio === ratio && (!video || item.mode === mode))) {
                    const refs = referenceBounds(item);
                    if (!bounds.has(refs)) bounds.set(refs, new Set());
                    bounds.get(refs).add(video ? item.durationSeconds : item.imageSize);
                }
                for (const [refs, valueSet] of bounds) {
                    const values = Array.from(valueSet).sort(video ? (a, b) => a - b : (a, b) => parseInt(a, 10) - parseInt(b, 10));
                    const key = JSON.stringify([values, refs]);
                    if (!groups.has(key)) groups.set(key, { aspects: [], values, refs });
                    groups.get(key).aspects.push(ratio);
                }
            }
            for (const group of groups.values()) {
                rows.push(video ? [contract.id, mode, group.aspects.join(', '), group.values.join(', '), group.refs]
                    : [contract.id, group.aspects.join(', '), group.values.join(', '), group.refs]);
            }
        }
        return rows;
    }

    function formatDefaults(contract) {
        const format = value => {
            const fields = contract.type === 'video' ? ['durationSeconds', 'aspectRatio', 'mode'] : ['aspectRatio', 'imageSize'];
            if (!value || !contract.variants.some(item => fields.every(key => item[key] === value[key]))
                || !contractRatios.includes(value.aspectRatio)
                || (contract.type === 'video' ? !contractModes.includes(value.mode) || !Number.isInteger(value.durationSeconds)
                    : !['1K', '2K', '4K'].includes(value.imageSize))) return 'unspecified';
            return fields.map(key => key + '=' + value[key]).join(', ');
        };
        const main = '- ' + contract.id + ': ' + format(contract.defaults);
        const modes = contract.type === 'video' ? contractModes.filter(mode => contract.mode_defaults?.[mode]) : [];
        return main + (modes.length ? '; ' + modes.map(mode => mode + ' → ' + format(contract.mode_defaults[mode])).join('; ') : '');
    }

    function buildAgentPrompt(root, locale, reference) {
        const language = agentProse[locale] ? locale : 'en';
        const p = agentProse[language];
        const origin = serviceRoot(root);
        const registry = Array.isArray(reference?.model_parameters) ? reference.model_parameters : [];
        const contracts = cleanFamilies.map(id => registry.find(item => item.id === id
            && item.type === (id.startsWith('gemini-') ? 'image' : 'video') && Array.isArray(item.variants)));
        // Do not copy an incomplete contract into an apparently complete handoff.
        if (contracts.some(item => !item || !compactContractRows(item).length)) {
            throw new TypeError('Flow2API integration reference must contain all eight model family contracts');
        }
        const imageRows = contracts.filter(item => item.type === 'image').flatMap(compactContractRows);
        const videoRows = contracts.filter(item => item.type === 'video').flatMap(compactContractRows);
        return [
            '# ' + p.title, p.mission, p.boundary,
            '## ' + p.stepsTitle, p.steps.map((step, index) => (index + 1) + '. ' + step).join('\n'),
            '## ' + p.connectionTitle,
            fence('text', 'FLOW2API_BASE_URL=' + origin + '\nFLOW2API_API_KEY=REPLACE_WITH_SERVER_API_KEY'), p.connection,
            '## ' + p.modelsTitle, p.models,
            markdownTable(p.imageHeaders, imageRows), markdownTable(p.videoHeaders, videoRows),
            '### ' + p.typesTitle, p.types,
            '### ' + p.defaultsTitle, p.defaults, contracts.map(formatDefaults).join('\n'),
            '## ' + p.inputsTitle, p.inputs, p.runtime, p.reliability,
            '## ' + p.acceptanceTitle, p.acceptance,
            build(origin, language, { intro: p.recipesIntro, skipUpscale: true,
                copy: { extend: p.extend, setup: p.setup, js: p.js } })
        ].join('\n\n').trim();
    }

    window.Flow2APIIntegrationRecipes = Object.freeze({ build, buildAgentPrompt });
}());
