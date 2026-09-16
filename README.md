# Internal LLM Gateway

Gateway FastAPI dùng chung cho nhiều ứng dụng, cung cấp OpenAI-compatible Chat
Completions và tách model serving khỏi nghiệp vụ VMS.

## Phạm vi MVP

- `POST /v1/chat/completions`, gồm JSON và streaming SSE.
- `GET /v1/models` theo allowlist của API key.
- Runtime API key riêng cho từng project; key chỉ được lưu dưới dạng HMAC digest.
- Policy theo key: model, TPM/RPM, concurrency, input, output, timeout, metadata JSON và tags.
- PostgreSQL lưu project/key/usage/audit; Redis giữ distributed limits.
- Client tự gửi system prompt. Gateway chỉ chèn safety policy tối thiểu.
- Không thực thi tool và từ chối `tools`/`tool_choice`.
- Management API và UI nội bộ tại `/admin`.

## Admin Console

`/admin` là console quản trị light-first, không cần frontend build toolchain. Sau
khi xác thực bằng Platform Admin key hoặc Management key của project, console có
các màn hình độc lập:

- **Overview**: KPI project, API key, request, token và latency.
- **Projects**: tạo project, đổi tên/trạng thái và quản lý nhóm ứng dụng.
- **API Keys**: lọc, cấp, thu hồi, cấu hình policy và xem detail key; plaintext chỉ hiển thị một lần.
- **Usage**: biểu đồ theo thời gian và request metadata không chứa prompt.
- **Playground**: thử OpenAI-compatible Chat Completions bằng runtime key.
- **Settings**: model mappings, phiên bản và trạng thái dependency an toàn.

Management key được giữ trong `sessionStorage`, tồn tại khi reload và tự mất khi
đóng tab. Production phải phục vụ console qua HTTPS, hạn chế management paths
theo subnet/VPN và không chạy ứng dụng không tin cậy trên cùng origin.

Các API đọc dữ liệu cho console:

```text
GET /management/v1/dashboard?hours=24&project_id=...
GET /management/v1/keys?project_id=...&kind=runtime&status=active
GET /management/v1/projects/{project_id}/keys
GET /management/v1/usage/summary?hours=24&project_id=...
GET /management/v1/system/status
```

Mọi endpoint đều áp dụng project scope tại backend. Response danh sách key không
chứa plaintext hoặc digest; system status không trả connection URL hay secret.

## Khởi động

Model backend (vLLM hoặc SGLang) phải được chạy độc lập và cung cấp OpenAI API.

```bash
cp .env.example .env
```

Thay toàn bộ giá trị `replace-with-*`, đặc biệt:

- `POSTGRES_PASSWORD`
- `LLM_GATEWAY_DATABASE_URL` phải dùng cùng mật khẩu PostgreSQL.
- `LLM_GATEWAY_KEY_PEPPER` là secret ngẫu nhiên tối thiểu 32 ký tự; không thay đổi
  sau khi đã phát hành key, nếu không toàn bộ key cũ sẽ mất hiệu lực.
- `LLM_GATEWAY_PLATFORM_ADMIN_KEY` là key đăng nhập quản trị bootstrap.
- `LLM_GATEWAY_UPSTREAM_BASE_URL` trỏ tới `/v1` của vLLM/SGLang.

Sau đó:

```bash
docker compose up --build -d
```

Các URL mặc định:

- Admin UI: `http://HOST:18083/admin`
- Swagger: `http://HOST:18083/docs`
- Liveness: `http://HOST:18083/health/live`
- Readiness: `http://HOST:18083/health/ready`

Production phải đặt Gateway sau HTTPS/reverse proxy. Management paths nên chỉ
được mở trên subnet quản trị.

## Tạo project và runtime key

Có thể dùng UI hoặc Management API:

```bash
curl -X POST http://127.0.0.1:18083/management/v1/projects \
  -H "Authorization: Bearer YOUR_PLATFORM_ADMIN_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "name":"VMS Agent"
  }'
```

Lấy `project_id` rồi cấp runtime key:

```bash
curl -X POST http://127.0.0.1:18083/management/v1/projects/PROJECT_ID/keys \
  -H "Authorization: Bearer YOUR_PLATFORM_ADMIN_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "name":"vms-production",
    "kind":"runtime",
    "tpm":120000,
    "rpm":600,
    "allowed_models":["qwen3-8b"],
    "max_concurrency":2,
    "max_input_characters":20000,
    "max_output_tokens":2048,
    "timeout_seconds":60,
    "metadata":{"environment":"production","owner":"vms"},
    "tags":["vms","production"]
  }'
```

Plaintext key chỉ xuất hiện trong response này. Điền key vào
`VMS_AGENT_MODEL_API_KEY` của `vms_ai_agent`.

Các runtime settings của API key là optional. Nếu để trống khi tạo, gateway ghi
default từ `resources/configs/app.yaml` vào key; sau đó mỗi key có policy độc
lập. `tpm` để trống nghĩa là không giới hạn TPM; các giới hạn còn lại luôn có
giá trị hiệu lực trên key và không kế thừa từ project. Project chỉ dùng để nhóm
quản lý, trạng thái và báo cáo usage.
Chỉ Platform Admin có thể tạo/cập nhật các settings này. Metadata phải là JSON
object và tags là mảng nhãn ngắn, không trùng.

## Gọi Chat Completions

```bash
curl -X POST http://127.0.0.1:18083/v1/chat/completions \
  -H "Authorization: Bearer YOUR_RUNTIME_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model":"qwen3-8b",
    "messages":[
      {"role":"system","content":"Bạn là trợ lý nghiệp vụ VMS."},
      {"role":"user","content":"Xin chào"}
    ],
    "temperature":0.2,
    "max_tokens":512
  }'
```

Để streaming, thêm `"stream": true`.

## Chạy local và test

```bash
python3 -m pip install -e '.[dev]'
python3 -m pytest
python3 -m pytest --cov=app --cov-report=term-missing
```

Migration production:

```bash
alembic upgrade head
```

Nếu database hiện hữu được tạo trước đây bằng `auto_create_schema` và chưa có
bảng `alembic_version`, chỉ stamp sau khi đã xác nhận schema đang đúng revision
ban đầu, rồi mới chạy migration index của Admin Console:

```bash
alembic stamp 20260904_0001
alembic upgrade head
```

`database.auto_create_schema` đang bật để MVP khởi động thuận tiện. Khi vận hành
ổn định, đặt thành `false` và chạy Alembic trong pipeline deployment.
