# Chọn model, chi phí và giới hạn

Đọc khi cần chọn giữa các model hoặc báo chi phí cho người dùng. `python3 $S models` luôn là bảng tổ hợp đúng nhất; các con số credit dưới đây là số đo trên tài khoản Ultra, có thể đổi khi Flow đổi giá.

## Video

- **`omni-1.2-flash` (mặc định, `--mode auto`)**: 3–15 s ở cả 16:9 và 9:16, tự chọn tạo từ chữ hay từ 0–10 ảnh tham chiếu. 11–15 s cần tài khoản có gói Google AI Plus, Pro hoặc Ultra. Đo 25/11/2026: 720p 3 s 9 credit.
- **`--draft` (Omni 1.2 360p)**: 1/3 credit (3 s: 3 credit). Dùng để thử prompt và bố cục trước khi gen bản chuẩn.
- **Frames to Video của Omni 1.2 (`--mode i2v`)**: 1 ảnh là hình đầu, 2 ảnh là hình đầu và hình cuối (video bắt đầu đúng ảnh đầu và kết thúc đúng ảnh cuối, đã kiểm bằng cách trích khung). Hình cuối chỉ có ở 3–10 s; 11–15 s chỉ nhận hình đầu. Không có `--mode i2v` thì ảnh được hiểu là ảnh tham chiếu, không phải khung hình. 720p: 3 s 9 credit, 4 s 12.
- **extend / edit (chỉ Omni 1.2, 720p)**: chạy trên đúng tài khoản và project đã tạo video nguồn. Video làm ngoài server này thì thêm `--source-project <project id>`. `extend` nối thêm 3–10 s, không nhận ảnh, 3 s tốn 9 credit. `edit` cần `--duration` đúng độ dài video nguồn, 3 s tốn 9 credit.
- **Veo 3.1** (`veo-3.1-lite`, `veo-3.1-fast`, `veo-3.1-quality`): chọn `--mode` rõ ràng. `t2v` 4/6/8 s, `i2v` 4/6 s với 1–2 ảnh (đầu, cuối), `r2v` 8 s với 1–3 ảnh (không có ở quality). Script không đoán `i2v` hay `r2v` khi có `--ref`, vì đoán sai là mất tiền. Đo: lite 4 s khoảng 5 credit, fast 4 s 10, fast r2v 8 s 20, **quality 4 s 100** (hỏi người dùng trước khi dùng quality).
- **`veo-3.1-lite-lower-priority`**: **0 credit**, cùng tổ hợp với Lite (`t2v` 4/6/8 s, `i2v` 4/6 s, `r2v` 8 s). Đo 25/11/2026: 4 job thành công, số dư không đổi, thời gian 49–149 s (Lite thường 47–152 s). Flow xếp loại này sau job trả phí nên lúc đông có thể chờ lâu hơn. Dùng khi cần thử nhiều lần.
- **Model sắp bị gỡ**: `check` liệt kê kèm ngày. Đừng chọn chúng cho việc mới.
- Quyền truy cập Veo theo từng tài khoản và từng model; nếu một tài khoản bị từ chối, gateway tự chuyển sang tài khoản khác.
- Video không có độ phân giải tuỳ chọn ngoài `--draft`, và không phóng to video có sẵn được.

## Ảnh

- `gemini-3.1-flash-image` (mặc định, 1K), `gemini-3.1-flash-lite-image` (nhanh, rẻ), `gemini-3.0-pro-image` (đẹp nhất). Cỡ 2K/4K và model pro tuỳ gói của tài khoản; thiếu quyền thì lỗi đến ngay lúc bắt đầu, chưa tạo gì.
- Thời gian một ảnh (đo từ nhật ký server): `flash-lite` khoảng 21 s; `flash` 1K khoảng 47–73 s; cỡ 2K thêm 17–24 s phóng lớn; ảnh tham chiếu thêm 15–17 s mỗi ảnh ở lần tải đầu (xem "Ảnh tham chiếu" trong SKILL.md).
- Ảnh Gemini có dấu ✦ nhỏ ở góc dưới phải: cắt hoặc che trước khi dùng.
