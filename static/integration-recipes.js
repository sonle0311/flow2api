(function () {
    'use strict';

    // Documentation only: building this string never contacts the server.
    const prose = {
        en: {
            title: 'Runnable integration recipes',
            intro: 'These examples describe this repository, not the full OpenAI or Google API. Discover the deployed catalog first. The representative IDs below exist in the current registry; availability still depends on account tier, credits, captcha and upstream access. The complete registry and capability tables appear elsewhere in this guide.',
            setup: ['Environment and discovery', 'Use the server API key configured by the administrator, never a Google Cookie, account token or admin password. Replace the placeholder locally. ROOT is the service origin, including any reverse-proxy prefix, without /v1. An OpenAI SDK base_url ends in /v1; Gemini requests use /v1beta/models. Do not append /v1 twice. Headers are preferable to ?key= because URLs may be logged. Authentication accepts Bearer, x-goog-api-key, or ?key=; if several are supplied, Bearer takes precedence, then x-goog-api-key. A wrong Bearer key is not rescued by a correct query key.'],
            image: ['Text to image: curl and a request file', 'Save this JSON as request.json (UTF-8). Run the curl command below from Bash or PowerShell using curl.exe on Windows. stream:false waits for the final response. The result is choices[0].message.content containing Markdown, not an OpenAI Images data array. A simple string prompt generates media; this service is not a general conversational or function-calling LLM.'],
            edit: ['Image to image: URL or local file', 'A multimodal message combines a nonempty text prompt and image_url objects. Use an HTTPS image URL reachable by the server, or a data URI containing the actual base64 image bytes. The URL is downloaded by the server, so localhost refers to that server. The Python script below creates edit.json from a local reference.png; then use the same curl command with @edit.json. Replace the data URI with an HTTPS URL for URL input. Do not pass a raw local filesystem path or just the filename. Only the last OpenAI message supplies the main prompt and direct images; image models can additionally recover the most recent image from earlier assistant Markdown. Send explicit references for predictable behavior.'],
            dimensions: ['Aspect ratio, resolution and aliases', 'Use a simplified image alias plus generationConfig.imageConfig to select a variant. For example the request below resolves to gemini-3.1-flash-image-portrait-2k. Ratios are 16:9, 9:16, 1:1, 4:3, 3:4; names landscape, portrait, square, four-three, three-four are also accepted. imageSize is 1K (base output), 2K or 4K. Upsampling can fall back to the original image; inspect the actual output. If no ratio is supplied, aliases infer it from the first input image or default to landscape. Explicit variant IDs keep their configured shape/resolution, so do not expect configuration fields to override them.', 'The resolver also accepts generationConfig.aspectRatio/imageSize, snake_case image_config/aspect_ratio/image_size, raw JSON extra_body.generationConfig (or extraBody), and top-level aspect_ratio/image_size. OpenAI SDK extra_body merges fields into the outgoing JSON; use extra_body={"generationConfig": ...}. Top-level size such as 1024x1792 approximates the closest supported ratio; quality medium maps to 2k and high/hd/ultra to 4k, while low/standard request base output. These are compatibility mappings, not arbitrary pixel dimensions. Resolution applies only where the selected alias has a matching variant. Prefer one spelling and avoid conflicting fields.'],
            video: ['Video recipes: change the model and image count', 'Every body below goes to POST /v1/chat/completions with the same Bearer header. Save one as request.json and run the previous curl command, with --max-time 3600 for video. The model ID selects duration and orientation; there is no generic seconds parameter. T2V has no input image; current I2V accepts one first frame or two ordered first/last frames. Use 1–3 references for R2V; this is not first/last interpolation. The registry declares a minimum of 1, but the current local handler does not reject 0 and falls back to text generation; upstream acceptance of that fallback is not guaranteed. Omni supports 0–3 images and selects its reference path when images are supplied. Models in the registry do not guarantee access for the account in use.'],
            extend: ['Extend an existing Flow video', 'Use the Flow mediaGenerationId, not a chatcmpl ID, operation/task ID, MP4 URL or uploaded arbitrary video. The current public extension model below accepts extend:// in an OpenAI image_url slot; this marker is not an image download. The streaming video content can contain data-media-id; administrators can also inspect generated_assets.mediaGenerationId in generation logs. The ordinary nonstream completion returns a video URL without exposing a structured source media ID, so retain the ID when available or obtain it from authorized Flow/admin records. There is no public upload-video or media-ID lookup endpoint in this adapter. Gemini normalization does not forward an extension ID; use the OpenAI route for extension.'],
            upscale: ['Video upsampling and legacy compatibility', 'Current public hyphenated video IDs do not configure video upsampling. Hidden legacy IDs such as veo_3_1_t2v_4s_1080p and veo_3_1_i2v_s_4s_4k remain accepted by this source registry and generate a new video before upsampling it. They are not a standalone upscale endpoint for an arbitrary MP4. Use only if the deployed version supports them and the account can access their upstream models. The legacy alias veo_3_1_t2v with generationConfig.imageConfig.imageSize="1080p" or "4K" selects an available legacy upscale variant; this does not apply automatically to veo-3.1-fast. An upscale failure may return the original video. There is no /videos/upscale route.'],
            gemini: ['Gemini-compatible requests', 'Save the JSON below as gemini.json. contents.parts.text is the prompt. inlineData contains base64 only (no data: prefix); fileData.fileUri accepts a reachable image URL or data URI with an image MIME type. To use a local file, reuse the Python base64 conversion above and put the encoded bytes in inlineData.data. The server uses the last user content, not a full Gemini reasoning conversation. For text-only image generation, remove the image part. POST :generateContent returns candidates[].content.parts with inlineData or fileData for media; :streamGenerateContent uses SSE (optional ?alt=sse is tolerated). Gemini progress is returned as text parts; this adapter does not add a thought:true flag. This is an adapter: response modalities, tools, structured output and unrelated Gemini methods are not promised.'],
            js: ['JavaScript: robust fetch and SSE', 'Run this in a modern browser or Node.js with fetch (Node 18+). Set environment variables in Node; in a browser the fallback key is a placeholder to replace only in trusted local use. Production applications should proxy through their own backend so the service key is not embedded in public frontend code. The parser buffers UTF-8 and SSE frames across network chunks, handles CRLF, [DONE], final partial frames, HTTP errors and in-stream JSON errors. reasoning_content is generation progress, not the final media result. AbortController closes the client request; it does not guarantee upstream cancellation or refund.'],
            python: ['Python: requests, httpx and optional OpenAI SDK', 'Install only the library needed: python -m pip install requests, httpx, or openai. Both plain HTTP examples disable automatic generation retries. The optional SDK uses chat.completions.create and max_retries=0. SDK images.generate, images.edit, Responses, assistants, tools, embeddings, audio and a generic text chat are not implemented routes in this repository. Extra fields accepted by a request schema do not imply their semantics are implemented.'],
            adapter: ['Connecting any tool or building an adapter', '1. Pick the OpenAI-compatible provider/custom endpoint if the tool can send chat/completions, or Gemini-compatible if it supports a custom Gemini root. Set base URL, server key, and a verified model ID manually if discovery is unavailable.\n2. Discover /v1/models and /v1/models/aliases; preserve capability distinctions. Display only suitable image/video models in each workflow. Do not rename an image model to gpt-4o and assume text chat works.\n3. Translate the user prompt and actual image bytes/URLs into the request format shown above. Preserve ordered first/last frames and reference-count limits. The tool must allow image attachments, custom model IDs, long timeouts and custom JSON for advanced settings.\n4. Parse the final OpenAI content or Gemini media parts. Preserve progress separately. An HTTP 200 SSE stream can still carry an error. If a tool ignores reasoning_content, generation may appear silent until completion; that is normal.\n5. For images, extract Markdown image destinations; for video, parse the video src attribute from the returned content (nonstream wraps it in an html code fence). Never insert the returned HTML with innerHTML. Treat all model text and URLs as untrusted: use textContent for text, create img/video elements yourself, validate URL schemes (HTTPS or approved HTTP; bounded image data URIs when needed), restrict origins according to your application, and set video.controls=true. Retain data-media-id separately for extension. Gemini inlineData should become a Blob with a validated image MIME type.\n6. Serve cache URLs through a reachable public root when remote clients need them; /tmp links and localhost links may be inaccessible outside the deployment. Signed upstream URLs and cache entries can expire. Save required output promptly according to deployment policy.'],
            errors: ['Errors, waiting, cancellation and retries', 'Authentication failures use HTTP 401 with {"detail":"Invalid API key"}. Validation may use {"detail":...} (400/422). Generation errors use the OpenAI error envelope below; Gemini uses error.code/message/status. Handle both HTTP status and payload. A successful TCP/HTTP connection is not proof that generation succeeded. 400 usually means unsupported model, missing prompt or wrong image count; 403 may indicate model/account access; 503 may mean no usable token; 502/504 may indicate upstream failure or timeout. Inspect the actual error message and administrator logs rather than retrying every error.', 'Default generation configuration is 300 seconds for images and 1500 seconds for video, but administrators can change it and polling/upscaling can extend the effective wait. Configure the client, reverse proxy and load balancer timeouts together; the examples use a generous 3600-second limit. Disable proxy SSE buffering. Closing a stream or timing out can leave upstream work already submitted. No public cancellation, job-status polling or idempotency-key contract is provided by these generation routes. A retry may create another paid job. Retry discovery GETs safely; for POST, decide from logs/output first, then use bounded backoff for genuinely transient failures. Never loop automatically on 400/401/403.']
        },
        vi: {
            title: 'Công thức tích hợp có thể chạy',
            intro: 'Các ví dụ mô tả mã nguồn này, không phải toàn bộ API OpenAI hay Google. Hãy đọc danh sách model của máy chủ trước. ID minh họa có trong registry hiện tại; quyền sử dụng còn phụ thuộc gói tài khoản, credits, captcha và upstream. Bảng registry và khả năng đầy đủ nằm ở phần khác của hướng dẫn.',
            setup: ['Môi trường và khám phá model', 'Dùng API key máy chủ do quản trị viên cấu hình, không dùng Google Cookie, token tài khoản hay mật khẩu admin. Thay placeholder trên máy của bạn. ROOT là gốc dịch vụ, có thể gồm tiền tố reverse proxy, không có /v1. base_url của OpenAI SDK kết thúc bằng /v1; Gemini gọi /v1beta/models. Tránh lặp /v1. Ưu tiên header thay cho ?key= vì URL có thể bị ghi log. Hệ thống nhận Bearer, x-goog-api-key hoặc ?key=; nếu cùng xuất hiện thì ưu tiên Bearer rồi x-goog-api-key. Bearer sai không được cứu bởi query key đúng.'],
            image: ['Văn bản thành ảnh: curl và file yêu cầu', 'Lưu JSON thành request.json (UTF-8). Chạy lệnh curl bên dưới trong Bash hoặc PowerShell, dùng curl.exe trên Windows. stream:false đợi kết quả cuối. Kết quả là Markdown trong choices[0].message.content, không phải mảng data của OpenAI Images. Prompt chuỗi tạo nội dung đa phương tiện; dịch vụ không phải LLM hội thoại tổng quát hay function calling.'],
            edit: ['Ảnh thành ảnh: URL hoặc file cục bộ', 'Một tin nhắn đa phương thức gồm prompt văn bản không rỗng và các đối tượng image_url. Dùng URL HTTPS mà máy chủ tải được hoặc data URI chứa base64 thực của ảnh. localhost trong URL là máy chủ, không phải máy của người dùng. Script Python bên dưới tạo edit.json từ reference.png; sau đó dùng lệnh curl với @edit.json. Muốn dùng URL thì thay data URI bằng URL HTTPS. Không gửi đường dẫn file cục bộ hay chỉ tên file. Tin nhắn OpenAI cuối cung cấp prompt và ảnh trực tiếp; model ảnh còn có thể lấy ảnh gần nhất từ Markdown assistant trước đó. Gửi ảnh tham chiếu tường minh để có kết quả ổn định.'],
            dimensions: ['Tỉ lệ, độ phân giải và alias', 'Dùng alias ảnh rút gọn cùng generationConfig.imageConfig để chọn biến thể. Ví dụ dưới phân giải thành gemini-3.1-flash-image-portrait-2k. Các tỉ lệ: 16:9, 9:16, 1:1, 4:3, 3:4; tên landscape, portrait, square, four-three, three-four cũng hợp lệ. imageSize nhận 1K (ảnh gốc), 2K hoặc 4K. Phóng ảnh có thể thất bại và trả ảnh gốc; kiểm tra kết quả thực. Nếu không chỉ định tỉ lệ, alias suy từ ảnh đầu tiên hoặc mặc định ngang. ID biến thể tường minh giữ tỉ lệ/độ phân giải cấu hình sẵn, không bị ghi đè bởi các trường này.', 'Resolver còn nhận generationConfig.aspectRatio/imageSize, image_config/aspect_ratio/image_size, JSON extra_body.generationConfig (hoặc extraBody), và aspect_ratio/image_size ở cấp ngoài cùng. OpenAI SDK gộp extra_body vào JSON gửi đi; dùng extra_body={"generationConfig": ...}. size như 1024x1792 được ánh xạ tới tỉ lệ gần nhất; quality medium thành 2k, high/hd/ultra thành 4k, low/standard dùng ảnh gốc. Đây là ánh xạ tương thích, không phải kích thước pixel tùy ý. Độ phân giải chỉ áp dụng khi alias có biến thể tương ứng. Dùng một kiểu tên và tránh các trường mâu thuẫn.'],
            video: ['Video: thay model và số ảnh', 'Mỗi body dưới gửi tới POST /v1/chat/completions với cùng header Bearer. Lưu một body thành request.json rồi chạy curl ở trên, dùng --max-time 3600 cho video. ID model chọn thời lượng và hướng; không có tham số seconds tổng quát. T2V không có ảnh; I2V hiện tại nhận một khung đầu hoặc hai ảnh theo thứ tự đầu/cuối. Nên gửi 1–3 ảnh tham chiếu cho R2V, không phải nội suy đầu/cuối. Registry khai báo tối thiểu 1 ảnh nhưng handler hiện tại không chặn 0 ảnh và chuyển sang tạo từ văn bản; không bảo đảm upstream chấp nhận cách dự phòng này. Omni nhận 0–3 ảnh và chuyển sang nhánh tham chiếu khi có ảnh. Model xuất hiện trong registry không bảo đảm tài khoản có quyền dùng.'],
            extend: ['Nối dài video Flow có sẵn', 'Dùng mediaGenerationId của Flow, không phải chatcmpl ID, task/operation ID, URL MP4 hay video tải lên tùy ý. Model public dưới nhận extend:// trong image_url của OpenAI; đây là marker, không phải URL tải ảnh. Nội dung video streaming có thể chứa data-media-id; quản trị viên cũng có thể xem generated_assets.mediaGenerationId trong log tạo nội dung. Phản hồi nonstream thông thường chỉ trả URL video, không có trường source media ID có cấu trúc. Hãy giữ ID khi nhận được hoặc lấy từ hồ sơ Flow/admin được phép truy cập. Adapter không có endpoint public để tải video lên hay tra media ID. Gemini không chuyển tiếp extension ID; dùng route OpenAI để nối dài.'],
            upscale: ['Phóng video và tương thích legacy', 'ID video public có dấu gạch nối hiện tại không cấu hình phóng video. ID legacy ẩn như veo_3_1_t2v_4s_1080p và veo_3_1_i2v_s_4s_4k vẫn được registry mã nguồn nhận và tạo video mới trước khi phóng. Chúng không phải endpoint phóng một MP4 bất kỳ. Chỉ dùng khi phiên bản triển khai còn hỗ trợ và tài khoản truy cập được model upstream. Alias legacy veo_3_1_t2v với generationConfig.imageConfig.imageSize="1080p" hoặc "4K" chọn biến thể phóng tương ứng; không tự áp dụng cho veo-3.1-fast. Phóng thất bại có thể trả video gốc. Không có route /videos/upscale.'],
            gemini: ['Yêu cầu tương thích Gemini', 'Lưu JSON dưới thành gemini.json. contents.parts.text là prompt. inlineData chứa base64 thuần, không có tiền tố data:; fileData.fileUri nhận URL ảnh hoặc data URI với MIME ảnh. Với file cục bộ, dùng phép chuyển base64 trong Python ở trên và đặt chuỗi mã hóa vào inlineData.data. Máy chủ dùng user content cuối, không thực hiện toàn bộ hội thoại suy luận Gemini. Để tạo ảnh chỉ bằng văn bản, bỏ part ảnh. POST :generateContent trả media trong candidates[].content.parts dưới dạng inlineData hoặc fileData; :streamGenerateContent dùng SSE (?alt=sse tùy chọn vẫn được nhận). Tiến trình Gemini được trả bằng text parts; adapter không thêm cờ thought:true. Đây là adapter; không hứa hỗ trợ response modalities, tools, structured output hay các phương thức Gemini khác.'],
            js: ['JavaScript: fetch và SSE có bộ đệm', 'Chạy trong trình duyệt mới hoặc Node.js có fetch (Node 18+). Đặt biến môi trường ở Node; trong trình duyệt key dự phòng là placeholder, chỉ thay khi chạy cục bộ đáng tin cậy. Ứng dụng production nên gọi qua backend riêng để không nhúng key vào frontend công khai. Parser ghép UTF-8 và khung SSE qua nhiều chunk, xử lý CRLF, [DONE], khung cuối thiếu dấu ngắt, lỗi HTTP và JSON lỗi trong stream. reasoning_content là tiến trình tạo nội dung, không phải media cuối. AbortController đóng yêu cầu phía client, không bảo đảm hủy upstream hay hoàn credits.'],
            python: ['Python: requests, httpx và OpenAI SDK tùy chọn', 'Chỉ cài thư viện cần dùng: python -m pip install requests, httpx hoặc openai. Hai ví dụ HTTP thuần không tự retry tạo nội dung. SDK tùy chọn dùng chat.completions.create và max_retries=0. SDK images.generate, images.edit, Responses, assistants, tools, embeddings, audio và chat văn bản tổng quát không phải route được triển khai ở đây. Schema nhận một trường không đồng nghĩa chức năng của trường đó được thực thi.'],
            adapter: ['Kết nối công cụ bất kỳ hoặc viết adapter', '1. Chọn provider OpenAI-compatible/custom endpoint nếu công cụ gửi được chat/completions, hoặc Gemini-compatible nếu cho đổi gốc Gemini. Đặt base URL, key máy chủ và model ID đã kiểm tra; nhập model thủ công nếu không khám phá được.\n2. Đọc /v1/models và /v1/models/aliases; giữ đúng khác biệt khả năng. Chỉ hiện model ảnh/video phù hợp từng luồng. Đừng đổi tên model ảnh thành gpt-4o rồi kỳ vọng chat văn bản.\n3. Chuyển prompt và bytes/URL ảnh thực theo định dạng trên. Giữ thứ tự khung đầu/cuối và giới hạn số ảnh. Công cụ phải cho đính kèm ảnh, dùng model tùy chỉnh, timeout dài và JSON bổ sung cho thiết lập nâng cao.\n4. Đọc content OpenAI cuối hoặc media parts Gemini. Tách tiến trình khỏi kết quả. SSE HTTP 200 vẫn có thể chứa lỗi. Nếu công cụ bỏ reasoning_content, có thể không thấy gì trước kết quả cuối.\n5. Với ảnh, lấy đích của Markdown ảnh; với video, đọc thuộc tính src (nonstream bọc video trong code fence html). Không đưa HTML trả về vào innerHTML. Xem văn bản và URL là dữ liệu chưa tin cậy: dùng textContent, tự tạo img/video, kiểm tra scheme (HTTPS hoặc HTTP được duyệt; data URI ảnh có giới hạn dung lượng), hạn chế origin theo ứng dụng và đặt video.controls=true. Lưu data-media-id riêng để nối dài. inlineData Gemini nên chuyển thành Blob với MIME ảnh đã kiểm tra.\n6. Dùng gốc public truy cập được cho URL cache khi có client từ xa; /tmp hay localhost có thể không truy cập được bên ngoài. URL upstream có chữ ký và cache có thể hết hạn. Lưu đầu ra cần thiết sớm theo chính sách triển khai.'],
            errors: ['Lỗi, thời gian chờ, hủy và retry', 'Sai xác thực trả HTTP 401 với {"detail":"Invalid API key"}. Lỗi validation có thể là {"detail":...} (400/422). Lỗi tạo nội dung dùng envelope OpenAI dưới; Gemini dùng error.code/message/status. Kiểm tra cả HTTP status lẫn payload. Kết nối TCP/HTTP thành công chưa chứng minh đã tạo xong. 400 thường là model không hỗ trợ, thiếu prompt hoặc sai số ảnh; 403 có thể do quyền model/tài khoản; 503 có thể không còn token dùng được; 502/504 có thể do lỗi upstream/timeout. Đọc thông báo và log quản trị trước khi retry.', 'Cấu hình mặc định là 300 giây cho ảnh và 1500 giây cho video, nhưng admin có thể đổi và polling/phóng có thể làm thời gian chờ thực dài hơn. Cấu hình timeout client, reverse proxy và load balancer đồng bộ; ví dụ dùng 3600 giây. Tắt buffering SSE ở proxy. Đóng stream hay timeout có thể xảy ra sau khi upstream đã nhận công việc. Các route này không có hợp đồng public về hủy, polling trạng thái job hay idempotency key. Retry có thể tạo thêm job tốn phí. GET khám phá có thể retry an toàn; với POST hãy kiểm tra log/đầu ra trước rồi mới backoff có giới hạn cho lỗi tạm thời. Không lặp tự động với 400/401/403.']
        },
        'zh-CN': {
            title: '可运行的集成示例',
            intro: '以下示例描述本仓库，而非完整的 OpenAI 或 Google API。请先查询部署服务器的模型目录。示例 ID 均存在于当前 registry；实际可用性仍取决于账号等级、积分、验证码及上游权限。完整模型与能力表位于本指南其他部分。',
            setup: ['环境变量与模型发现', '使用管理员配置的服务器 API key，不要使用 Google Cookie、账号 token 或管理员密码。请在本机替换占位值。ROOT 是服务根地址，可包含反向代理路径前缀，但不带 /v1。OpenAI SDK 的 base_url 以 /v1 结尾；Gemini 使用 /v1beta/models。避免重复 /v1。优先使用请求头，因为 ?key= 可能出现在 URL 日志中。认证支持 Bearer、x-goog-api-key、?key=，同时存在时依次优先 Bearer、x-goog-api-key。错误的 Bearer 不会被正确的查询参数补救。'],
            image: ['文生图：curl 与请求文件', '将 JSON 保存为 UTF-8 的 request.json。在 Bash 或 PowerShell 运行下面的 curl，Windows 请使用 curl.exe。stream:false 等待最终结果。结果位于 choices[0].message.content，是 Markdown，而不是 OpenAI Images 的 data 数组。字符串提示词用于生成媒体；本服务不是通用对话或函数调用 LLM。'],
            edit: ['图生图：URL 或本地文件', '多模态消息由非空文本提示词与 image_url 对象组成。使用服务器可访问的 HTTPS 图片 URL，或包含真实图片 base64 字节的 data URI。URL 中的 localhost 指服务器自身。下面的 Python 脚本从 reference.png 生成 edit.json，然后使用相同 curl 命令并改为 @edit.json。URL 输入可将 data URI 换为 HTTPS URL。不要传本地路径或只有文件名。主要提示词和直接图片取自最后一条 OpenAI 消息；图片模型还可能从之前 assistant 的 Markdown 恢复最近图片。明确传入参考图片更可靠。'],
            dimensions: ['宽高比、分辨率与别名', '使用简化图片别名和 generationConfig.imageConfig 选择变体。下面示例解析为 gemini-3.1-flash-image-portrait-2k。支持比例 16:9、9:16、1:1、4:3、3:4，也支持 landscape、portrait、square、four-three、three-four。imageSize 可为 1K（基础输出）、2K、4K。放大失败可能回退原图，请检查实际结果。别名未指定比例时从第一张参考图推断，否则默认横向。完整变体 ID 保留自身配置，不应期待这些字段覆盖其比例或分辨率。', '解析器还接受 generationConfig.aspectRatio/imageSize、image_config/aspect_ratio/image_size、原始 JSON 的 extra_body.generationConfig（或 extraBody）以及顶层 aspect_ratio/image_size。OpenAI SDK 会把 extra_body 合并到发出的 JSON；应使用 extra_body={"generationConfig": ...}。顶层 size 如 1024x1792 会近似映射为最接近的支持比例；quality medium 对应 2k，high/hd/ultra 对应 4k，low/standard 使用基础输出。这是兼容映射，并非任意像素尺寸。只有别名存在对应变体时才应用分辨率。建议统一字段格式，避免冲突。'],
            video: ['视频示例：替换模型与图片数量', '以下 body 都发送至 POST /v1/chat/completions，并使用相同 Bearer 请求头。选一个保存为 request.json，使用上面的 curl，视频建议 --max-time 3600。模型 ID 决定时长和方向，没有通用 seconds 参数。T2V 不带图片；当前 I2V 接受一张首帧，或两张按首帧、尾帧顺序排列的图片。R2V 建议使用 1–3 张参考图，不等同于首尾帧插值。注册表声明至少 1 张，但本地处理器未拒绝 0 张并回退至文生视频；不保证上游接受这种回退。Omni 支持 0–3 张图片，有图片时走参考路径。目录存在某模型并不保证当前账号有权限。'],
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
    const body = (model, content) => ({ model, messages: [{ role: 'user', content }], stream: false });
    const imageModel = 'gemini-3.1-flash-image-landscape';

    function build(root, locale) {
        const p = prose[locale] || prose.en;
        const origin = String(root || 'http://localhost:8000');
        const parts = ['\n## ' + p.title + '\n\n' + p.intro];
        function section(key, snippets) {
            parts.push('\n### ' + p[key][0] + '\n\n' + p[key].slice(1).join('\n\n') + '\n' + (snippets || ''));
        }
        section('setup', fence('bash', 'export FLOW2API_BASE_URL=' + "'" + origin.replace(/'/g, "'\\''") + "'" + '\nexport FLOW2API_API_KEY="REPLACE_WITH_SERVER_API_KEY"\ncurl --fail-with-body "$FLOW2API_BASE_URL/v1/models" -H "Authorization: Bearer $FLOW2API_API_KEY"\ncurl --fail-with-body "$FLOW2API_BASE_URL/v1/models/aliases" -H "Authorization: Bearer $FLOW2API_API_KEY"\ncurl --fail-with-body "$FLOW2API_BASE_URL/v1beta/models" -H "x-goog-api-key: $FLOW2API_API_KEY"') + fence('powershell', '$env:FLOW2API_BASE_URL = ' + "'" + origin.replace(/'/g, "''") + "'" + '\n$env:FLOW2API_API_KEY = "REPLACE_WITH_SERVER_API_KEY"\n$headers = @{ Authorization = "Bearer $env:FLOW2API_API_KEY" }\nInvoke-RestMethod "$env:FLOW2API_BASE_URL/v1/models" -Headers $headers\nInvoke-RestMethod "$env:FLOW2API_BASE_URL/v1/models/aliases" -Headers $headers'));
        section('image', json(body(imageModel, 'Create a cinematic photograph of a red bicycle beside a lake at sunrise.')) + fence('bash', 'curl --fail-with-body --max-time 3600 "$FLOW2API_BASE_URL/v1/chat/completions" \\\n  -H "Authorization: Bearer $FLOW2API_API_KEY" \\\n  -H "Content-Type: application/json" --data-binary @request.json') + fence('powershell', 'curl.exe --fail-with-body --max-time 3600 "$env:FLOW2API_BASE_URL/v1/chat/completions" -H "Authorization: Bearer $env:FLOW2API_API_KEY" -H "Content-Type: application/json" --data-binary "@request.json"'));
        section('edit', json(body(imageModel, [textPart('Keep the bicycle; change the background to a snowy forest.'), imagePart('https://YOUR_REACHABLE_HOST/reference.png')])) + fence('python', 'import base64, json\nfrom pathlib import Path\nencoded = base64.b64encode(Path("reference.png").read_bytes()).decode("ascii")\nrequest = {"model": "' + imageModel + '", "stream": False,\n    "messages": [{"role": "user", "content": [\n        {"type": "text", "text": "Keep the subject; change the background to a snowy forest."},\n        {"type": "image_url", "image_url": {"url": "data:image/png;base64," + encoded}}]}]}\nPath("edit.json").write_text(json.dumps(request), encoding="utf-8")'));
        section('dimensions', json({ ...body('gemini-3.1-flash-image', 'A vertical watercolor poster of a mountain village.'), generationConfig: { imageConfig: { aspectRatio: '9:16', imageSize: '2K' } } }));
        const frame = 'https://YOUR_REACHABLE_HOST/first.png';
        const last = 'https://YOUR_REACHABLE_HOST/last.png';
        section('video', '**T2V**\n' + json(body('veo-3.1-fast-4s-landscape', 'A red bicycle rolls slowly beside a lake, cinematic tracking shot.')) + '**I2V: 1 image**\n' + json(body('veo-3.1-fast-i2v-4s-landscape', [textPart('Slowly orbit the subject.'), imagePart(frame)])) + '**I2V: first + last**\n' + json(body('veo-3.1-quality-i2v-6s-portrait', [textPart('Create a smooth transition from the first frame to the last frame.'), imagePart(frame), imagePart(last)])) + '**R2V: 1–3 images**\n' + json(body('veo-3.1-fast-r2v-8s-landscape', [textPart('Use these subjects in a coherent cinematic scene.'), imagePart(frame), imagePart(last)])) + '**Omni: 0–3 images**\n' + json(body('omni-1.1-flash-4s-landscape', [textPart('Animate this scene with a slow camera pan.'), imagePart(frame)])));
        section('extend', json(body('veo-3.1-fast-extend-8s-landscape', [textPart('Continue the movement naturally, maintaining the same scene.'), imagePart('extend://REPLACE_WITH_FLOW_MEDIA_GENERATION_ID')])));
        section('upscale', json(body('veo_3_1_t2v_4s_1080p', 'A cinematic mountain landscape at dawn.')));
        section('gemini', json({ contents: [{ role: 'user', parts: [{ text: 'Paint the subject as a watercolor portrait.' }, { fileData: { mimeType: 'image/png', fileUri: frame } }] }], generationConfig: { imageConfig: { aspectRatio: '1:1', imageSize: '2K' } } }) + fence('json', '{"inlineData":{"mimeType":"image/png","data":"REPLACE_WITH_ACTUAL_BASE64_BYTES"}}') + fence('bash', 'curl --fail-with-body --max-time 3600 "$FLOW2API_BASE_URL/v1beta/models/gemini-3.1-flash-image:generateContent" \\\n  -H "x-goog-api-key: $FLOW2API_API_KEY" \\\n  -H "Content-Type: application/json" --data-binary @gemini.json\n# SSE: use :streamGenerateContent?alt=sse and curl -N') + fence('powershell', 'curl.exe --fail-with-body --max-time 3600 "$env:FLOW2API_BASE_URL/v1beta/models/gemini-3.1-flash-image:generateContent" -H "x-goog-api-key: $env:FLOW2API_API_KEY" -H "Content-Type: application/json" --data-binary "@gemini.json"'));
        section('js', fence('javascript', jsExample(origin)));
        section('python', fence('python', pythonExample()) + fence('python', 'import os\nfrom openai import OpenAI\nclient = OpenAI(api_key=os.environ["FLOW2API_API_KEY"],\n    base_url=os.environ["FLOW2API_BASE_URL"].rstrip("/") + "/v1",\n    timeout=3600.0, max_retries=0)\nresult = client.chat.completions.create(\n    model="gemini-3.1-flash-image",\n    messages=[{"role": "user", "content": "A watercolor mountain village."}],\n    stream=False,\n    extra_body={"generationConfig": {"imageConfig": {"aspectRatio": "16:9", "imageSize": "2K"}}})\nprint(result.choices[0].message.content)'));
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
      body: JSON.stringify({model: "gemini-3.1-flash-image-landscape", stream: true,
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
body = {"model": "gemini-3.1-flash-image-landscape", "stream": False,
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

    window.Flow2APIIntegrationRecipes = Object.freeze({ build });
}());
