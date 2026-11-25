---
name: flow2api
description: Generates images and videos through the user's own Flow2API gateway (Nano Banana / Gemini image, Omni 1.2, Veo 3.1) from any project, including cheap 360p drafts, video extend and video edit. Use when the user asks to "gen ảnh", "tạo ảnh AI", "tạo video AI", make character art, keyframes, thumbnails, image edits, image-to-video, reference-to-video, or to extend or edit a Flow video, or mentions Flow2API, Veo, Omni or nano banana. Also use to check the gateway connection, see which models a key may use, or recover a job after a dropped connection. Every generation is paid, so never run one the user did not ask for. Not for operating or debugging the gateway server itself (use flow2api-gateway-ops).
license: Proprietary
metadata:
  project: flow2api
---

# Flow2API (client)

Gọi máy chủ Flow2API của người dùng để tạo ảnh và video, từ bất kỳ dự án nào. Một script Python thuần (chỉ thư viện chuẩn, Python 3.9+): `scripts/flow2api.py`. Bảng model và tổ hợp hợp lệ nằm ở `references/contract.json`, sinh trực tiếp từ gateway; script kiểm tra trước khi gửi nên tổ hợp sai bị từ chối miễn phí.

## Cấu hình

Script đọc `FLOW2API_BASE_URL` (mặc định `http://localhost:8000`, không có `/v1`; giữ tiền tố proxy nếu có) và `FLOW2API_API_KEY` từ môi trường, nếu không có thì từ `~/.config/flow2api/env` (dòng `KEY=value`, quyền 600).

**Key là bí mật**: không hỏi key qua chat, không in, không ghi vào file dự án hay tham số lệnh. Nếu `check` báo "CHƯA ĐẶT", bảo người dùng tự chạy trong terminal của họ:

```bash
mkdir -p ~/.config/flow2api && printf 'Flow2API key: ' && IFS= read -rs K && printf 'FLOW2API_BASE_URL=http://localhost:8000\nFLOW2API_API_KEY=%s\n' "$K" > ~/.config/flow2api/env && chmod 600 ~/.config/flow2api/env && unset K && echo
```

## Lệnh

```bash
S=~/.claude/skills/flow2api/scripts/flow2api.py
python3 $S check      # miễn phí, chạy đầu tiên: key, model key này được dùng, model sắp bị gỡ, có job API không
python3 $S models     # bảng model/mode/aspect/giây/số ảnh
python3 $S image "prompt" --aspect 9:16 --size 2K --out <thư-mục> --name <tên>
python3 $S image "giữ nhân vật, đổi bối cảnh" --ref nhanvat.png --out ...        # ảnh thành ảnh
python3 $S video "prompt" --aspect 9:16 --duration 8 --out ...                   # Omni 1.2, mặc định
python3 $S video "prompt" --draft --duration 3 --out ...                         # nháp 360p, 1/3 credit
python3 $S video "camera chậm" --ref a.png --ref b.png --out ...                 # Omni: 0–10 ảnh tham chiếu
python3 $S video "..." --model veo-3.1-lite --mode i2v --ref dau.png [--ref cuoi.png]
python3 $S video "đi tiếp" --mode extend --source <media_id> --duration 5 --out ...   # nối thêm 3–10 s
python3 $S video "đổi màu áo" --mode edit --source <media_id> --duration <độ dài video nguồn>
python3 $S jobs                  # job gần đây của key này
python3 $S job <job_id> --out .. # lấy kết quả job đã gửi (sau khi mất kết nối)
python3 $S batch jobs.jsonl --parallel 3   # mỗi dòng: {"kind":"image","prompt":"...","aspect":"9:16","ref":["a.png"],"out":"...","name":"..."}
```

- Thêm `--dry-run` vào `image`, `video`, `batch`: kiểm tra và in request, không gửi gì, miễn phí.
- Prompt dài: `--prompt-file file.txt`.
- Mỗi kết quả lưu `<name>.png|.mp4` và `<name>.json` (model, cấu hình, prompt, `job_id`, `media_id`). **Giữ `media_id`** để extend/edit sau này.
- Tiến trình in ra stderr; `<name>.job` ghi job id ngay khi server nhận.

## Chọn model

Chạy `models` thay vì nhớ bảng. Điều cần biết để chọn:

- **Video mặc định `omni-1.2-flash`** (`--mode auto`): 3–15 s ở cả 16:9 và 9:16, tự chọn tạo từ chữ hay từ 0–10 ảnh tham chiếu. 11–15 s cần tài khoản có gói Google AI Plus, Pro hoặc Ultra.
- **`--draft`** (Omni 1.2 360p) tốn 1/3 credit: dùng để thử prompt và bố cục trước khi gen bản chuẩn.
- **Veo 3.1** (`veo-3.1-lite`, `veo-3.1-fast`, `veo-3.1-quality`): chọn `--mode` rõ ràng. `t2v` 4/6/8 s, `i2v` 4/6 s với 1–2 ảnh (đầu, cuối), `r2v` 8 s với 1–3 ảnh (không có ở quality). Script không đoán `i2v` hay `r2v` khi có `--ref`, vì đoán sai là mất tiền. Chi phí đo ngày 25/11/2026 trên tài khoản Ultra: lite 4 s khoảng 5 credit, fast 4 s 10, fast r2v 8 s 20, **quality 4 s 100**; hỏi người dùng trước khi dùng quality. Quyền truy cập theo từng tài khoản và từng model; nếu một tài khoản bị từ chối, gateway tự chuyển sang tài khoản khác.
- **Model Flow sắp gỡ**: `check` liệt kê kèm ngày. Đừng chọn chúng cho việc mới.
- **extend/edit** (chỉ Omni 1.2, 720p): chạy trên đúng tài khoản và project đã tạo video nguồn. Video làm ngoài server này thì thêm `--source-project <project id>`. `extend` không nhận ảnh. `edit` cần `--duration` đúng độ dài video nguồn.
- **Ảnh**: `gemini-3.1-flash-image` (mặc định, 1K), `gemini-3.1-flash-lite-image` (nhanh, rẻ), `gemini-3.0-pro-image` (đẹp nhất). Cỡ 2K/4K và model pro tuỳ gói của tài khoản; nếu thiếu quyền, lỗi đến ngay lúc bắt đầu, chưa tạo gì.

## Quy tắc

1. **Tính phí.** Chỉ chạy `image`/`video` khi người dùng đã yêu cầu đúng sản phẩm đó. Với lô lớn hoặc video, nói trước số lần tạo và chờ đồng ý; thử bằng `--draft` hoặc `--dry-run` trước khi gen bản chuẩn. `check`, `models`, `jobs`, `--dry-run` chạy thoải mái.
2. **Không gửi lại mù quáng.** Script gửi qua job API kèm `Idempotency-Key`, nên mất kết nối hay thử lại không trả phí hai lần. Mất kết nối hoặc hết giờ chờ không có nghĩa là server đã dừng: chạy `jobs`, rồi `job <id>` để lấy kết quả. Không tự gen lại.
3. **429 và quyền.** Script tự chờ `Retry-After` của server (tối đa 4 lần). Hai lỗi không retry, báo người dùng:
   - `credit_budget_exceeded`: key hết hạn mức credit của tháng, tới đầu tháng sau mới dùng lại.
   - `model_not_allowed` (403): key không được dùng model đó; `check` cho biết model nào được phép.
4. **Lỗi khác:** 401 sai key; 400/422 sai tổ hợp, thiếu prompt hoặc model đã bị Flow gỡ (giữ lựa chọn của người dùng, sửa đúng chỗ sai); 503 không tài khoản nào phục vụ model; 502/504 lỗi upstream. Job báo "server khởi động lại": credit có thể đã trừ, xem `jobs` hoặc trang quản trị trước khi gửi lại.
5. **Giữ nhân vật giống nhau qua nhiều ảnh:** tạo một ảnh gốc nhân vật (toàn thân, nền trơn), cho người dùng duyệt, rồi truyền nó bằng `--ref` ở mọi ảnh sau; prompt ghi rõ "giữ nguyên khuôn mặt, kiểu tóc, trang phục của nhân vật trong ảnh".
6. **Prompt:** viết bằng tiếng Anh cho ổn định; nêu phong cách, khung hình, ánh sáng và những thứ không muốn có (chữ, logo, watermark). Không tạo người thật dễ nhận diện, nội dung giả mạo hay thương hiệu của người khác.
7. **Soi kết quả** bằng công cụ đọc ảnh (tay, mặt, chữ lạ) trước khi đưa người dùng. Ảnh Gemini có dấu ✦ nhỏ ở góc dưới phải: cắt hoặc che trước khi dùng.
8. Video không có độ phân giải tuỳ chọn ngoài `--draft`, và không phóng to video có sẵn được.

## Khi gateway đổi

Skill này nằm trong repo `flow2api` (`.agents/skills/flow2api`); `~/.claude/skills/flow2api` là symlink tới đó. Khi gateway thêm hoặc bỏ model, chạy trong repo `.venv/bin/python3.11 .agents/skills/flow2api/scripts/sync_contract.py` để cập nhật `references/contract.json`; test `tests/test_flow2api_skill.py` báo lỗi nếu quên. Đừng sửa tay file đó. Test của chính skill (server giả, miễn phí): `python3 scripts/test_flow2api.py`.

## Ảnh AI → SVG (tuỳ chọn)

Đọc [references/image-to-svg.md](references/image-to-svg.md) khi người dùng muốn đổi ảnh sang vector.
