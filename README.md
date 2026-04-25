# line-skill

把 LINE 對話記錄蒸餾成 AI 版朋友，在 Claude Code 用 `/朋友名` 直接對話。

**無需 API key，無需 pip install。**

```
LINE .txt  →  python3 tools/...  →  /line-skill  →  /朋友名
```

---

## 安裝（1 行指令）

```bash
git clone https://github.com/eric831017/line-skill ~/.claude/skills/line-skill
```

> 需要已安裝 [Claude Code](https://claude.ai/code)（免費帳號即可）。

---

## 使用（4 步）

### 第一步：匯出 LINE 對話

LINE App → 進入與朋友的對話 → 右上角「⋮」→ 其他 → 傳送對話記錄 → **以文字形式傳送** → 存成 `.txt`

把 `.txt` 丟進 `~/.claude/skills/line-skill/` 目錄。

### 第二步：解析對話

```bash
cd ~/.claude/skills/line-skill
python3 tools/line_txt_parser.py "[LINE]朋友名字.txt" --me 你的名字 --friend 朋友名字
```

> LINE 匯出的檔名預設為 `[LINE]朋友名字.txt`，方括號在 bash 中是特殊字元，**務必加引號**。

> `--me` 和 `--friend` 必須與 LINE 裡顯示的名稱**完全一致**（包含空格與大小寫），否則會解析出 0 則訊息。

### 第三步：蒸餾 persona

在同一個目錄開啟 Claude Code：

```bash
claude
```

然後輸入：

```
/line-skill
```

Claude 會問你對這位朋友的印象（可直接 Enter 跳過），接著自動分析對話並生成 persona 與 Skill 檔。整個過程約 2–3 分鐘。

### 第四步：開始對話

```
/朋友名字
```

例如朋友叫「小明」就輸入 `/小明`。

---

## 功能

| 用法 | 效果 |
|------|------|
| `/朋友名` | 與 AI 版朋友對話 |
| `[compare] 你說的話` | 同時看朋友和你會怎麼回應，對比說話風格 |
| 「他不會這樣說，應該是…」 | 即時糾正並更新 persona |

---

## 隱私

對話檔只存在本機，不上傳到任何地方。`friends/` 目錄建議加入 `.gitignore`。
