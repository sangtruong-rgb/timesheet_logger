# Sửa lỗi nhóm commit và benchmark lại — 09/10/2026

Đã xử lý ba điểm còn sót: mã nhóm thay đổi khi có commit trong phút đầu, thiếu
token của lượt đã chạy nhưng mô tả bị từ chối, và merge PR sát biên phút bị đưa
ra ngoài khoảng. Benchmark mới cho **19.009 → 6.182 token**, giảm **67,48%**.

## Hành vi sau sửa

- Mã nhóm được tạo từ khoảng phân bổ và các closing commit trước khi tách dòng.
  Commit được gắn thêm vào một dòng không làm đổi mã nhóm; ngữ cảnh commit/PR
  được tổng hợp cho một mô tả chung. Thời gian và bằng chứng từng dòng giữ riêng.
- `usage-attempt.json` ghi token độc lập với việc chấp nhận mô tả. Có usage hoàn
  chỉnh thì ghi nhận cả lượt bị từ chối; thiếu usage thì giữ trạng thái unknown.
  Receipt thành công và receipt attempt cùng định danh lượt chạy nên không cộng
  trùng. Ledger benchmark giữ cả các lần lỗi/retry và vẫn được ghi khi benchmark
  chưa hoàn thành. Receipt attempt không được dùng để chấp nhận timesheet.
- Merge PR cùng phút với closing commit được liên kết khi khớp SHA và repository,
  gắn vào đoạn làm việc cuối của nhóm. Giữ timestamp gốc và metadata liên kết,
  không thêm phút hoặc vượt giờ kết thúc đã xác nhận. Thiếu SHA hoặc không khớp
  vẫn dùng quy tắc timestamp/review hiện tại.
- Snapshot mới dùng schema v4; v1/v2/v3 vẫn dựng theo hành vi trước đó. Payload
  AI vẫn là v3. Snapshot và bằng chứng benchmark cũ không bị viết lại.

## Điều kiện đo

- Dùng lại nguồn lịch sử **07/10/2026** của benchmark trước, đóng băng thành
  snapshot v4 áp dụng ngưỡng gộp dưới **20 phút**. Giờ bắt đầu **09:00 là giả định
  của benchmark**, không phải xác nhận thời gian làm thực tế.
- Cùng snapshot cho legacy và compact: **6 dòng, 300 phút đề xuất, 40 commit
  được gán, 9 hoạt động cần review**. Compact có 5 job, trong đó một job cho hai
  đoạn cùng nhóm trước/sau nghỉ trưa. Legacy mô tả riêng 6 dòng.
- Cùng `gpt-6.1-sol`, reasoning `low`, CLI **0.161.0**. Mỗi phương án có một lượt
  thành công; không có lượt thất bại, retry hoặc usage chưa xác định trong phép đo.
- Chỉ đo các lượt tổng hợp AI. Input gồm ngữ cảnh CLI gửi cho model; không tính
  cuộc chat phát triển hoặc các lệnh shell/Python không gọi AI.

| Chỉ số | Legacy | Compact |
| --- | ---: | ---: |
| Input token do provider báo | 18.619 | 5.664 |
| Cached input, đã nằm trong input | 0 | 0 |
| Output token | 390 | 518 |
| Tổng input + output | **19.009** | **6.182** |
| Prompt UTF-8, byte | 11.574 | 4.258 |
| Job mô tả | 6 | 5 |
| Thời gian chạy, giây | 15,964 | 20,349 |

Input giảm **69,58%**; tổng giảm **67,48%**, tương đương **12.827 token**.
Tổng token thực sự đã dùng cho cả hai lượt benchmark là **25.191**; compact riêng
là 6.182. Output compact cao hơn trong lượt này; thời gian chạy không giảm.
Một cặp đo chưa xác định mức tiết kiệm trung bình.

Mốc 6.966 token trong [báo cáo trước](token-optimization-benchmark.md) dùng 23 dòng
theo chính sách phân bổ cũ. Không dùng chênh lệch giữa hai số compact để kết luận
hiệu quả riêng của ba bản sửa lỗi.

## Kiểm chứng

- **565 kiểm thử qua**, gồm nhóm có commit trong phút đầu qua nghỉ trưa/Calendar,
  snapshot v1-v4, liên kết merge theo SHA/repository và biên giờ xác nhận, usage
  của mô tả bị từ chối, retry/dedup và unknown không bị quy thành zero.
- Ca usage giả lập: legacy 165 token, compact bị từ chối 165, retry compact 165.
  So sánh thành công vẫn là 165/165; ledger ghi đủ **495**, CSV có đúng ba lượt.
- Nguồn preview ngày **08/10** được đối chiếu SHA PR #66 qua GitHub readonly:
  giữ **4 dòng, 337 phút**, merge event gắn vào dòng cuối, review **1 → 0**.
  Đây là replay của nguồn cũ có bổ sung bằng chứng SHA; không thu thập lại cả ngày
  hoặc gọi AI cho preview này.
- Đã đối chiếu 5 mô tả compact với commit/PR/Calendar; hai đoạn cùng nhóm nhận
  cùng mô tả. Attendance và thời lượng đề xuất vẫn được bảo toàn.
- Assemble/rerun bảo toàn byte và ghi nhận đúng 6.182 token. Resume benchmark
  bảo toàn report/ledger/CSV, được kiểm tra bằng cách chặn mọi lời gọi AI mới.
- Không publish/log work; dữ liệu audit và authentication không đưa vào Git.

## Bằng chứng cục bộ

- [Snapshot](../data/audit/followup-benchmark-20261009-002528/activity.json)
- [Benchmark](../data/audit/followup-benchmark-20261009-002528/benchmark/benchmark.json)
- [Ledger từng lượt](../data/audit/followup-benchmark-20261009-002528/benchmark/attempts.json)
- [Usage CSV](../data/audit/followup-benchmark-20261009-002528/benchmark/token-usage.csv)
- [Timesheet kiểm tra](../data/audit/followup-benchmark-20261009-002528/timesheets/2026-10-07.md)
- [Đối chiếu PR #66](../data/audit/followup-benchmark-20261009-002528/pr66-replay/verification.json)

Các file audit bị Git ignore; liên kết bằng chứng chỉ khả dụng tại workspace này.
