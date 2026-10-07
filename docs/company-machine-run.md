# Chạy và audit trên máy công ty — macOS/Linux

Chạy từ `main` sau khi PR #60–#63 đã merge. Runtime của logger là Python 3.11+
trên macOS/Linux với POSIX locks. Các bộ test được xác minh bằng Python 3.14.6;
phiên bản Python thấp nhất và môi trường máy công ty cần kiểm tra tại chỗ.
Không cần chuyển thư mục audit hoặc token cá nhân từ máy phát triển.

## 1. Lấy code và tạo môi trường

Cần Git, Python 3.11+, GitHub CLI (`gh`) và quyền đọc các repository muốn theo dõi.
Trong terminal macOS/Linux:

```bash
git clone https://github.com/sangtruong-rgb/timesheet_logger.git
cd timesheet_logger
git switch main
git pull --ff-only
python3 --version
python3 -c 'import sys; assert sys.version_info >= (3, 11), "Cần Python 3.11+"'
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements-calendar.txt
python3 -m unittest discover -s tests
```

Nếu đã clone, dùng thư mục hiện có và bỏ lệnh clone. Kiểm tra local edits trước khi
switch/pull; không reset hoặc ghi đè chúng. Mỗi terminal mới cần activate lại venv.
Test suite gồm fixtures/regression và không đòi OAuth thật; pass suite không chứng
minh các nguồn hoặc Claude đang hoạt động trên máy công ty.

## 2. Cấu hình danh tính và GitHub

```bash
gh auth login --hostname github.com --web
gh auth status
test -f config/user-config.json || cp config/example-config.json config/user-config.json
```

Sửa `config/user-config.json` bằng editor:

- `author.names` và `author.emails`: các alias tác giả commit thực sự thuộc bạn.
- `github.users`: tất cả tài khoản GitHub thực sự thuộc bạn.
- `repositories`: repo muốn lấy; dùng `owner/repo` hoặc absolute path tới local
  clone. Remote Git lấy default-branch history; local Git lấy all refs. Local clone
  cần có remote GitHub để lấy PR và phải được fetch đủ refs muốn audit.
- `timezone`: `Asia/Ho_Chi_Minh` nếu bạn dùng múi giờ Việt Nam.
- `calendar.calendar_ids`: mặc định `primary`; thêm calendar ID nếu cần.
- `token_tracking.claude_dir`: mặc định `~/.claude` hoặc thư mục transcript thật
  của Claude trên máy công ty. Không đoán đường dẫn khi sử dụng cấu hình riêng.

Các đường dẫn trong profile tính từ thư mục `config/`; template đã dùng
`../token.json`, `../credentials.json`. Repo không tự nạp `.env`. GitHub CLI phải
đọc được các repo đã chọn; `gh auth status` một mình không xác nhận quyền từng repo.
Xem [GitHub CLI authentication](https://cli.github.com/manual/gh_auth_login).

## 3. Cấp quyền Google Calendar trên máy công ty

Trong Google Cloud, bật Calendar API và có OAuth client loại Desktop. Đặt client
file tại `credentials.json` ở gốc repo (hoặc cấu hình đường dẫn tương ứng), rồi:

```bash
python3 scripts/setup_calendar_oauth.py --config config/user-config.json
```

Đăng nhập đúng Google account chứa lịch công việc và chấp nhận quyền
`calendar.readonly`. Script lưu `token.json`; nếu token đã có, script giữ nguyên.
Không in nội dung, commit hoặc đưa credentials/token vào báo cáo audit.
Hướng dẫn tạo Desktop client: [Google Calendar quickstart](https://developers.google.com/workspace/calendar/api/quickstart/python).

## 4. Kiểm tra pipeline thật trước khi dùng Claude

Trong terminal đã activate venv, tạo audit directory mới:

```bash
export TS_ROOT="$(pwd -P)"
export TS_DATE="$(python3 -c 'import datetime; from zoneinfo import ZoneInfo; print(datetime.datetime.now(ZoneInfo("Asia/Ho_Chi_Minh")).date().isoformat())')"
export TS_RUN="$TS_ROOT/data/audit/company-$(date -u +%Y%m%dT%H%M%SZ)-$$"
mkdir -p "$TS_RUN"
python3 scripts/run_pipeline.py --phase prepare --date "$TS_DATE" \
  --config "$TS_ROOT/config/user-config.json" \
  --snapshot "$TS_RUN/activity.json" --export-ai-input "$TS_RUN/ai-input.json" \
  --output-dir "$TS_RUN/timesheets"
```

Chỉ tiếp tục nếu prepare exit 0/PREPARED và từng nguồn là `success/live`.
Nếu exit 2, đọc diagnostic/draft, sửa nguồn lỗi rồi dùng audit directory mới;
không bật fixtures hoặc lấy export cũ để bỏ qua lỗi. Số commit/PR/event bằng 0
có thể hợp lệ; `success` khác với `unavailable/error`.

Assemble kiểm tra fallback bằng đúng snapshot vừa chuẩn bị:

```bash
python3 scripts/run_pipeline.py --phase assemble \
  --snapshot "$TS_RUN/activity.json" --output-dir "$TS_RUN/timesheets"
```

Kết quả mong đợi: COMPLETE/exit 0; `timesheets/DATE.json`, `.md`,
`.collection.json` và các sidecar. Token usage là unknown vì bước này không gọi AI.
Đọc source statuses trong snapshot/collection manifest, review unassigned evidence
và attendance. COMPLETE xác nhận thu thập đủ nguồn, không xác nhận đã tham dự họp.
Chạy lại assemble phải giữ nguyên bytes của output. Audit chưa ghi vào timesheet cũ.

## 5. Chạy skill bằng Claude Code thật

Nếu đã có Claude Code thì kiểm tra `claude --version`. Nếu chưa có, cài theo
[Claude Code setup](https://code.claude.com/docs/en/setup); lệnh macOS/Linux:

```bash
curl -fsSL https://claude.ai/install.sh | bash
```

Mở terminal mới nếu cần PATH, activate lại venv, vào repo và chạy `claude` một lần
để đăng nhập theo cấu hình tài khoản công ty. Sau đó thoát để bắt đầu phiên audit
riêng. Installer của repo tạo symlink project và giữ nguyên destination khác:

```bash
python3 scripts/install_skill.py --scope project
export TS_CLAUDE_RUN="$TS_RUN/claude"
mkdir -p "$TS_CLAUDE_RUN"
export TS_SESSION="$(python3 -c 'import uuid; print(uuid.uuid4())')"
export TS_START="$(python3 -c 'import datetime; print(datetime.datetime.now(datetime.timezone.utc).isoformat())')"
claude --session-id "$TS_SESSION"
```

Nếu đổi terminal, khai báo lại TS_ROOT/TS_DATE/TS_RUN như bước 4. Phiên UUID riêng
giúp xác định đúng transcript; không dùng phiên này cho công việc khác hoặc tiếp tục
phiên cũ. Không tắt persistence/skills. Các lệnh trên không tự xác nhận skill đã load.

Trong Claude, gọi `/personal-timesheet` và yêu cầu:

```text
Chạy personal-timesheet cho ngày hôm nay theo timezone Asia/Ho_Chi_Minh.
Dùng profile config/user-config.json trong bundle và Python của .venv.
Dùng đường dẫn trong biến môi trường TS_CLAUDE_RUN làm run directory:
activity.json, ai-input.json, ai-output.json và timesheets/.
Chạy prepare mới với dữ liệu thật; AI chỉ mô tả block_id trong payload nhỏ;
assemble đúng snapshot đó. Không dùng fixtures hoặc ghi timesheet production.
Chưa tự ghi usage vì phản hồi cuối chưa xong. Báo run_id, từng nguồn,
collection status, đường dẫn output và các mục cần review.
```

Xác nhận command/skill được nhận diện, script chạy bằng venv, không báo thiếu Google
SDK và AI output dùng đúng block IDs. Nếu không có block cần AI, bỏ ai-output theo
SKILL.md; lần đó chưa chứng minh nhánh AI summarization. Nếu skill chưa được nhận
diện, kiểm tra `.claude/skills/personal-timesheet/SKILL.md` và khởi động lại Claude.
Project symlink/invocation: [Claude skills](https://code.claude.com/docs/en/skills).
UUID flag: [CLI reference](https://code.claude.com/docs/en/cli-reference).

## 6. Thu usage sau khi phản hồi cuối hoàn tất

Thoát phiên Claude, trở về cùng terminal và ghi end timestamp. Dùng snapshot mà
phiên Claude vừa tạo, không dùng run_id của phép thử fallback ở bước 4:

```bash
export TS_END="$(python3 -c 'import datetime; print(datetime.datetime.now(datetime.timezone.utc).isoformat())')"
python3 - <<'PY'
import json, os
from pathlib import Path
run = Path(os.environ['TS_CLAUDE_RUN'])
snapshot = json.loads((run / 'activity.json').read_text())
manifest = {
    'run_id': snapshot['run_id'],
    'target_date': snapshot['normalized']['date'],
    'session_id': os.environ['TS_SESSION'],
    'started_at': os.environ['TS_START'],
    'ended_at': os.environ['TS_END'],
}
(run / 'usage-run.json').write_text(json.dumps(manifest, indent=2))
PY
python3 scripts/collect_token_usage.py \
  --config "$TS_ROOT/config/user-config.json" \
  --run-manifest "$TS_CLAUDE_RUN/usage-run.json" \
  --csv-path "$TS_CLAUDE_RUN/token-usage.csv"
```

Exact session lookup phải tìm đúng một transcript. Window này chỉ có thể coi là
full run khi phiên audit không có việc khác; nếu có, cần selected message IDs và
phải báo selected scope. Input/output/cache-read/cache-creation trong snapshot
usage phải đầy đủ. Nếu thiếu/sai schema, collector exit 2, giữ CSV và chưa xác lập
tổng; không tự điền zero hoặc ghi manual totals để làm acceptance pass.
Xem [R04 policy](r04-usage-schema-validation.md).

## 7. Bằng chứng để chốt F25/V01

Giữ commit `git rev-parse HEAD`, Python/Claude versions, target date/timezone,
run_id, session ID, start/end, source statuses, snapshot, AI input/output,
collection manifest, timesheet và CSV cô lập. Đối chiếu từng message trong đúng
transcript với CSV, kiểm tra dedup/latest-complete, tổng gồm cache và rerun không
nhân đôi run record. Không đưa credentials/token hoặc transcript toàn bộ công việc
khác lên issue. Báo đường dẫn và diagnostic của phiên audit đã chọn để kiểm tra.

F25 chưa hoàn tất chỉ nhờ suite pass. V01 còn cần dữ liệu thật phù hợp cho all-day,
cross-midnight, meeting overlap và submitted PR review; fixtures không thay bằng
bằng chứng live. Logger chỉ đọc Calendar, không tạo/sửa meetings để test. D02
(giờ làm cấu hình, BREAK/OT) vẫn deferred theo quyết định trước.
