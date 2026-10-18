"""chat_sorter_core 的单元测试：解析 / 关键词 / 扫描 / 分类 / 写入去重。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import chat_sorter_core as core


SAMPLE_TXT = """会话: 文件传输助手 (filehelper)
账号: wxid_demo
导出时间: 2026-10-18 16:16:19

[2026-07-22 20:16:11] 余井(wxid_demo): 时代不一样了，两种方式各有缘由。
[2026-07-23 13:47:19] 余井(wxid_demo): 2.txt 6 0 0 0 8283 @cdn_305f02 abc 0 0
[2026-07-23 19:24:07] 余井(wxid_demo): 喜乐今天KET考试考得不错
[2026-07-25 09:10:33] 余井(wxid_demo): 步骤(1): 先做喜乐的复习计划
[2026-07-26 10:00:00] 老爸(wxid_lao): 老妈的检查报告出来了
"""


def _make_candidates(root: Path) -> list[core.CandidateDir]:
    (root / "喜乐").mkdir(parents=True)
    (root / "喜乐的KET考试").mkdir(parents=True)
    (root / "老妈的病情").mkdir(parents=True)
    (root / "老爸").mkdir(parents=True)
    (root / "周围邻居" / "陈轩").mkdir(parents=True)
    (root / ".workbuddy" / "memory").mkdir(parents=True)
    (root / "wxid_demo123").mkdir(parents=True)
    return core.scan_candidate_dirs(root)


def test_parse_chat_txt(tmp_path: Path) -> None:
    src = tmp_path / "文件传输助手.txt"
    src.write_text(SAMPLE_TXT, encoding="utf-8")
    messages = core.parse_chat_txt(src)
    assert len(messages) == 5
    first = messages[0]
    assert first.time_str == "2026-07-22 20:16:11"
    assert first.sender_display == "余井"
    assert first.sender_username == "wxid_demo"
    assert first.content == "时代不一样了，两种方式各有缘由。"
    assert first.line.startswith("[2026-07-22 20:16:11] 余井(wxid_demo): ")
    # 内容里带“(1): ”不会被误当作发送者
    assert messages[3].content == "步骤(1): 先做喜乐的复习计划"
    assert messages[4].sender_display == "老爸"


def test_extract_keywords() -> None:
    assert core.extract_keywords("老妈的病情") == ["老妈"]
    assert core.extract_keywords("我") == []
    assert set(core.extract_keywords("喜乐的KET考试")) == {"喜乐", "KET考试", "KET"}
    assert core.extract_keywords("产品、GEO") == ["GEO"]
    assert core.extract_keywords("我自己的简历") == []
    assert core.extract_keywords("wxid_jzemtwvdyvml21") == []
    assert core.extract_keywords("周围邻居/陈轩") == ["周围邻居", "陈轩"]


def test_scan_candidate_dirs(tmp_path: Path) -> None:
    candidates = _make_candidates(tmp_path)
    rels = {c.rel_display for c in candidates}
    assert "." in rels  # 根目录自身也是候选
    assert {"喜乐", "喜乐的KET考试", "老妈的病情", "老爸", "周围邻居/陈轩"} <= rels
    # 隐藏目录、微信 ID 目录整棵子树排除
    assert not any(r.startswith(".workbuddy") for r in rels)
    assert not any("wxid_" in r for r in rels)


def test_classify_message(tmp_path: Path) -> None:
    candidates = _make_candidates(tmp_path)

    def classify(content: str) -> core.ClassifyResult:
        msg = core.ChatMessage(
            time_str="2026-07-22 20:16:11",
            sender_display="余井",
            sender_username="wxid_demo",
            content=content,
            line=f"[2026-07-22 20:16:11] 余井(wxid_demo): {content}",
        )
        return core.classify_message(msg, candidates)

    # 命中更具体的目录（关键词更长，分数更高）
    res = classify("喜乐今天KET考试考得不错")
    assert res.candidate is not None and res.candidate.rel_display == "喜乐的KET考试"
    # 平分时更浅的目录优先
    res = classify("喜乐真棒")
    assert res.candidate is not None and res.candidate.rel_display == "喜乐"
    # “老妈”命中“老妈的病情”，“老爸”虽是发送者名但内容里没有则不参与
    res = classify("老妈的检查报告出来了")
    assert res.candidate is not None and res.candidate.rel_display == "老妈的病情"
    # 系统/附件消息不分类
    res = classify("2.txt 6 0 0 0 8283 @cdn_305f02 abc 0 0")
    assert res.candidate is None and res.reason == "系统/附件消息"
    # 无命中
    res = classify("今天天气不错")
    assert res.candidate is None


def test_apply_writes_dedupe_and_append(tmp_path: Path) -> None:
    person = tmp_path / "喜乐"
    person.mkdir()
    target = person / "微信聊天记录.txt"
    line_old = "[2026-01-01 09:00:00] 余井(wxid_demo): 已存在的内容"
    line_new = "[2026-07-23 19:24:07] 余井(wxid_demo): 喜乐今天KET考试考得不错"
    line_early = "[2026-06-01 08:00:00] 余井(wxid_demo): 更早的一条"
    target.write_text(line_old + "\n", encoding="utf-8")

    cand = core.CandidateDir(path=person, rel_display="喜乐", depth=1, keywords=["喜乐"])

    def msg(time: str, content: str) -> core.ChatMessage:
        return core.ChatMessage(
            time_str=time,
            sender_display="余井",
            sender_username="wxid_demo",
            content=content,
            line=f"[{time}] 余井(wxid_demo): {content}",
        )

    assignments = [
        (cand, msg("2026-07-23 19:24:07", "喜乐今天KET考试考得不错")),
        (cand, msg("2026-06-01 08:00:00", "更早的一条")),
        (cand, msg("2026-01-01 09:00:00", "已存在的内容")),
    ]
    reports = core.apply_writes(assignments, output_filename="微信聊天记录.txt", source_label="文件传输助手.txt")
    assert len(reports) == 1
    rep = reports[0]
    assert rep.file_path == target
    assert rep.written == 2  # 已存在的一条被去重跳过
    assert rep.skipped_existing == 1
    assert rep.error == ""

    lines = target.read_text(encoding="utf-8").splitlines()
    assert lines[0] == line_old
    # 新写入的按时间排序追加
    assert lines[1] == line_early
    assert lines[2] == line_new


def test_apply_writes_new_file_header(tmp_path: Path) -> None:
    person = tmp_path / "老爸"
    person.mkdir()
    cand = core.CandidateDir(path=person, rel_display="老爸", depth=1, keywords=["老爸"])
    msg = core.ChatMessage(
        time_str="2026-07-26 10:00:00",
        sender_display="老爸",
        sender_username="wxid_lao",
        content="报告出来了",
        line="[2026-07-26 10:00:00] 老爸(wxid_lao): 报告出来了",
    )
    reports = core.apply_writes([(cand, msg)], output_filename="记录.txt", source_label="文件传输助手.txt")
    assert reports[0].written == 1
    lines = (person / "记录.txt").read_text(encoding="utf-8").splitlines()
    assert lines[0].startswith("# 微信聊天记录（来源：文件传输助手.txt")
    assert lines[1] == msg.line
