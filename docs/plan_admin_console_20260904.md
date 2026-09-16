# Kế hoạch triển khai Admin Console

## 1. Mục tiêu và phạm vi

Thiết kế lại `/admin` thành ứng dụng quản trị light-first có sidebar, đồng thời
bổ sung các API đọc dữ liệu cần thiết cho Overview, API Keys, Usage và Settings.
Chat Completions API, model serving, schema cơ sở dữ liệu và cách phát hành API
key không thay đổi.

## 2. Bối cảnh và ràng buộc

- Backend: FastAPI, SQLAlchemy async, PostgreSQL, Redis.
- Frontend: HTML/CSS/JavaScript thuần, được FastAPI phục vụ trực tiếp.
- Không thêm Node.js, bundler hoặc thư viện biểu đồ.
- Management API tiếp tục xác thực bằng Bearer key.
- Platform Admin xem toàn hệ thống; Client Admin chỉ xem project của mình.
- Không API nào được trả digest, plaintext key đã cấp, secret hoặc prompt.
- Management key được lưu trong `sessionStorage` theo quyết định đã duyệt. Đây
  là đánh đổi có chủ ý cho hệ thống nội bộ; CSP, không dùng `innerHTML` với dữ
  liệu động và HTTPS ở reverse proxy là các biện pháp giảm rủi ro XSS.

## 3. Yêu cầu EARS

| ID | Yêu cầu |
|---|---|
| ADM-01 | WHEN người dùng mở `/admin` THE SYSTEM SHALL hiển thị màn hình xác thực trước khi tải dữ liệu quản trị. |
| ADM-02 | WHEN management key hợp lệ THE SYSTEM SHALL lưu key trong `sessionStorage` của tab và hiển thị console theo đúng quyền. |
| ADM-03 | WHEN management API trả 401 THE SYSTEM SHALL xóa credential trong phiên và quay về màn hình xác thực. |
| ADM-04 | WHEN Platform Admin mở Overview THE SYSTEM SHALL trả và hiển thị số project, key và usage tổng hợp trong khoảng thời gian hợp lệ. |
| ADM-05 | WHEN Client Admin yêu cầu dữ liệu THE SYSTEM SHALL giới hạn mọi project, key và usage theo `project_id` trong principal. |
| ADM-06 | WHEN người dùng mở Projects THE SYSTEM SHALL cho phép tìm, lọc, tạo và cập nhật project theo quyền hiện có. |
| ADM-07 | WHEN người dùng mở API Keys THE SYSTEM SHALL chỉ hiển thị metadata an toàn và cho phép tạo hoặc revoke key theo quyền. |
| ADM-08 | WHEN key mới được tạo THE SYSTEM SHALL hiển thị plaintext đúng một lần và không bao giờ trả lại plaintext qua API danh sách. |
| ADM-09 | WHEN người dùng mở Usage THE SYSTEM SHALL hiển thị KPI, chuỗi thời gian và request metadata mà không chứa prompt. |
| ADM-10 | WHEN dữ liệu usage rỗng THE SYSTEM SHALL hiển thị trạng thái rỗng và các KPI bằng 0 thay vì dữ liệu giả. |
| ADM-11 | WHEN người dùng mở Playground THE SYSTEM SHALL gửi system prompt và user request tới Chat API bằng runtime key chỉ giữ trong bộ nhớ. |
| ADM-12 | WHEN người dùng mở Settings THE SYSTEM SHALL chỉ trả cấu hình public và trạng thái dependency, không trả URL hoặc secret nội bộ. |
| ADM-13 | WHEN viewport nhỏ THE SYSTEM SHALL chuyển sidebar thành drawer và giữ mọi chức năng thao tác được. |
| ADM-14 | WHEN người dùng đổi theme THE SYSTEM SHALL lưu preference không nhạy cảm trong `localStorage`. |
| ADM-15 | WHEN hai admin cập nhật cùng project THE SYSTEM SHALL giữ optimistic version và trả conflict thay vì ghi đè âm thầm. |

## 4. Kiến trúc tích hợp

```text
Admin SPA
  ├─ session state: management key, principal, selected project
  ├─ hash router: overview/projects/keys/usage/playground/settings
  └─ API client
       │ Authorization: Bearer <management key>
       ▼
FastAPI Management routes
  ├─ kiểm tra principal và project scope
  ├─ dashboard / key metadata / usage summary / safe status
  └─ SqlRepository
       ▼
PostgreSQL: projects, api_keys, usage_events

Playground ── Authorization: Bearer <runtime key> ──► /v1/chat/completions
```

## 5. API dự kiến

| Method | Endpoint | Kết quả |
|---|---|---|
| GET | `/management/v1/dashboard?hours=24` | KPI project, key và usage theo scope. |
| GET | `/management/v1/keys?project_id=&kind=&status=&limit=` | Metadata key đã lọc. |
| GET | `/management/v1/projects/{id}/keys` | Metadata key của một project. |
| GET | `/management/v1/usage/summary?hours=&project_id=` | KPI và chuỗi thời gian usage. |
| GET | `/management/v1/system/status` | Tên, phiên bản, prefixes, model map và trạng thái dependency an toàn. |

`hours` được giới hạn từ 1 đến 2160 (90 ngày), `limit` từ 1 đến 1000. API
không cung cấp phân trang cursor trong giai đoạn này vì quy mô nội bộ nhỏ.

## 6. So sánh phương án

| Phương án | Ưu điểm | Nhược điểm | Phức tạp | Bảo mật | Chọn |
|---|---|---|---|---|---|
| SPA thuần + hash router | Không build, tương thích triển khai hiện tại | Tự quản lý component/state | Thấp | Trung bình | Có |
| React + Vite | Component ecosystem tốt | Thêm toolchain và artifact | Trung bình | Trung bình | Không |
| Server-rendered HTMX | Ít state client | Tăng coupling route/template | Trung bình | Tốt | Không |

| Cách thống kê | Ưu điểm | Nhược điểm | Phức tạp | Chọn |
|---|---|---|---|---|
| Aggregate tại PostgreSQL | Ít dữ liệu truyền, mở rộng tốt | Query phức tạp hơn | Trung bình | Có |
| Tải event rồi aggregate Python | Dễ viết | Tốn RAM/IO khi usage tăng | Thấp ban đầu | Không |

Phương án chọn ưu tiên KISS ở frontend và thực hiện aggregate trong database để
không biến Gateway process thành nơi xử lý toàn bộ lịch sử sự kiện.

## 7. Edge case và truy vết

| Edge case | Điều kiện | Hành vi mong đợi | EARS |
|---|---|---|---|
| Key thiếu/sai/hết hạn | API trả 401 | Xóa phiên, hiện login | ADM-01, ADM-03 |
| Client Admin sửa project khác | Thay `project_id` trên URL | 403, không lộ dữ liệu | ADM-05 |
| Không có usage | Khoảng thời gian rỗng | KPI 0, series rỗng | ADM-10 |
| Token null | Upstream không trả usage | Tổng dùng `COALESCE(0)` | ADM-09 |
| Key hết hạn nhưng status active | `expires_at` đã qua | UI hiển thị `expired` hiệu dụng | ADM-07 |
| Revoke hai lần | Key đã revoked | Lần sau trả 404 theo contract hiện tại | ADM-07 |
| Project version cũ | Hai admin lưu đồng thời | 409 và tải lại bản mới | ADM-15 |
| Filter không hợp lệ | hours/limit ngoài biên | Error contract trả 400 | ADM-04, ADM-09 |
| Dependency down | DB/Redis/upstream lỗi | Status degraded, phần khác vẫn render khi có thể | ADM-12 |
| Response chứa chuỗi độc hại | Tên project/key do người dùng nhập | Render bằng `textContent`, không thực thi HTML | ADM-06, ADM-07 |

## 8. Ngoại lệ và phục hồi

| Nguồn | Ngoại lệ | Xử lý | Ảnh hưởng người dùng |
|---|---|---|---|
| Authentication | Credential không hợp lệ | Error contract 401, frontend logout | Nhập lại key |
| Authorization | Sai project scope | 403 tại backend | Toast không đủ quyền |
| PostgreSQL | Query thất bại | Handler 500, request ID, không lộ chi tiết | Retry thủ công |
| Redis/upstream status | Dependency không sẵn sàng | Trả trạng thái `unavailable` trong status | Badge degraded |
| Project update | Optimistic conflict | 409 | Tải lại project rồi sửa lại |
| Browser storage | `sessionStorage` bị chặn | Giữ key trong memory cho phiên trang | Reload phải đăng nhập lại |
| Network/UI | Fetch lỗi hoặc JSON lỗi | Toast và empty/error state cục bộ | Cho phép retry |

Không tự retry thao tác ghi để tránh tạo project/key trùng. GET có thể được người
dùng retry qua nút Refresh.

## 9. Đồng thời và tính nhất quán

| Tài nguyên | Rủi ro | Biện pháp |
|---|---|---|
| Project policy | Lost update | Giữ optimistic `version`. |
| API key revoke | Hai admin revoke | Update có điều kiện `status=active`; thao tác sau nhận 404. |
| Dashboard trong lúc có request mới | KPI lệch nhẹ giữa query | Chấp nhận eventual snapshot cho dashboard vận hành. |
| Key `last_used_at` | Nhiều request cập nhật | Last-write-wins, không ảnh hưởng xác thực. |
| UI fetch chuyển trang nhanh | Response cũ ghi đè màn hình mới | Mỗi page kiểm tra route hiện tại trước khi render. |

Create project/key không thêm idempotency key ở giai đoạn này. Frontend khóa nút
submit khi request đang chạy; backend constraint tên project và prefix key bảo vệ
các trường hợp trùng cơ bản.

## 10. Kế hoạch triển khai và kiểm chứng

### Pha 1 — Acceptance tests

1. Bổ sung fake repository cho key list, dashboard, usage summary và status.
2. Viết integration tests cho platform scope, client scope, filter và không lộ secret.
3. Mở rộng UI contract tests cho navigation, session storage và từng màn hình.

Kiểm chứng: `python3 -m pytest` ban đầu phải thất bại ở contract mới.

### Pha 2 — Backend

1. Thêm serializer metadata cho API key.
2. Thêm repository query có project scope và aggregate usage theo giờ.
3. Thêm management routes và validation query.
4. Giữ response envelope `{ "data": ... }` và error contract hiện tại.

Kiểm chứng: `python3 -m pytest tests/test_management.py tests/test_repository_unit.py`.

### Pha 3 — Frontend

1. Tạo application shell, login gate, sidebar và hash router.
2. Tạo API/state/component modules.
3. Tạo sáu page modules và SVG chart không dependency.
4. Thêm responsive drawer, modal, toast, loading/empty/error states và dark mode.
5. Thêm CSP/cache headers cho Admin assets.

Kiểm chứng: UI contract tests và thử tải toàn bộ static assets qua ASGI client.

### Pha 4 — Tài liệu và hồi quy

1. Cập nhật README với URL, quyền và luồng quản trị mới.
2. Chạy Ruff và toàn bộ Pytest.
3. Kiểm tra không xuất hiện `digest`, pepper hoặc admin key trong response mới.

Kiểm chứng:

```bash
python3 -m ruff check app tests
python3 -m pytest
```

## 11. Tiêu chí hoàn thành

- Tất cả ADM-01 đến ADM-15 có test hoặc UI contract tương ứng.
- Platform Admin và Client Admin nhìn thấy đúng phạm vi dữ liệu.
- Plaintext key chỉ xuất hiện trong response tạo key.
- Sáu màn hình hoạt động mà không cần build frontend.
- Toàn bộ test cũ và mới đều pass; Ruff không có lỗi.
