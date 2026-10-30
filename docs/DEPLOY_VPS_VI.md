# Chạy Flow2API trên VPS Linux bằng Docker Compose

Bản này tích hợp Chrome thông thường, màn hình ảo và noVNC. Bạn đăng nhập Google/Flow từ trình duyệt trên máy mình; Chrome thực sự chạy trên VPS. Database và profile trình duyệt nằm trong volume Docker, tách khỏi image.

## 1. Chuẩn bị VPS

- Linux **amd64/x86_64**. Bản Chrome này không hỗ trợ VPS ARM64.
- Docker Engine đang chạy, Docker Compose **v2.20 trở lên**, Python 3 và tar.
- Tài khoản SSH có quyền sử dụng Docker.

Kiểm tra:

```bash
uname -m
docker info --format '{{.Architecture}}'
docker compose version
python3 --version
```

Nếu chưa có Docker, cài theo hướng dẫn chính thức cho [Ubuntu](https://docs.docker.com/engine/install/ubuntu/) hoặc [Debian](https://docs.docker.com/engine/install/debian/). Trên Ubuntu/Debian, có thể cài Python và tar bằng `sudo apt-get install python3 tar`. Nếu Docker yêu cầu quyền root, dùng `sudo` nhất quán cho các lệnh setup/Compose bên dưới.

## 2. Đưa bản code đã sửa lên VPS

Dùng gói `flow2api-vps.tar.gz` được tạo từ workspace hiện tại. Gói không chứa tài khoản, cookie, profile, log hay khóa cấu hình trên máy phát triển. Không chỉ pull image upstream vì image đó không tự chứa những thay đổi local này.

Từ máy của bạn, thay `USER` và `VPS_IP` bằng thông tin SSH thật:

```bash
scp flow2api-vps.tar.gz USER@VPS_IP:~/
```

Trên VPS:

```bash
mkdir -p ~/flow2api
tar -xzf ~/flow2api-vps.tar.gz -C ~/flow2api
cd ~/flow2api
bash docker/setup-vps.sh
```

Script sẽ kiểm tra Docker/kiến trúc, tạo `.env.vps` với mật khẩu quản trị và API key ngẫu nhiên, build image từ code này, rồi đợi dịch vụ khỏe. Lần build đầu phải tải Chrome và thư viện nên phụ thuộc tốc độ mạng VPS. Chạy lại script giữ nguyên thông tin đã tạo, không tự đổi mật khẩu.

Xem thông tin **đăng nhập ban đầu** ngay trên VPS:

```bash
python3 docker/setup_vps.py --show-credentials
```

File `.env.vps` được đặt quyền `600`. Khi bạn đổi mật khẩu hoặc API key trong giao diện, database là nguồn cấu hình chính; các giá trị ban đầu trong file không tự ghi đè database.

## 3. Mở trang quản lý qua SSH tunnel

Mặc định ứng dụng chỉ bind `127.0.0.1:8000` trên VPS. Chưa cần domain và không cần mở cổng VNC ra Internet.

Chạy lệnh sau **trên máy của bạn**, giữ cửa sổ SSH này mở:

```bash
ssh -N -L 18000:127.0.0.1:8000 USER@VPS_IP
```

Mở [http://127.0.0.1:18000/manage](http://127.0.0.1:18000/manage) và đăng nhập bằng tài khoản vừa tạo. Cổng local `18000` tránh trùng server phát triển đang chạy ở `8000`. Nếu cổng VPS đã đổi trong `.env.vps`, thay số `8000` phía sau bằng cổng đó.

## 4. Thêm tài khoản Google/Flow

1. Chọn **Thêm tài khoản bằng trình duyệt**, nhập email Google.
2. Chrome trên VPS mở profile riêng. Tài khoản ở trạng thái **Chờ đăng nhập**.
3. Chọn **Mở màn hình VPS**. Trang noVNC dùng phiên quản trị hiện tại, không yêu cầu thêm mật khẩu VNC.
4. Thao tác trong Chrome để đăng nhập Google/Flow và hoàn tất xác minh.
5. Đóng **toàn bộ cửa sổ thuộc profile đăng nhập đó**. Đóng tab noVNC chỉ ngắt màn hình từ xa, không đóng Chrome.
6. Ứng dụng mở lại profile trong nền, kiểm tra đúng email và phiên Flow, lưu cookie rồi bật tài khoản khi thành công.

Các lần đồng bộ sau chạy nền theo chu kỳ tài khoản. Cần bật đồng bộ trình duyệt, tự động kiểm tra phiên chung và tự động làm mới riêng tài khoản. Phần này hoạt động độc lập với nhà cung cấp CAPTCHA. Google có thể yêu cầu đăng nhập lại; lúc đó mở lại profile và thao tác qua màn hình VPS.

Trước khi tạo ảnh/video, cấu hình phương thức giải CAPTCHA trong **Cài đặt**: nhập khóa nhà cung cấp nếu dùng dịch vụ bên ngoài, hoặc chọn chế độ trình duyệt phù hợp. Đăng nhập cookie không tự cấu hình khóa giải CAPTCHA.

## 5. Xem trạng thái và cập nhật

Từ thư mục `~/flow2api`:

```bash
docker compose --env-file .env.vps -f docker-compose.vps.yml ps
docker compose --env-file .env.vps -f docker-compose.vps.yml logs --tail=100 flow2api-vps
```

Sau khi chép bản code mới vào **cùng thư mục** và giữ `.env.vps`:

```bash
bash docker/setup-vps.sh
```

Named volume giữ database và `managed_browser_profiles` qua việc tạo lại container. Project mặc định là `flow2api-vps`; dùng cùng project khi cập nhật. `docker compose down` giữ volume; `down -v` xóa cả dữ liệu nên không dùng để cập nhật thông thường.

Để tạo gói mới từ workspace phát triển:

```bash
python3 docker/package_vps.py
```

Gói được ghi vào `dist/flow2api-vps.tar.gz`. File `.dockerignore` và trình đóng gói cùng loại profile/cookie/cấu hình thật khỏi bản build.

## 6. Sao lưu

Tạm dừng ứng dụng để browser và SQLite ghi xong trước khi sao lưu:

```bash
mkdir -p backups
docker compose --env-file .env.vps -f docker-compose.vps.yml stop flow2api-vps
docker compose --env-file .env.vps -f docker-compose.vps.yml run --rm --no-deps --entrypoint tar flow2api-vps -czf - -C /app data > backups/flow2api-data.tar.gz
docker compose --env-file .env.vps -f docker-compose.vps.yml start flow2api-vps
```

Lưu riêng `.env.vps`. Bản sao dữ liệu chứa phiên Google, cần giữ riêng như thông tin đăng nhập. Cần tạo backup ngay trên VPS; profile Chrome từ Windows không phải bản di chuyển đã được kiểm thử cho Linux.

## 7. Khi dùng domain/HTTPS

Luồng SSH ở trên chạy được mà không cần domain. Khi triển khai reverse proxy HTTPS, proxy phải chuyển tiếp cả HTTP và WebSocket, giữ Host gốc, và ứng dụng cần tin đúng IP proxy để nhận `X-Forwarded-Proto`. Compose nhận danh sách IP tin cậy qua `FLOW2API_TRUSTED_PROXY_IPS`; đặt giá trị đúng mạng của proxy trước khi tạo lại container. Chỉ đặt `FLOW2API_BIND_ADDRESS=0.0.0.0` khi bạn đã thiết kế đường truy cập HTTPS phù hợp.

noVNC và WebSocket được bảo vệ bằng cookie phiên quản trị cùng origin. Cổng RFB `5900` chỉ dùng trong loopback container, không được publish ra VPS. Đổi mật khẩu/đăng xuất sẽ thu hồi phiên và ngắt màn hình từ xa. Phiên quản trị cũng mất sau khi ứng dụng khởi động lại, cần đăng nhập lại trang quản lý.

## Khắc phục lỗi thường gặp

- **Docker không truy cập được:** kiểm tra daemon và quyền sử dụng Docker của tài khoản SSH.
- **VPS ARM64:** setup sẽ từ chối; dùng VPS amd64/x86_64 cho image Chrome này.
- **Chrome không mở / lỗi sandbox:** kiểm tra log và cấu hình seccomp/user namespace của host. Bản Compose dùng user thường và sandbox, đã kiểm thử trên Linux container; một số kernel hoặc chính sách VPS có thể cần quản trị viên điều chỉnh.
- **Màn hình trống:** trở lại quản lý để bấm mở trình duyệt; desktop trống khi chưa có cửa sổ Chrome là bình thường.
- **Đăng nhập xong vẫn chờ:** đóng tất cả cửa sổ của profile đó; chỉ đóng tab noVNC chưa đủ.
- **Lỗi kết nối sau restart/đổi mật khẩu:** đăng nhập lại trang quản lý rồi mở màn hình VPS.
- **Google từ chối đăng nhập:** kiểm tra trong Chrome qua màn hình VPS; chấp nhận đăng nhập vẫn do Google quyết định, các kiểm thử đóng gói không thay thế bước xác minh tài khoản thật.
