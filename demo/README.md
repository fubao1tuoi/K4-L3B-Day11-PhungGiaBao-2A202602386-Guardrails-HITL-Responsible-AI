# VinBank Blue Agent — Web Demo

Demo local dùng trực tiếp pipeline của bài lab:

```text
Rate limit → Input guardrails → Blue LLM → Output guardrails → Secret egress check
```

## Chạy demo

Từ thư mục gốc repo, kích hoạt virtual environment rồi chạy:

```powershell
python demo/server.py
```

Mở trình duyệt tại <http://127.0.0.1:8000>.

Đổi cổng nếu cần:

```powershell
python demo/server.py --port 8080
```

Demo dùng `OPENROUTER_API_KEY` trong `.env` ở phía server. API key không được gửi tới trình duyệt. Không nhập dữ liệu ngân hàng thật vào giao diện.

Phần chấm bài trong `src/` vẫn giữ nguyên model ID theo đề. Riêng demo dùng endpoint hiện hành `liquid/lfm-2.5-2.6b:free`. Có thể đổi riêng cho demo bằng biến `DEMO_OPENROUTER_MODEL` nếu OpenRouter cập nhật catalog sau này.
