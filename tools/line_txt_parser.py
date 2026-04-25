#!/usr/bin/env python3
"""
LINE .txt 對話記錄解析器

功能：
- 解析 LINE 匯出的 .txt 對話記錄
- 過濾系統訊息（圖片、貼圖、檔案、通話、收回訊息等）
- 分早期 / 中期 / 近期 三等分各取樣 100 則訊息
- 產出 raw_messages.json 與給 Claude Code 用的 distill_prompt.txt

使用方式：
  python3 tools/line_txt_parser.py <檔案路徑> --me <我的名稱> --friend <朋友名稱>
  python3 tools/line_txt_parser.py --test
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime


FILTER_PATTERNS = [
    r"^\[圖片\]$",
    r"^\[貼圖\]$",
    r"^\[檔案\]$",
    r"^\[影片\]$",
    r"^\[語音訊息\]$",
    r"^\[相簿\]$",
    r"^\[聯絡資訊\]$",
    r"^\[位置資訊\]$",
    r"^☎ 通話時間",
    r"^☎ 未接來電",
    r"^☎ 取消通話",
    r"^通話時間",
    r"^未接來電",
    r"^已收回訊息$",
    r"^已收回訊息。$",
    r"^.+ 已收回訊息$",
]

DATE_LINE_PATTERNS = [
    re.compile(r"^(\d{4})/(\d{1,2})/(\d{1,2})（?[一二三四五六日週天]+）?\s*$"),
    re.compile(r"^(\d{4})/(\d{1,2})/(\d{1,2})\([一二三四五六日週天]+\)\s*$"),
    re.compile(r"^(\d{4})\.(\d{1,2})\.(\d{1,2})\s+[A-Za-z一二三四五六日週天星期]+\s*$"),
    re.compile(r"^(\d{4})/(\d{1,2})/(\d{1,2})\s*$"),
]

TIME_PATTERNS = [
    re.compile(r"^(上午|下午)\s*(\d{1,2}):(\d{2})$"),
    re.compile(r"^(\d{1,2}):(\d{2})\s*(AM|PM|am|pm)$"),
    re.compile(r"^(\d{1,2}):(\d{2})$"),
]


def parse_date_line(line):
    line = line.strip()
    for pat in DATE_LINE_PATTERNS:
        m = pat.match(line)
        if m:
            try:
                y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
                return datetime(y, mo, d).date()
            except ValueError:
                return None
    return None


def parse_time(token):
    token = token.strip()
    for pat in TIME_PATTERNS:
        m = pat.match(token)
        if not m:
            continue
        groups = m.groups()
        if pat is TIME_PATTERNS[0]:
            period, hh, mm = groups[0], int(groups[1]), int(groups[2])
            if period == "下午" and hh < 12:
                hh += 12
            if period == "上午" and hh == 12:
                hh = 0
            return hh, mm
        if pat is TIME_PATTERNS[1]:
            hh, mm, period = int(groups[0]), int(groups[1]), groups[2].upper()
            if period == "PM" and hh < 12:
                hh += 12
            if period == "AM" and hh == 12:
                hh = 0
            return hh, mm
        if pat is TIME_PATTERNS[2]:
            return int(groups[0]), int(groups[1])
    return None


def is_filtered(text):
    if not text or not text.strip():
        return True
    t = text.strip()
    for pat in FILTER_PATTERNS:
        if re.match(pat, t):
            return True
    return False


def parse_line_message(line):
    """嘗試把一行解析成 (time_tuple, sender, text)；失敗回傳 None。"""
    raw = line.rstrip("\n")
    # 優先嘗試 tab 分隔格式（舊版 LINE 匯出）
    tab_parts = raw.split("\t")
    if len(tab_parts) >= 3:
        time_token = tab_parts[0].strip()
        t = parse_time(time_token)
        if t is not None:
            return t, tab_parts[1].strip(), "\t".join(tab_parts[2:])

    # 空白分隔格式：HH:MM 發送者 訊息（新版 LINE 匯出）
    space_parts = raw.split(" ", 2)
    if len(space_parts) >= 3:
        time_token = space_parts[0].strip()
        t = parse_time(time_token)
        if t is not None:
            return t, space_parts[1].strip(), space_parts[2]

    return None


def parse_lines(lines, me_name, friend_name):
    """解析全部行，回傳 messages list 與 date_range (first, last)。"""
    messages = []
    current_date = None
    first_date = None
    last_date = None
    current_msg = None  # 用於合併多行訊息

    def flush():
        nonlocal current_msg
        if current_msg is None:
            return
        text = current_msg["text"]
        if is_filtered(text):
            current_msg = None
            return
        sender_label = current_msg["sender"]
        if sender_label == me_name:
            sender_key = "me"
        elif sender_label == friend_name:
            sender_key = "friend"
        else:
            current_msg = None
            return
        messages.append({
            "date": current_msg["date"].isoformat() if current_msg["date"] else None,
            "time": f"{current_msg['hh']:02d}:{current_msg['mm']:02d}",
            "sender": sender_key,
            "sender_name": sender_label,
            "text": text.strip(),
        })
        current_msg = None

    for raw_line in lines:
        line = raw_line.rstrip("\n").rstrip("\r")
        if not line.strip():
            continue

        d = parse_date_line(line)
        if d is not None:
            flush()
            current_date = d
            if first_date is None:
                first_date = d
            last_date = d
            continue

        parsed = parse_line_message(line)
        if parsed is not None:
            flush()
            (hh, mm), sender, text = parsed
            current_msg = {
                "date": current_date,
                "hh": hh,
                "mm": mm,
                "sender": sender,
                "text": text,
            }
        else:
            if current_msg is not None:
                current_msg["text"] += "\n" + line

    flush()
    return messages, first_date, last_date


def sample_three_thirds(messages, total=300):
    """分早 / 中 / 近三等分，各取 total/3 則。"""
    if len(messages) <= total:
        return list(messages)

    third = len(messages) // 3
    parts = [
        messages[:third],
        messages[third:2 * third],
        messages[2 * third:],
    ]
    per = total // 3
    sampled = []
    for part in parts:
        if len(part) <= per:
            sampled.extend(part)
        else:
            step = len(part) / per
            picks = [part[int(i * step)] for i in range(per)]
            sampled.extend(picks)
    return sampled


def slugify(name):
    s = name.strip().lower()
    s = re.sub(r"\s+", "-", s)
    s = re.sub(r"[^\w一-鿿\-]", "", s)
    if not s:
        s = "friend"
    return s


def build_distill_prompt(slug, friend_name, me_name, friend_msgs_all, me_msgs_all,
                         friend_sample, me_sample):
    lines = []
    lines.append("請根據以下 LINE 對話記錄，分別蒸餾出兩個人的 persona.md。")
    lines.append("")
    lines.append("執行步驟：")
    lines.append(f"1. 先分析「{friend_name}」的說話風格，參考 prompts/persona_analyzer.md")
    lines.append(f"2. 根據分析結果，套用 prompts/persona_builder.md 的格式，"
                 f"生成 friends/{slug}/persona_friend.md")
    lines.append(f"3. 對「{me_name}」重複同樣步驟，生成 friends/{slug}/persona_me.md")
    lines.append(f"4. 生成 friends/{slug}/SKILL.md（格式見 prompts/skill_builder.md）")
    lines.append(f"5. 更新 friends/{slug}/meta.json")
    lines.append("")
    lines.append(f"--- {friend_name} 的訊息（共 {len(friend_msgs_all)} 則，"
                 f"已取樣 {len(friend_sample)} 則）---")
    for m in friend_sample:
        lines.append(m["text"].replace("\n", " "))
    lines.append("")
    lines.append(f"--- {me_name} 的訊息（共 {len(me_msgs_all)} 則，"
                 f"已取樣 {len(me_sample)} 則）---")
    for m in me_sample:
        lines.append(m["text"].replace("\n", " "))
    lines.append("")
    return "\n".join(lines)


def write_outputs(out_dir, slug, friend_name, me_name, messages,
                  first_date, last_date):
    os.makedirs(out_dir, exist_ok=True)

    friend_msgs = [m for m in messages if m["sender"] == "friend"]
    me_msgs = [m for m in messages if m["sender"] == "me"]

    friend_sample = sample_three_thirds(friend_msgs, total=300)
    me_sample = sample_three_thirds(me_msgs, total=300)

    date_range_str = ""
    if first_date and last_date:
        date_range_str = f"{first_date.isoformat()} ~ {last_date.isoformat()}"

    raw = {
        "friend_name": friend_name,
        "my_name": me_name,
        "total_messages": len(messages),
        "friend_message_count": len(friend_msgs),
        "my_message_count": len(me_msgs),
        "date_range": date_range_str,
        "first_date": first_date.isoformat() if first_date else None,
        "last_date": last_date.isoformat() if last_date else None,
        "messages": [
            {"sender": m["sender"], "text": m["text"]} for m in messages
        ],
    }

    raw_path = os.path.join(out_dir, "raw_messages.json")
    with open(raw_path, "w", encoding="utf-8") as f:
        json.dump(raw, f, ensure_ascii=False, indent=2)

    prompt_text = build_distill_prompt(
        slug, friend_name, me_name, friend_msgs, me_msgs,
        friend_sample, me_sample,
    )
    prompt_path = os.path.join(out_dir, "distill_prompt.txt")
    with open(prompt_path, "w", encoding="utf-8") as f:
        f.write(prompt_text)

    meta = {
        "slug": slug,
        "friend_name": friend_name,
        "my_name": me_name,
        "total_messages": len(messages),
        "friend_message_count": len(friend_msgs),
        "my_message_count": len(me_msgs),
        "friend_sample_count": len(friend_sample),
        "my_sample_count": len(me_sample),
        "date_range": date_range_str,
        "parsed_at": datetime.now().isoformat(timespec="seconds"),
        "status": "parsed",
    }
    with open(os.path.join(out_dir, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    return raw_path, prompt_path, friend_msgs, me_msgs, friend_sample, me_sample


def days_between(a, b):
    if not a or not b:
        return 0
    return (b - a).days + 1


def run_parse(input_path, me_name, friend_name):
    if not os.path.isfile(input_path):
        print(f"❌ 找不到檔案：{input_path}", file=sys.stderr)
        print("", file=sys.stderr)
        print("請確認檔案路徑正確，或執行：", file=sys.stderr)
        print(f"  ls -la \"{os.path.dirname(input_path) or '.'}\"", file=sys.stderr)
        sys.exit(1)

    with open(input_path, "r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()

    messages, first_date, last_date = parse_lines(lines, me_name, friend_name)

    if not messages:
        print("❌ 沒有解析到任何訊息。", file=sys.stderr)
        print("", file=sys.stderr)
        print("可能原因：", file=sys.stderr)
        print(f"  1. --me 或 --friend 名稱與檔案中的不一致", file=sys.stderr)
        print(f"     目前指定：--me {me_name!r} --friend {friend_name!r}", file=sys.stderr)
        print("  2. .txt 檔案不是 LINE 匯出格式", file=sys.stderr)
        print("  3. 檔案編碼非 UTF-8", file=sys.stderr)
        sys.exit(1)

    slug = slugify(friend_name)
    out_dir = os.path.join("friends", slug)

    raw_path, prompt_path, friend_msgs, me_msgs, friend_sample, me_sample = \
        write_outputs(out_dir, slug, friend_name, me_name, messages,
                      first_date, last_date)

    total = len(messages)
    f_count = len(friend_msgs)
    m_count = len(me_msgs)
    f_pct = f_count / total * 100 if total else 0
    m_pct = m_count / total * 100 if total else 0
    span_days = days_between(first_date, last_date)

    print("✅ 解析完成")
    print()
    print("統計：")
    print(f"  總訊息：{total} 則")
    print(f"  {friend_name} 訊息：{f_count} 則（{f_pct:.1f}%）")
    print(f"  {me_name} 訊息：{m_count} 則（{m_pct:.1f}%）")
    if first_date and last_date:
        print(f"  時間跨度：{first_date.isoformat()} ~ {last_date.isoformat()}"
              f"（{span_days} 天）")
    print()
    print("輸出：")
    print(f"  {raw_path}")
    print(f"  {prompt_path}")
    print()
    print("下一步：")
    print("  在 Claude Code 中執行：")
    print("  /line-skill")
    print("  或直接把 distill_prompt.txt 的內容貼給 Claude Code")


# ----------------------- 測試模式 -----------------------

TEST_DATA = """[LINE] 與朋友A的對話
儲存日期：2024/03/16

2023/06/01(四)
下午 02:31\t朋友A\t欸你那個事情怎樣了
下午 02:35\t我\t還在等回覆
下午 02:35\t朋友A\t哦
下午 02:36\t朋友A\t那就繼續等啊哈哈
下午 02:36\t朋友A\t[貼圖]
下午 02:40\t我\t嗯

2023/09/15(五)
上午 10:12\t我\t早安
上午 10:13\t朋友A\t早 今天要幹嘛
上午 10:14\t我\t就上班啊
上午 10:14\t朋友A\t無聊
上午 10:14\t朋友A\t晚上要不要吃飯
上午 10:15\t我\t好啊 吃哪
上午 10:16\t朋友A\t隨便
下午 12:30\t我\t[圖片]
下午 12:31\t朋友A\t哇看起來不錯

2023/12/25(一)
上午 11:00\t朋友A\t聖誕快樂🎄
上午 11:02\t我\t聖誕快樂！
上午 11:02\t朋友A\t今天有要出門嗎
上午 11:03\t我\t沒有耶 太冷
上午 11:03\t朋友A\t廢
上午 11:04\t朋友A\t出來啦
上午 11:04\t朋友A\t我請你喝咖啡
上午 11:05\t我\t蛤 真假
上午 11:05\t朋友A\t真的啦
上午 11:30\t朋友A\t已收回訊息
下午 03:00\t朋友A\t☎ 通話時間 12:34

2024/03/15(五)
下午 02:31\t朋友A\t欸你那個事情怎樣了
下午 02:35\t我\t還在等回覆
下午 02:35\t朋友A\t哦
下午 02:36\t朋友A\t那就繼續等啊哈哈
下午 02:40\t我\t嗯啊
下午 02:41\t朋友A\t加油
下午 02:41\t朋友A\t💪
"""


def run_test():
    print("=== --test 模式 ===")
    print()

    test_path = "/tmp/_line_skill_test.txt"
    with open(test_path, "w", encoding="utf-8") as f:
        f.write(TEST_DATA)

    with open(test_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    messages, first_date, last_date = parse_lines(lines, me_name="我",
                                                  friend_name="朋友A")

    assert messages, "解析後 messages 為空"
    assert first_date is not None, "first_date 為 None"
    assert last_date is not None, "last_date 為 None"

    texts = [m["text"] for m in messages]
    for filtered in ("[貼圖]", "[圖片]", "已收回訊息"):
        assert filtered not in texts, f"應被過濾的內容仍出現：{filtered}"
    for m in messages:
        assert not m["text"].startswith("☎"), "通話訊息未被過濾"

    senders = {m["sender"] for m in messages}
    assert senders == {"me", "friend"}, f"sender 不正確：{senders}"

    f_count = sum(1 for m in messages if m["sender"] == "friend")
    m_count = sum(1 for m in messages if m["sender"] == "me")
    assert f_count > 0 and m_count > 0, "雙方訊息數應皆 > 0"

    sampled = sample_three_thirds(list(range(900)), total=300)
    assert len(sampled) == 300, f"取樣總數應為 300，實得 {len(sampled)}"
    assert sampled[0] < 300, "早期樣本應落在前段"
    assert 300 <= sampled[150] < 600, "中期樣本應落在中段"
    assert sampled[-1] >= 600, "近期樣本應落在後段"

    short = sample_three_thirds([1, 2, 3, 4], total=300)
    assert short == [1, 2, 3, 4], "訊息少於 total 時應原樣回傳"

    assert slugify("朋友A") == "朋友a"
    assert slugify("John Doe") == "john-doe"
    assert slugify("  ") == "friend"

    out_dir = "/tmp/_line_skill_test_out"
    if os.path.isdir(out_dir):
        for fname in os.listdir(out_dir):
            os.remove(os.path.join(out_dir, fname))
    raw_path, prompt_path, fm, mm, fs, ms = write_outputs(
        out_dir, "test-slug", "朋友A", "我", messages, first_date, last_date,
    )
    assert os.path.isfile(raw_path), "raw_messages.json 未生成"
    assert os.path.isfile(prompt_path), "distill_prompt.txt 未生成"
    with open(raw_path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    assert raw["friend_name"] == "朋友A"
    assert raw["my_name"] == "我"
    assert raw["total_messages"] == len(messages)

    with open(prompt_path, "r", encoding="utf-8") as f:
        prompt_text = f.read()
    assert "請根據以下 LINE 對話記錄" in prompt_text
    assert "朋友A 的訊息" in prompt_text
    assert "我 的訊息" in prompt_text
    assert "prompts/persona_analyzer.md" in prompt_text
    assert "prompts/persona_builder.md" in prompt_text

    print("✅ 全部測試通過")
    print()
    print(f"解析訊息數：{len(messages)}")
    print(f"  朋友A：{f_count}")
    print(f"  我：{m_count}")
    print(f"時間跨度：{first_date} ~ {last_date}")
    print()
    print("前 5 則解析結果：")
    for m in messages[:5]:
        print(f"  [{m['sender']}] {m['text']}")
    print()
    print(f"範例輸出檔案：")
    print(f"  {raw_path}")
    print(f"  {prompt_path}")


def main():
    parser = argparse.ArgumentParser(
        description="LINE .txt 對話記錄解析器",
    )
    parser.add_argument("input", nargs="?", help="LINE 匯出的 .txt 檔案路徑")
    parser.add_argument("--me", help="我的名稱（與 LINE 中顯示一致）")
    parser.add_argument("--friend", help="朋友的名稱（與 LINE 中顯示一致）")
    parser.add_argument("--test", action="store_true", help="執行內建測試")

    args = parser.parse_args()

    if args.test:
        run_test()
        return

    if not args.input or not args.me or not args.friend:
        parser.print_help()
        print()
        print("範例：")
        print("  python3 tools/line_txt_parser.py 對話記錄.txt --me 我 --friend 朋友A")
        sys.exit(1)

    run_parse(args.input, args.me, args.friend)


if __name__ == "__main__":
    main()
