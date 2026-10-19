"""chat_sorter_core 的单元测试：解析 / 扫描 / LLM 分类 / 写入去重。"""

from __future__ import annotations

import sys
import threading
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


def _msg(time: str, content: str, sender: str = "余井", username: str = "wxid_demo") -> core.ChatMessage:
    return core.ChatMessage(
        time_str=time,
        sender_display=sender,
        sender_username=username,
        content=content,
        line=f"[{time}] {sender}({username}): {content}",
    )


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


def test_scan_candidate_dirs(tmp_path: Path) -> None:
    candidates = _make_candidates(tmp_path)
    rels = {c.rel_display for c in candidates}
    assert "." in rels  # 根目录自身也是候选
    assert {"喜乐", "喜乐的KET考试", "老妈的病情", "老爸", "周围邻居/陈轩"} <= rels
    # 隐藏目录、微信 ID 目录整棵子树排除
    assert not any(r.startswith(".workbuddy") for r in rels)
    assert not any("wxid_" in r for r in rels)


def test_scan_candidate_dirs_max_depth(tmp_path: Path) -> None:
    _make_candidates(tmp_path)
    one = core.scan_candidate_dirs(tmp_path, max_depth=1)
    rels = {c.rel_display for c in one}
    # 深度 1：根目录自身 + 顶层目录，二层“周围邻居/陈轩”被剪枝
    assert rels == {".", "喜乐", "喜乐的KET考试", "老妈的病情", "老爸", "周围邻居"}
    two = core.scan_candidate_dirs(tmp_path, max_depth=2)
    assert "周围邻居/陈轩" in {c.rel_display for c in two}


def test_parse_llm_results() -> None:
    # 纯 JSON
    parsed = core.parse_llm_results('{"results":[{"index":1,"dir":"喜乐","reason":"提到孩子"}]}')
    assert parsed == {1: ("喜乐", "提到孩子")}
    # 带 Markdown 代码块包装
    wrapped = '```json\n{"results":[{"index":2,"dir":"","reason":"无关"}]}\n```'
    assert core.parse_llm_results(wrapped) == {2: ("", "无关")}
    # 非法编号被跳过
    bad = '{"results":[{"index":"x","dir":"喜乐","reason":""},{"index":3,"dir":"老爸","reason":"r"}]}'
    assert core.parse_llm_results(bad) == {3: ("老爸", "r")}


def test_build_llm_messages(tmp_path: Path) -> None:
    candidates = _make_candidates(tmp_path)
    messages = [_msg("2026-07-22 20:16:11", "内容A"), _msg("2026-07-22 20:20:00", "内容B")]
    llm_messages = core.build_llm_messages(candidates, messages)
    assert llm_messages[0]["role"] == "system"
    user_text = llm_messages[1]["content"]
    assert "候选目录列表" in user_text
    assert "(根目录)" in user_text  # 根目录用显示名
    assert "- 喜乐" in user_text
    assert "1. [2026-07-22 20:16:11] 内容A" in user_text
    assert "2. [2026-07-22 20:20:00] 内容B" in user_text


def test_classify_with_llm(tmp_path: Path) -> None:
    candidates = _make_candidates(tmp_path)
    messages = [
        _msg("2026-07-23 19:24:07", "喜乐今天KET考试考得不错"),
        _msg("2026-07-23 13:47:19", "2.txt 6 0 0 0 8283 @cdn_305f02 abc 0 0"),  # 系统附件
        _msg("2026-07-22 20:16:11", "随便聊聊天气"),
    ]
    progress = []

    def fake_call(llm_messages: list[dict]) -> str:
        user_text = llm_messages[1]["content"]
        assert "候选目录列表" in user_text and "喜乐" in user_text
        return (
            '{"results":['
            '{"index":1,"dir":"喜乐","reason":"提到孩子喜乐"},'
            '{"index":2,"dir":"不存在的目录","reason":"x"},'
            '{"index":9,"dir":"老爸","reason":"y"}]}'
        )

    results = core.classify_with_llm(
        messages,
        candidates,
        call_llm=fake_call,
        batch_size=20,
        concurrency=2,
        progress_cb=lambda d, t, f: progress.append((d, t, f)),
    )
    # 第一条：LLM 指向“喜乐”
    assert results[0].candidate is not None and results[0].candidate.rel_display == "喜乐"
    assert results[0].reason == "提到孩子喜乐"
    # 第二条：系统附件消息不发送 LLM，直接标未分类
    assert results[1].candidate is None
    assert results[1].reason.startswith("系统/附件")
    # 第三条：LLM 给了无效目录 -> 不采纳
    assert results[2].candidate is None
    assert "无效目录" in results[2].reason
    assert progress and progress[-1] == (1, 1, 0)  # 1 批完成、0 失败


def test_classify_with_llm_cancel(tmp_path: Path) -> None:
    candidates = _make_candidates(tmp_path)
    messages = [_msg("2026-07-22 20:16:11", "随便聊聊天气"), _msg("2026-07-22 20:20:00", "再聊一句")]
    cancel_event = threading.Event()
    cancel_event.set()  # 分析前已取消：不应发起任何 LLM 调用
    calls = []

    def fake_call(llm_messages: list[dict]) -> str:
        calls.append(llm_messages)
        return '{"results":[]}'

    results = core.classify_with_llm(
        messages, candidates, call_llm=fake_call, cancel_event=cancel_event
    )
    assert not calls
    assert all(r.candidate is None and r.reason == "已取消" for r in results)
    # 摘要包含取消计数
    assert "已取消 2 条" in core.summarize(results)


def test_classify_with_llm_retry_then_fail(tmp_path: Path) -> None:
    candidates = _make_candidates(tmp_path)
    messages = [_msg("2026-07-22 20:16:11", "随便聊聊天气")]
    progress = []

    def bad_call(_llm_messages: list[dict]) -> str:
        raise OSError("network down")

    results = core.classify_with_llm(
        messages,
        candidates,
        call_llm=bad_call,
        concurrency=1,
        progress_cb=lambda d, t, f: progress.append((d, t, f)),
    )
    assert results[0].candidate is None
    assert results[0].reason.startswith("LLM调用失败")
    assert progress and progress[-1] == (1, 1, 1)  # 重试耗尽的批计入失败数
    assert "LLM 调用失败 1 条" in core.summarize(results)


def test_apply_writes_dedupe_and_append(tmp_path: Path) -> None:
    person = tmp_path / "喜乐"
    person.mkdir()
    target = person / "微信聊天记录.txt"
    line_old = "[2026-01-01 09:00:00] 余井(wxid_demo): 已存在的内容"
    line_new = "[2026-07-23 19:24:07] 余井(wxid_demo): 喜乐今天KET考试考得不错"
    line_early = "[2026-06-01 08:00:00] 余井(wxid_demo): 更早的一条"
    target.write_text(line_old + "\n", encoding="utf-8")

    cand = core.CandidateDir(path=person, rel_display="喜乐", depth=1)

    def msg(time: str, content: str) -> core.ChatMessage:
        return _msg(time, content)

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
    cand = core.CandidateDir(path=person, rel_display="老爸", depth=1)
    msg = _msg("2026-07-26 10:00:00", "报告出来了", sender="老爸", username="wxid_lao")
    reports = core.apply_writes([(cand, msg)], output_filename="记录.txt", source_label="文件传输助手.txt")
    assert reports[0].written == 1
    lines = (person / "记录.txt").read_text(encoding="utf-8").splitlines()
    assert lines[0].startswith("# 微信聊天记录（来源：文件传输助手.txt")
    assert lines[1] == msg.line
