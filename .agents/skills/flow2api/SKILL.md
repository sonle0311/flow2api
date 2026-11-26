---
name: flow2api
description: Generates images and videos through the user's own Flow2API gateway (Nano Banana / Gemini image, Omni 1.2, Veo 3.1) from any project, one at a time or in large parallel batches, including cheap 360p drafts, start and end frames, video extend and edit. Use when the user asks to "gen ảnh", "tạo ảnh AI", "tạo video AI", make character art, keyframes, storyboards, thumbnails, image edits, image-to-video or reference-to-video, produce dozens of images, or extend or edit a Flow video, or mentions Flow2API, Veo, Omni or nano banana. Also use to check the gateway connection, see which models a key may use, or recover a job after a dropped connection. Every generation is paid, so never run one the user did not ask for. Not for operating or debugging the gateway server itself (use flow2api-gateway-ops).
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

## Quy trình chuẩn

1. `python3 $S check` (miễn phí): key có dùng được không, model key này được dùng, model sắp bị gỡ, có job API không.
2. **Lập kế hoạch rồi hỏi**: số sản phẩm, model, cỡ, ước tính thời gian và credit (xem [references/models-and-costs.md](references/models-and-costs.md)). Với lô lớn, video hoặc model đắt, chờ người dùng đồng ý trước khi gửi. Dùng `--dry-run` để kiểm tra miễn phí.
3. **Một sản phẩm** thì dùng lệnh đơn. **Hai sản phẩm trở lên thì dùng `batch`** (mục dưới), không viết vòng lặp gọi từng lệnh.
4. Soi kết quả (tay, mặt, chữ lạ) trước khi đưa người dùng; làm lại đúng phần hỏng.

## Lệnh

```bash
S=~/.claude/skills/flow2api/scripts/flow2api.py
python3 $S check                 # miễn phí, chạy đầu tiên
python3 $S models                # bảng model/mode/aspect/giây/số ảnh
python3 $S image "prompt" --aspect 9:16 --size 2K --out <thư-mục> --name <tên>
python3 $S image "giữ nhân vật, đổi bối cảnh" --ref nhanvat.png --out ...        # ảnh thành ảnh
python3 $S video "prompt" --aspect 9:16 --duration 8 --out ...                   # Omni 1.2, mặc định
python3 $S video "prompt" --draft --duration 3 --out ...                         # nháp 360p, 1/3 credit
python3 $S video "camera chậm" --ref a.png --ref b.png --out ...                 # Omni: 0–10 ảnh tham chiếu
python3 $S video "ngày thành đêm" --mode i2v --ref dau.png [--ref cuoi.png] --duration 5 --out ...   # hình đầu, hoặc đầu + cuối
python3 $S video "đi tiếp" --mode extend --source <media_id> --duration 5 --out ...   # nối thêm 3–10 s
python3 $S video "đổi màu áo" --mode edit --source <media_id> --duration <độ dài video nguồn>
python3 $S jobs                  # job gần đây của key này
python3 $S job <job_id> --out .. # lấy kết quả job đã gửi (sau khi mất kết nối)
python3 $S batch jobs.jsonl      # nhiều sản phẩm song song (mục dưới)
```

- `--dry-run` (cho `image`, `video`, `batch`): kiểm tra và in request, không gửi gì. `--prompt-file file.txt` cho prompt dài.
- Mỗi kết quả lưu `<name>.png|.mp4` và `<name>.json` (model, cấu hình, prompt, `job_id`, `media_id`). **Giữ `media_id`** để extend/edit. `<name>.job` ghi job id ngay khi server nhận.
- Model, thời lượng, chi phí: [references/models-and-costs.md](references/models-and-costs.md). Mặc định: video `omni-1.2-flash`, ảnh `gemini-3.1-flash-image` 1K.

## Làm nhiều ảnh hoặc video: dùng `batch`, đừng chạy tuần tự

Mỗi lệnh `image`/`video` đơn chờ xong rồi mới trả về, nên gọi liên tiếp là chạy **từng cái một**. Gateway có nhiều tài khoản và xử lý song song được. Đo ngày 26/11/2026 với `gemini-3.1-flash-image` 1K và một ảnh tham chiếu: 3 ảnh tuần tự mất 140 s (47 s mỗi ảnh); `batch` 12 ảnh, 6 cùng lúc, mất 114 s (9,5 s mỗi ảnh, 0 lỗi). Một phiên 38 ảnh 2K có 1–3 ảnh tham chiếu chạy tuần tự mất khoảng 1 giờ (87–125 s mỗi ảnh) trong khi server gần như rảnh.

```bash
# jobs.jsonl: mỗi dòng một sản phẩm, luôn đặt "name" duy nhất
{"kind":"image","prompt":"scene 01 ...","ref":["nhanvat.png"],"model":"gemini-3.1-flash-image","aspect":"16:9","size":"2K","out":"out","name":"scene-01"}
{"kind":"video","prompt":"...","mode":"i2v","ref":["dau.png","cuoi.png"],"duration":5,"out":"out","name":"clip-01"}
python3 $S batch jobs.jsonl --dry-run   # kiểm tra toàn bộ, đếm job sẽ chạy / đã có, chưa gửi gì
python3 $S batch jobs.jsonl             # mặc định 6 cùng lúc (--parallel N, tối đa 9)
```

- **Chạy nền** (công cụ chạy lệnh nền của agent, hoặc `... > batch.log 2>&1 &`) và báo tiến độ cho người dùng; mỗi job xong in một dòng, kết quả cũng ghi vào `jobs.jsonl.results.jsonl`. Đừng chặn cả phiên chờ và đừng poll dày: xem log mỗi vài phút.
- **Chạy lại không tốn thêm**: job có `name` đã có file kết quả thì bị bỏ qua. Bị ngắt hay có job lỗi thì chạy lại đúng lệnh cũ; chỉ phần thiếu được gửi. `--force` mới tạo lại tất cả. Job không có `name` sẽ bị tạo lại mỗi lần.
- **Dừng sớm**: `credit_budget_exceeded`, `model_not_allowed` hoặc 401 làm cả lô dừng gửi tiếp (mọi job còn lại sẽ lỗi y hệt); script in lý do và số job chưa chạy.
- Số 6 đã đo; lên 9 là giới hạn của script. Nếu thấy nhiều lỗi `UNUSUAL_ACTIVITY` hay 429 thì hạ `--parallel` xuống 3–4.
- Một job video có thể gửi cùng lô với ảnh; video giới hạn song song riêng (mặc định 6).

## Ảnh tham chiếu: gửi đúng file cũ để server dùng lại

Mỗi ảnh tham chiếu (cả hình đầu/cuối của Frames) phải được tải lên Flow trước khi gen, 15–17 s mỗi ảnh. Server nhớ ảnh đã tải theo **nội dung file** (SHA-256), từng tài khoản và project (mỗi tài khoản xoay 4 project, nên một ảnh mới tải tối đa 4 lần cho mỗi tài khoản rồi từ đó gần như 0 s; đo thật: 50–78 s tải ảnh giảm còn 7 ms).

- Dùng **cùng một file, không đổi byte** cho mọi lần: không đổi kích thước, không lưu lại, không xoá metadata giữa các lần gọi. Chỉ cần đổi 1 byte là bị coi ảnh mới.
- Đặt ảnh tham chiếu cố định (một bảng nhân vật, một ảnh phong cách) rồi truyền cùng file ở mọi job của lô, thay vì mỗi cảnh một biến thể.
- Nhiều job cùng ảnh mới chạy song song chỉ tải một lần (server gộp lại).

## Quy tắc

1. **Tính phí.** Chỉ chạy `image`/`video`/`batch` khi người dùng đã yêu cầu đúng sản phẩm đó và đồng ý kế hoạch. `check`, `models`, `jobs`, `--dry-run` chạy thoải mái. Thử bằng `--draft` hoặc `flash-lite` trước khi gen bản chuẩn.
2. **Không gửi lại mù quáng.** Script gửi qua job API kèm `Idempotency-Key`, nên mất kết nối hay thử lại không trả phí hai lần. Mất kết nối hoặc hết giờ chờ không có nghĩa là server đã dừng: chạy `jobs`, rồi `job <id>` để lấy kết quả. Không tự gen lại; với lô thì chạy lại lệnh `batch` cũ.
3. **429 và quyền.** Script tự chờ `Retry-After` của server (tối đa 4 lần). Hai lỗi không retry, báo người dùng: `credit_budget_exceeded` (key hết hạn mức credit tháng, tới đầu tháng sau mới dùng lại) và `model_not_allowed` (403, `check` cho biết model nào được phép).
4. **Lỗi khác:** 401 sai key; 400/422 sai tổ hợp, thiếu prompt hoặc model đã bị Flow gỡ (giữ lựa chọn của người dùng, sửa đúng chỗ sai); 503 không tài khoản nào phục vụ model; 502/504 lỗi upstream. Job báo "server khởi động lại": credit có thể đã trừ, xem `jobs` hoặc trang quản trị trước khi gửi lại. `UNUSUAL_ACTIVITY` thỉnh thoảng xuất hiện ở lần thử đầu và server tự thử lại; chỉ đáng lo khi lặp lại liên tục.
5. **Giữ nhân vật giống nhau:** tạo một ảnh gốc nhân vật (toàn thân, nền trơn), cho người dùng duyệt, rồi truyền nó bằng `--ref` ở mọi ảnh sau; prompt ghi rõ "giữ nguyên khuôn mặt, kiểu tóc, trang phục của nhân vật trong ảnh".
6. **Prompt:** viết bằng tiếng Anh cho ổn định; nêu phong cách, khung hình, ánh sáng và những thứ không muốn có (chữ, logo, watermark). Không tạo người thật dễ nhận diện, nội dung giả mạo hay thương hiệu của người khác.
7. **Chọn đúng việc tốn thời gian:** cỡ 2K thêm ~20 s mỗi ảnh; `flash-lite` nhanh gấp ~3 lần `flash`. Hỏi người dùng có cần 2K/model đẹp cho cả lô không, hay chỉ cho bản cuối.

## Khi gateway đổi

Skill này nằm trong repo `flow2api` (`.agents/skills/flow2api`); `~/.claude/skills/flow2api` là symlink tới đó. Khi gateway thêm hoặc bỏ model, chạy trong repo `.venv/bin/python3.11 .agents/skills/flow2api/scripts/sync_contract.py` để cập nhật `references/contract.json`; test `tests/test_flow2api_skill.py` báo lỗi nếu quên. Đừng sửa tay file đó. Test của chính skill (server giả, miễn phí): `python3 scripts/test_flow2api.py`.

## Ảnh AI → SVG (tuỳ chọn)

Đọc [references/image-to-svg.md](references/image-to-svg.md) khi người dùng muốn đổi ảnh sang vector.
