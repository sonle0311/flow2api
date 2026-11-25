# Ảnh AI → SVG (tuỳ chọn)

Đọc khi người dùng muốn đổi ảnh thành vector để dựng chuyển động bằng code.

- Dùng VTracer. Cần người dùng đồng ý cài: `python3 -m venv ~/.venvs/vtracer && ~/.venvs/vtracer/bin/pip install vtracer`.
- Gen ảnh theo kiểu "flat cel shading, clean bold outlines, limited palette, plain background" thì vector hoá mới đẹp.
- Ảnh nhiều chuyển màu mềm sau khi vector hoá sẽ thành nhiều mảng màu như poster.
- Số đo trên ảnh 768×1376 (21/11/2026):
  - Mức **chi tiết**: `filter_speckle=4, color_precision=6, layer_difference=16`. Gần như giống ảnh gốc, khoảng 2.000–3.300 mảng, 1–1,6 MB.
  - Mức **phẳng**: `filter_speckle=12, color_precision=5, layer_difference=40`. Khoảng 150–350 mảng, 130–350 KB. Mất nét mực trên mặt và nếp quần áo; ảnh tương phản mạnh (nền sáng, áo trắng) giữ tốt hơn ảnh tối.
- Gọi trong Python: `vtracer.convert_image_to_svg_py(in, out, colormode="color", hierarchical="stacked", mode="spline", ...)`.
- Đừng lấy SVG thay ảnh gốc cho khung hình 1080×1920: ở mức vài nghìn mảng, nét mực mảnh và hoa văn nhỏ bị gộp thành mảng loang, người xem thấy mờ (Mả Kết, 22/11/2026). Muốn nét thì phóng ảnh gốc 2× bằng lanczos + unsharp.
- SVG ra là các mảng màu chồng lên nhau, **không tách sẵn tay, mặt hay tóc**. Muốn nhân vật cử động thì phải gen riêng từng lớp, hoặc tự cắt mảng theo vùng.
