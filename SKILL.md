# line-skill.skill

觸發詞：/distill-line
描述：把 LINE 對話記錄蒸餾成兩個人的 persona.md，並產生可直接呼叫的朋友 Skill

---

你是 line-skill 的主入口。
使用者執行 `/distill-line` 時，由你引導整個蒸餾流程。
你不會呼叫任何外部 API，所有分析與生成都在 Claude Code 內完成。

## 前置條件

- 專案目錄結構：
  - `tools/line_txt_parser.py`
  - `prompts/persona_analyzer.md`
  - `prompts/persona_builder.md`
  - `prompts/skill_builder.md`
  - `friends/<slug>/`（解析後產生）
- 使用者必須先把 LINE `.txt` 檔放入專案目錄

---

## 執行流程

### Step 1：確認解析結果

1. 列出 `friends/` 下所有子目錄
2. 對每個子目錄，檢查是否有 `distill_prompt.txt`
3. 若有多個尚未蒸餾的目錄，列出讓使用者選擇要蒸餾哪一個
4. 若都沒有 `distill_prompt.txt`，停下來提示：

   ```
   尚未解析任何 LINE 對話。請先執行：
     python3 tools/line_txt_parser.py <檔案路徑> --me <我的名稱> --friend <朋友名稱>
   完成後再執行 /distill-line
   ```

5. 確認選擇的目錄後，讀取 `meta.json`，向使用者複述：
   - 朋友名稱
   - 訊息總數、雙方各自則數
   - 時間跨度
   - 採樣數

### Step 2：詢問補充資訊

問使用者兩個問題（用 `AskUserQuestion` 或一般 prompt 都可，可跳過）：

1. 「你對這個朋友的主觀印象？」（會寫進 persona 的「使用者主觀印象」段落）
2. 「有沒有特別想強調的風格特色？」（會在分析時納入）

### Step 3：執行蒸餾

依序執行：

1. **讀取** `friends/<slug>/distill_prompt.txt`，取得朋友與我各自的訊息樣本
2. **分析朋友的風格**：
   - 套用 `prompts/persona_analyzer.md` 的 9 項分析框架
   - 對「朋友」的訊息樣本做完整分析
3. **生成 persona_friend.md**：
   - 套用 `prompts/persona_builder.md` 的格式
   - 變數帶入：`{name}`=朋友名、`{N}`=朋友訊息採樣數、`{date_range}`=meta 中的時間跨度、`{timestamp}`=當下時間、`{user_impression}`=Step 2 蒐集到的印象
   - 寫檔到 `friends/<slug>/persona_friend.md`
4. **對「我」的訊息重複步驟 2-3**：
   - 寫檔到 `friends/<slug>/persona_me.md`
   - `user_impression` 段填「（自我描述，由對話樣本歸納）」
5. **生成 SKILL.md**：
   - 套用 `prompts/skill_builder.md` 的格式
   - 變數帶入：`{slug}`、`{name}`=朋友名、`{my_name}`=我的名稱、`{persona_friend_full}`=整份 persona_friend.md
   - 寫檔到 `friends/<slug>/SKILL.md`
6. **更新 meta.json**：
   - 加入 `status: "distilled"`、`distilled_at`、`trigger: "/<slug>"`

### Step 4：完成提示

輸出：

```
✅ 蒸餾完成！

生成了以下檔案：
- friends/<slug>/persona_friend.md
- friends/<slug>/persona_me.md
- friends/<slug>/SKILL.md

使用方式：
  與 AI 版朋友對話：/<slug>
  對比兩人風格：輸入任何訊息前加上 [compare]

想調整 persona？直接說「他不會這樣說，應該是...」
```

---

## 共通守則

- 全程繁體中文
- 不要呼叫網路、不要 import 任何 SDK
- 蒸餾過程若樣本太少（< 30 則）要警告使用者，但仍可繼續
- 寫檔前先確認目錄存在，不存在就建立
- 任何步驟失敗要明確指出哪一步、可執行的下一步是什麼
