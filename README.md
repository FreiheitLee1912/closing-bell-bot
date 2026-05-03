# The Closing Bell · Telegram 推送機器人

每天美股收盤後，自動把「金融晨報」風格的 dashboard 圖片推到你的 Telegram。

```
[GitHub Actions cron] → [yfinance 抓資料] → [Claude API 寫評論]
                              ↓
                   [HTML 模板 → PNG 圖片]
                              ↓
                       [Telegram Bot] → 你的手機
```

完全免費（GitHub Actions 公開倉庫每月 2000 分鐘額度，這個任務每天約 30 秒就跑完）。

---

## 一次性架設（約 15 分鐘）

### Step 1 · 建立 Telegram Bot

1. 在 Telegram 找 [`@BotFather`](https://t.me/BotFather)，傳 `/newbot`
2. 取個顯示名稱（例：`My Closing Bell`）
3. 取個 username，必須以 `_bot` 結尾（例：`my_closing_bell_bot`）
4. BotFather 會給你一串 token，類似：
   ```
   1234567890:ABCdefGHIjklMNOpqrsTUVwxyz
   ```
   👉 **保存好，這就是 `TELEGRAM_BOT_TOKEN`**

### Step 2 · 取得你的 Chat ID

1. 在 Telegram 主動傳訊息給剛建立的 bot（隨便傳「hi」就好，不傳的話 getUpdates 會空白）
2. 瀏覽器訪問：
   ```
   https://api.telegram.org/bot<你的TOKEN>/getUpdates
   ```
3. 在 JSON 回覆中找 `"chat":{"id": 12345678, ...}`，那組數字就是你的 chat_id

   👉 **`TELEGRAM_CHAT_ID`**

### Step 3 · 取得 Anthropic API Key（可選但推薦）

到 [console.anthropic.com](https://console.anthropic.com) 申請。Sonnet 模型每次呼叫成本約 $0.001 USD，一個月 ~$0.03。

不設這個 key 也能跑——程式會用 fallback 規則寫一句模板評論。

### Step 4 · 部署到 GitHub

```bash
# 把這個資料夾推到你自己的 GitHub repo
cd closing-bell-bot
git init
git add .
git commit -m "init closing bell bot"
gh repo create closing-bell-bot --public --source=. --push
# 或手動 git remote add origin ... && git push
```

到 repo `Settings → Secrets and variables → Actions → New repository secret`，新增三個：

| Name | Value |
|---|---|
| `TELEGRAM_BOT_TOKEN` | 從 Step 1 |
| `TELEGRAM_CHAT_ID`   | 從 Step 2 |
| `ANTHROPIC_API_KEY`  | 從 Step 3（可選） |

### Step 5 · 馬上測一次

到 repo 的 `Actions` 分頁 → 左側選 `Daily Market Dispatch` → 右上角 `Run workflow` 手動跑一次。

幾秒後你的 Telegram 應該就會收到圖片了 🎉

---

## 自動排程

預設在 **UTC 22:30 週一到週五** 跑（= 美東收盤 90 分鐘後 = 日本時間早上 07:30）。

要改時間，編輯 `.github/workflows/daily.yml` 的 cron：

```yaml
- cron: '30 22 * * 1-5'    # ←改這行，cron 一律用 UTC
```

| 你想要的日本時間 | 對應 UTC | cron 寫法 |
|---|---|---|
| 06:00 JST | 21:00 UTC 前一天 | `0 21 * * 1-5` |
| 07:30 JST（預設）| 22:30 UTC 前一天 | `30 22 * * 1-5` |
| 09:00 JST | 00:00 UTC 當天 | `0 0 * * 2-6` |

> ⚠ GitHub Actions 的 cron 不保證**準時**，可能延遲 5–15 分鐘。如果需要精準時間，用 [Cloud Scheduler](https://cloud.google.com/scheduler) 觸發。

---

## 本機測試

```bash
pip install -r requirements.txt
playwright install chromium

export TELEGRAM_BOT_TOKEN=...
export TELEGRAM_CHAT_ID=...
export ANTHROPIC_API_KEY=...   # 可選

python dispatch.py
```

---

## 自訂

### 加追蹤標的

編輯 `dispatch.py` 最上面的 `TICKERS`：

```python
TICKERS = {
    "sp500":  "^GSPC",
    "nasdaq": "^IXIC",
    "dow":    "^DJI",
    "vix":    "^VIX",
    "usdjpy": "JPY=X",
    "tech":   "XLK",
    "energy": "XLE",
    # 加你想要的：
    "btc":    "BTC-USD",
    "gold":   "GC=F",
    "tlt":    "TLT",       # 20Y 美債 ETF
    "sox":    "SOXX",      # 半導體 ETF
}
```

新加的標的記得到 `build_payload()` 裡安排顯示位置（多增加 sector card、或開新 section）。

### 評論文字想要中文

改 `dispatch.py` 裡 `write_closing_note()` 的 prompt，把那段 English 換成：

```python
prompt = f"""你是一份每日財經晨報「The Closing Bell」的編輯。

今日美股收盤（{date_str}）：
...

請用 2 句話寫收盤評論，總共不超過 60 個字。
語氣冷靜觀察，像是經驗老道的編輯，不要太亢奮。
提一下今日領漲的指數、加上一個跨市場的訊號（日圓動向 / 板塊分歧 / 波動率區間之類的）。
不要 emoji，不要標題，不要引號，只要散文。"""
```

### 換模板設計

`template.html` 是純靜態 HTML + Chart.js，可以改色、改字型、改排版。
資料是透過 `<script id="market-data">` 注入的，渲染邏輯都在底下的 script 區塊。

---

## 結構

```
closing-bell-bot/
├── dispatch.py              主腳本
├── template.html            Dashboard 模板
├── requirements.txt
├── .github/
│   └── workflows/
│       └── daily.yml        排程
└── README.md
```

---

## 排錯

| 症狀 | 解方 |
|---|---|
| `Not enough data: only 1 rows` | yfinance 偶爾抓不到，重試或檢查 ticker。可改用 `period="14d"` |
| Telegram `400: chat not found` | chat_id 錯了，或忘記先傳 hi 給 bot |
| `Unauthorized` 401 | Anthropic API key 過期或錯誤 |
| Playwright timeout | 改 `page.wait_for_timeout(800)` 數值，或加大到 2000 |
| Action 跑了沒推送 | 看 Actions log，多半是 secret 沒設或值有空白 |
| 圖片字型怪 | Google Fonts 在 Action 容器裡可能延遲，腳本已等到 `__chartReady`，通常 OK |

---

## 進階方向

- 接 **LINE Messaging API** 取代 Telegram（在日本更直覺）
- 加 **歷史趨勢圖**（用 yfinance period="3mo" 拉 90 天數據畫迷你圖）
- 加 **新聞摘要**：用 NewsAPI / Reddit r/wallstreetbets RSS，給 Claude 摘要當日重點
- 改成 **盤中即時**：每 30 分鐘跑一次，只在大幅變動時才推送（節流）
- 把 PNG 改成 **PDF 存到 Google Drive**，建立每日歷史檔案
