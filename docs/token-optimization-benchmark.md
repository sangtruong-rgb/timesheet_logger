# Kết quả tối ưu token — 08/10/2026

Đã triển khai payload và runner gọn cho cách chia `commit_intervals`.
Trong phép đo này, tổng token AI giảm **64,61%**, từ **19.681 xuống 6.966**.

Phép đo mới sau các bản sửa ngày 09/10 nằm trong
[báo cáo benchmark lại](followup-benchmark-20261009.md): legacy **19.009**,
compact **6.182** token trên cùng snapshot theo chính sách hiện tại.

Số đo dưới đây được thực hiện **trước khi bổ sung quy tắc gộp commit dưới 30 phút**.
Snapshot benchmark v1 vẫn giữ nguyên 23 dòng. Kiểm tra lại cùng dữ liệu bằng Python
sau cập nhật cho 5 dòng và 4 job mô tả, giữ nguyên tổng 300 phút phân bổ và 40 commit
được gán; chưa gọi AI lại nên không quy đổi thành mức giảm token mới.

Payload hiện tại là v3: các đoạn thuộc cùng nhóm commit dùng một mô tả chung dù
PR theo từng đoạn khác nhau. Quy tắc này và ngưỡng gộp dưới 20 phút được cập nhật
sau phép đo; số token trong báo cáo vẫn thuộc snapshot và payload cũ.

## Điều kiện so sánh

- Cùng dữ liệu lịch sử ngày 07/10/2026 và cùng một snapshot đóng băng.
- Áp dụng cách chia mới với giờ bắt đầu **09:00 giả lập cho benchmark**;
  đây không phải xác nhận giờ làm thực tế. Không thu thập lại nguồn.
- 23 dòng timesheet, 23 job mô tả cho cả hai phương án. Dữ liệu này không có
  hai dòng trùng toàn bộ ngữ cảnh để gộp job; cơ chế đó được kiểm thử riêng.
- Cùng model `gpt-6.1-sol`, reasoning `low`, CLI **0.161.0**.
- Mỗi phương án có một lượt AI thành công; không tính phiên chat phát triển,
  các lệnh Python/shell hay thao tác CLI không gọi AI. Input của lượt AI bao gồm
  ngữ cảnh mà CLI gửi cho model.

## Trước và sau

| Chỉ số | Trước: payload và ngữ cảnh cũ | Sau: compact |
| --- | ---: | ---: |
| Input token do provider báo | 18.536 | 5.953 |
| Cached input, đã nằm trong input | 0 | 0 |
| Output token | 1.145 | 1.013 |
| Tổng input + output | **19.681** | **6.966** |
| Prompt UTF-8, byte | 15.898 | 4.892 |
| Số dòng timesheet / job mô tả | 23 / 23 | 23 / 23 |
| Thời gian chạy, giây | 38,258 | 36,462 |

Input giảm **67,88%**; tổng giảm **64,61%**, tương đương **12.715 token**.
Số đo khoảng 17k trước đây dùng cách chia cũ và CLI 0.160.1, nên không dùng
làm mốc đối chứng trực tiếp cho phép đo mới này. Số byte không phải số token.
Một cặp đo chưa xác định mức tiết kiệm trung bình cho mọi ngày/model.

## Các thay đổi

1. Lưu mỗi văn bản một lần trong danh mục chung, giữ vai trò commit/PR/Calendar
   bằng tham chiếu. Trong dữ liệu đo có 60 lượt xuất hiện nội dung commit/PR;
   danh mục mới chứa 49 văn bản, kể cả ngữ cảnh Calendar.
2. Chỉ gộp job khi nội dung commit, tiêu đề PR, Calendar và ngữ cảnh tham dự
   trùng nhau. Python ánh xạ kết quả về đúng mọi `block_id`, giữ giờ và hậu tố PR
   riêng của từng dòng. Không gộp các khoảng thời gian.
3. Dùng hướng dẫn ngắn cho mô tả timesheet, chạy từ thư mục cô lập và giảm công
   cụ/ngữ cảnh phát triển của lượt AI. Các tùy chọn chỉ áp dụng cho lượt chạy này.
4. Payload v2 giới hạn **request thực sự gửi model** ở 12.000 byte; dữ liệu audit
   đầy đủ vẫn nằm trong snapshot/export. Request của phép đo là 4.892 byte;
   envelope audit là 22.925 byte. Giữ khả năng đọc snapshot và usage manifest v1.
5. Manifest v2 giữ request/prompt/instructions/schema/raw response và các digest;
   bộ ghi token kiểm tra lại request từ snapshot và ánh xạ job về đầu ra chuẩn.

Cache mô tả lâu dài chưa triển khai. Tiết kiệm ở đây không đến từ cache provider.

## Xác minh

- **533 test** qua, gồm kiểm tra gộp các mảnh qua giờ trưa, khác ngữ cảnh thì
  không gộp, ánh xạ đầy đủ, giới hạn UTF-8, snapshot cũ, bằng chứng bị sửa và
  benchmark resume không gọi lại AI hoặc ghi token trùng.
- Đối chiếu cấu trúc trước/sau: thời gian, bằng chứng nguồn và metadata giữ nguyên.
- Đã đọc đối chiếu cả 23 cặp mô tả với nội dung commit/PR: các thay đổi chính được
  giữ lại. Cảnh báo Calendar chưa xác nhận tham dự vẫn do Python bảo toàn.
- Assemble bằng đầu ra compact và manifest v2 thành công: 23 dòng, 6.966 token
  được quy thuộc. 9 hoạt động chưa gán vẫn được giữ riêng để rà soát.
- Rerun assemble bảo toàn byte của JSON/Markdown/manifest/CSV; không gọi lại AI.
- Không thực hiện publish/log work.

Lần thử compact đầu bị CLI từ chối vì `tools.view_image` không phải config hợp lệ
trong phiên bản cài đặt. Đã chuyển sang feature `view_image` được CLI hỗ trợ;
giữ log lần lỗi và dùng lượt retry thành công. Feature bỏ qua host skill discovery
được CLI 0.161.0 đánh dấu đang phát triển; thông báo đó được giữ trong event log.

## Bằng chứng cục bộ

Các file bên dưới nằm trong thư mục audit bị Git ignore, không được publish:

- [Snapshot](../data/audit/token-optimization-20261008-170818/activity.json)
- [Kết quả benchmark](../data/audit/token-optimization-20261008-170818/benchmark/benchmark.json)
- [Event trước](../data/audit/token-optimization-20261008-170818/benchmark/legacy/events.jsonl)
- [Event sau](../data/audit/token-optimization-20261008-170818/benchmark/compact-retry-1/events.jsonl)
- [Timesheet test](../data/audit/token-optimization-20261008-170818/timesheets/2026-10-07.md)

Đo lại bằng `scripts/benchmark_codex_summary.py` với một snapshot hoàn chỉnh và
model chỉ định rõ; xem [cách chạy benchmark](codex-usage.md#beforeafter-benchmark).
