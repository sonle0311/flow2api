---
name: flow2api
description: Generate images and videos through the user's own Flow2API server (Gemini image models, Veo 3.1, Omni) from any project. Use whenever the user asks to "gen ảnh", "tạo ảnh AI", "vẽ bằng AI", "tạo video AI", make character art, keyframes, thumbnails, reference sheets, image edits (ảnh thành ảnh), image-to-video, reference-to-video or to extend a Flow video, or mentions Flow2API, Veo, Gemini image, nano banana, omni-flash. Also use it to check the Flow2API connection or list which models and option combinations are allowed. Every generation is paid: never generate without the user asking for that output.
---

# Flow2API

Gọi máy chủ Flow2API của người dùng để tạo ảnh và video. Dùng được ở mọi dự án: một script Python thuần (chỉ thư viện chuẩn, Python 3.9+) ở `scripts/flow2api.py`.

## Cấu hình

| Biến | Giá trị | Ghi chú |
|---|---|---|
| `FLOW2API_BASE_URL` | mặc định `http://localhost:8000` | gốc dịch vụ, **không** có `/v1`; giữ tiền tố proxy nếu có |
| `FLOW2API_API_KEY` | generation key | bí mật |
| `FLOW2API_MAX_PARALLEL_IMAGE` / `_VIDEO` | 9 / 6 | giới hạn song song phía máy mình |

Script đọc biến môi trường, nếu không có thì đọc `~/.config/flow2api/env` (dòng `KEY=value`, quyền 600).

**Key là bí mật:**
- Không bao giờ hỏi key qua chat, không in, không ghi vào file dự án hay tham số lệnh.
- Nếu `check` báo "CHƯA ĐẶT", hướng dẫn người dùng tự tạo file trong terminal của họ:

```bash
mkdir -p ~/.config/flow2api && printf 'Flow2API key: ' && IFS= read -rs K && printf 'FLOW2API_BASE_URL=http://localhost:8000\nFLOW2API_API_KEY=%s\n' "$K" > ~/.config/flow2api/env && chmod 600 ~/.config/flow2api/env && unset K && echo
```

## Lệnh

```bash
S=~/.claude/skills/flow2api/scripts/flow2api.py
python3 $S check            # GET /v1/models + /aliases, miễn phí; chạy đầu tiên
python3 $S models           # bảng model/tổ hợp hợp lệ (cục bộ)
python3 $S image "prompt" --aspect 9:16 --size 2K --out <thư-mục> --name <tên>
python3 $S image "giữ nhân vật, đổi bối cảnh..." --ref nhanvat.png --out ...      # ảnh thành ảnh
python3 $S video "prompt" --model veo-3.1-fast --mode t2v --aspect 9:16 --duration 8 --out ...
python3 $S video "camera chậm" --mode i2v --ref dau.png [--ref cuoi.png] --duration 4 --out ...
python3 $S video "..." --mode r2v --ref chu-the.png --ref phong-cach.png          # 1–3 ảnh tham chiếu
python3 $S video "đi tiếp" --mode extend --extend <media_id> --out ...            # nối dài video Flow
python3 $S batch jobs.jsonl --parallel 3   # mỗi dòng: {"kind":"image","prompt":"...","aspect":"9:16","ref":["a.png"],"out":"...","name":"..."}
```

- Prompt dài thì dùng `--prompt-file file.txt`.
- Mỗi kết quả lưu thành `<name>.png|.mp4` kèm `<name>.json`. File json ghi model, cấu hình, prompt và `media_id`; giữ `media_id` để nối dài video.
- Tiến trình in ra stderr.

## Model và tổ hợp hợp lệ

Chỉ dùng tổ hợp trong bảng. Script kiểm tra trước khi gửi và từ chối tổ hợp sai.

| Ảnh | aspect | size | ảnh tham chiếu |
|---|---|---|---|
| `gemini-3.0-pro-image` (đẹp nhất) | 16:9, 9:16, 1:1, 4:3, 3:4 | 1K, 2K, 4K | 0 – nhiều |
| `gemini-3.1-flash-image` (mặc định) | như trên | như trên | 0 – nhiều |
| `gemini-3.1-flash-lite-image` (nhanh, rẻ) | như trên | như trên | 0 – nhiều |

| Video | mode | aspect | giây | ảnh |
|---|---|---|---|---|
| `veo-3.1-fast` / `veo-3.1-lite` | t2v | 16:9, 9:16 | 4, 6, 8 | 0 |
| | i2v | 16:9, 9:16 | 4, 6 | 1–2 (đầu, cuối) |
| | r2v | 16:9, 9:16 | 8 | 1–3 (tham chiếu chủ thể/phong cách) |
| | extend | 16:9, 9:16 | 8 | 0 + `--extend ID` |
| `veo-3.1-quality` | t2v, i2v, extend (không có r2v) | như trên | như trên | như trên |
| `omni-1.1-flash` | auto | 16:9, 9:16 | 4, 6, 8, 10 | 0–3 |
| `omni-1.2-flash` | auto | 16:9: 3–10; 9:16: 3–15 | | 0–3 |

Mặc định: ảnh 16:9 1K; Veo t2v 8 s, i2v 4 s; Omni auto 8 s.

## Quy tắc khi dùng

1. **Tính phí.**
   - Chỉ chạy `image`/`video` khi người dùng đã yêu cầu đúng sản phẩm đó.
   - Với lô lớn hoặc video, nói trước số lần tạo rồi chờ đồng ý.
   - `check` và `models` thì chạy thoải mái.
2. **Không gửi lại mù quáng.**
   - Script tự thử lại khi gặp HTTP 429, quota hoặc reCAPTCHA (sau 5, 15, 45 giây).
   - Các lỗi khác thì báo cho người dùng. Mất kết nối hoặc hết giờ chờ không có nghĩa là upstream đã dừng; xem thư mục kết quả trước khi gửi lại.
3. **Lỗi thường gặp:**
   - 401: sai key.
   - 400/422: sai tổ hợp hoặc sai kiểu dữ liệu; giữ nguyên lựa chọn của người dùng, sửa đúng chỗ sai.
   - 403: tài khoản chưa có quyền.
   - 503: máy chủ hết token.
   - 502/504: lỗi upstream.
4. **Giữ nhân vật giống nhau qua nhiều ảnh:**
   - Tạo một ảnh gốc nhân vật (toàn thân, nền trơn) và cho người dùng duyệt.
   - Mọi ảnh sau đó truyền ảnh gốc bằng `--ref`, prompt ghi rõ "giữ nguyên khuôn mặt, kiểu tóc, trang phục của nhân vật trong ảnh".
5. **Prompt:**
   - Viết bằng tiếng Anh cho ổn định; nội dung tiếng Việt thì mô tả rõ bằng lời.
   - Nêu phong cách, khung hình, ánh sáng, và những thứ không muốn có (chữ, logo, watermark).
   - Không tạo người thật dễ nhận diện, nội dung giả mạo hay thương hiệu của người khác.
6. **Mở kết quả bằng công cụ đọc ảnh và tự soi** (tay, mặt, chữ lạ) trước khi đưa người dùng.
7. Video Omni/Veo không có độ phân giải tuỳ chọn, cũng không phóng to video có sẵn được.
8. Máy chủ hiện tại (ghi ngày 21/11/2026) **không có tài khoản Pro**:
   - `gemini-3.0-pro-image` và mọi cỡ **2K/4K** đều báo lỗi "需要 Pro 账号".
   - Dùng `gemini-3.1-flash-image` cỡ **1K**: ảnh dọc ra 768×1376, định dạng JPEG.
   - Lỗi này đến ngay lúc bắt đầu, chưa tạo ra ảnh nào.
9. Ảnh Gemini có dấu ✦ nhỏ ở góc dưới phải. Cắt hoặc che đi trước khi dùng.

## Ảnh AI → SVG (tuỳ chọn)

Muốn đổi ảnh thành vector để dựng chuyển động bằng code:
- Dùng VTracer. Cần người dùng đồng ý cài: `python3 -m venv ~/.venvs/vtracer && ~/.venvs/vtracer/bin/pip install vtracer`.
- Gen ảnh theo kiểu "flat cel shading, clean bold outlines, limited palette, plain background" thì vector hoá mới đẹp.
- Ảnh nhiều chuyển màu mềm sau khi vector hoá sẽ thành nhiều mảng màu như poster.
- Số đo trên ảnh 768×1376 (21/11/2026):
  - Mức **chi tiết**: `filter_speckle=4, color_precision=6, layer_difference=16`. Gần như giống ảnh gốc, khoảng 2.000–3.300 mảng, 1–1,6 MB.
  - Mức **phẳng**: `filter_speckle=12, color_precision=5, layer_difference=40`. Khoảng 150–350 mảng, 130–350 KB. Mất nét mực trên mặt và nếp quần áo; ảnh tương phản mạnh (nền sáng, áo trắng) giữ tốt hơn ảnh tối.
- Gọi trong Python: `vtracer.convert_image_to_svg_py(in, out, colormode="color", hierarchical="stacked", mode="spline", ...)`.
- Đừng lấy SVG thay ảnh gốc cho khung hình 1080×1920: ở mức vài nghìn mảng, nét mực mảnh và hoa văn nhỏ bị gộp thành mảng loang, người xem thấy mờ (Mả Kết, 22/11/2026). Muốn nét thì phóng ảnh gốc 2× bằng lanczos + unsharp.
- SVG ra là các mảng màu chồng lên nhau, **không tách sẵn tay, mặt hay tóc**. Muốn nhân vật cử động thì phải gen riêng từng lớp, hoặc tự cắt mảng theo vùng.

## Kiểm tra script

`python3 ~/.claude/skills/flow2api/scripts/test_flow2api.py` dùng máy chủ giả, không tốn phí. Các test kiểm tra: kiểm tra tổ hợp, kiểu tham số, ảnh tham chiếu, SSE bị cắt nhỏ, CRLF, lỗi trong stream, thiếu `[DONE]`, 401/422 không lộ key, tải media an toàn, nối dài bằng `media_id`.
