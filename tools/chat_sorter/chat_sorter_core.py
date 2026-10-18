"""文件传输助手聊天记录按人分类——核心逻辑。

职责：
1. 解析微信导出的 chat_txt 会话文件（如“文件传输助手.txt”）中的消息行。
2. 扫描素材根目录（含根目录自身与递归子目录，跳过隐藏/技术目录），
   从目录名提取关键词。
3. 按关键词匹配为每条消息推荐归属目录（只做推荐，不写盘）。
4. 用户在界面确认后，按目录分组、按时间排序、整行去重后追加写入目标 txt。

消息行格式（由 ContextBuddy 结构化导出生成）：
    [2026-07-22 20:16:11] 余井(wxid_jzemtwvdyvml21): 消息内容
消息内容中的真实换行在导出时已展平为字面量 ``\\n``，因此一条消息只占一行。
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

# 消息行：[时间] 显示名(用户名): 内容
# 用户名限定为微信 ID 字符集，避免把内容里的“(xx): ”误当作发送者。
MESSAGE_LINE_RE = re.compile(
    r"^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]\s+(.+?)\(([A-Za-z0-9_\-@.]{2,64})\):\s?(.*)$"
)

# 目录名先按这些标点切分
_NAME_SPLIT_RE = re.compile(r"[、，,；;·\s/]+")

# 没有区分度的通用词，单独成段时丢弃（如“喜乐的学习”只保留“喜乐”）
_GENERIC_WORDS = {
    "专辑", "产品", "病情", "资料", "相关", "记录", "事情", "规划", "学习",
    "考试", "历史", "创作", "书本", "视频", "图片", "课程", "工具", "服务",
    "咨询", "简历", "成长", "日记", "分析", "推荐", "效果", "直播",
}

# 代词类词，不作为关键词（避免大量误命中）
_PRONOUN_WORDS = {"我自己", "我们", "自己", "大家", "你们", "他们", "她们", "它们"}

# 泛化拉丁词（英文停用词/技术目录名），段与拉丁片段命中即丢弃
_GENERIC_LATIN_WORDS = {
    "ai", "app", "apps", "api", "sdk", "mvp", "ppt", "ok", "top", "new", "old",
    "and", "the", "how", "what", "when", "where", "why", "who", "for", "you",
    "your", "with", "from", "this", "that", "these", "those", "not", "are",
    "was", "were", "been", "our", "out", "use", "used", "using", "can", "has",
    "have", "had", "will", "would", "one", "two", "get", "got", "see", "its",
    "his", "her", "into", "more", "most", "than", "then", "them", "they",
    "there", "their", "some", "such", "only", "also", "just", "like", "over",
    "after", "before", "while", "about", "because", "very", "much", "many",
    "each", "other", "which", "all", "any", "may", "might", "must", "should",
    "could", "does", "did", "done", "via", "per", "off", "own", "same", "keep",
    "now", "let", "lets",
    "output", "temp", "tmp", "cache", "dist", "build", "src", "docs", "doc",
    "test", "tests", "assets", "images", "image", "video", "videos", "audio",
    "backup", "bak", "draft", "final", "copy", "file", "files", "folder",
    "project", "projects", "data", "info", "log", "logs", "ref", "refs",
    "note", "notes", "readme", "config", "lib", "libs", "bin", "utils",
    "tools", "demo", "sample", "examples", "master", "main",
}

# 技术性目录名（导出数据自身/公众号/群聊 ID），整棵子树跳过
_ID_NAME_RE = re.compile(r"^(wxid_|gh_)[A-Za-z0-9_-]+$|@chatroom$", re.IGNORECASE)

# 目录名命中即整棵子树不作为候选
_EXCLUDED_DIR_NAMES = {
    ".workbuddy", "structured_data", "chat_txt", "chat",
    "__pycache__", "node_modules", ".git", ".venv",
}

# 消息内容含这些标记时视为系统/附件消息，不做自动分类（仍可手动指定目录）
_NOISE_MARKERS = ("<?xml", "@cdn_", "eyj", "<sysmsg", "<emoji", "<msgsource>")


@dataclass
class ChatMessage:
    time_str: str
    sender_display: str
    sender_username: str
    content: str
    line: str  # 原始消息行，写入目标文件时原样保留


@dataclass
class CandidateDir:
    path: Path
    rel_display: str  # 相对根目录的显示路径；根目录自身为 "."
    depth: int
    keywords: list[str] = field(default_factory=list)


@dataclass
class ClassifyResult:
    message: ChatMessage
    candidate: CandidateDir | None = None
    matched_keywords: list[str] = field(default_factory=list)
    score: int = 0
    reason: str = ""  # 未分类原因（未匹配 / 系统附件消息）


@dataclass
class WriteReport:
    dir_path: Path
    file_path: Path
    written: int
    skipped_existing: int
    error: str = ""


def parse_chat_txt(file_path: str | os.PathLike) -> list[ChatMessage]:
    """解析会话 txt，返回全部消息（头部元信息行自动忽略）。"""
    file_path = Path(file_path)
    text = file_path.read_text(encoding="utf-8", errors="replace")
    messages: list[ChatMessage] = []
    for raw in text.splitlines():
        line = raw.rstrip("\r")
        match = MESSAGE_LINE_RE.match(line)
        if not match:
            continue
        messages.append(
            ChatMessage(
                time_str=match.group(1),
                sender_display=match.group(2),
                sender_username=match.group(3),
                content=match.group(4),
                line=line,
            )
        )
    return messages


def is_noise_content(content: str) -> bool:
    """系统/附件消息（表情、文件传输记录、链接 XML 等）不做自动分类。"""
    if not content.strip():
        return True
    low = content.lower()
    return any(marker in low for marker in _NOISE_MARKERS)


def extract_keywords(name: str) -> list[str]:
    """从目录名提取分类关键词。

    规则：按标点与“的”切分；丢弃通用词、代词、纯数字与单字（如“我”）；
    另外提取段内长度>=3 且以字母开头的拉丁串（如“KET考试”->“KET”）。
    """
    name = str(name or "").strip()
    if not name or _ID_NAME_RE.match(name):
        return []
    keywords: list[str] = []
    for part in _NAME_SPLIT_RE.split(name):
        for seg in part.split("的"):
            seg = seg.strip("·._-—（）()【】[]:：!！?？")
            if not seg or seg in _GENERIC_WORDS or seg in _PRONOUN_WORDS:
                continue
            if seg.isdigit() or len(seg) < 2:
                continue
            if seg.lower() not in _GENERIC_LATIN_WORDS:
                keywords.append(seg)
            for latin in re.finditer(r"[A-Za-z][A-Za-z0-9]{2,}", seg):
                token = latin.group(0)
                if token.lower() not in _GENERIC_LATIN_WORDS:
                    keywords.append(token)
    seen: set[str] = set()
    out: list[str] = []
    for kw in keywords:
        key = kw.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(kw)
    return out


def scan_candidate_dirs(root: str | os.PathLike) -> list[CandidateDir]:
    """扫描素材根目录：根目录自身 + 递归全部子目录（跳过隐藏/技术/ID 目录）。"""
    root = Path(root)
    if not root.is_dir():
        raise FileNotFoundError(f"素材根目录不存在或不是目录：{root}")

    def make(path: Path) -> CandidateDir:
        rel = path.relative_to(root)
        return CandidateDir(
            path=path,
            rel_display="." if not rel.parts else rel.as_posix(),
            depth=len(rel.parts),
            keywords=extract_keywords(path.name),
        )

    out = [make(root)]
    for dirpath, dirnames, _filenames in os.walk(root):
        kept = []
        for name in sorted(dirnames):
            if name.startswith(".") or name in _EXCLUDED_DIR_NAMES:
                continue
            if _ID_NAME_RE.match(name):
                continue
            kept.append(name)
        dirnames[:] = kept
        for name in kept:
            out.append(make(Path(dirpath) / name))
    out.sort(key=lambda c: (c.depth, c.rel_display))
    return out


def classify_message(message: ChatMessage, candidates: list[CandidateDir]) -> ClassifyResult:
    """为单条消息推荐目录：关键词命中计分，取分数最高者。

    平分时更浅的目录优先（如“喜乐”优先于“喜乐的KET考试”），
    内容更具体的目录靠更高分数胜出。
    """
    if is_noise_content(message.content):
        return ClassifyResult(message=message, reason="系统/附件消息")

    low = message.content.lower()
    best_key: tuple | None = None
    best_cand: CandidateDir | None = None
    best_matched: list[str] = []
    best_score = 0
    for cand in candidates:
        matched = [kw for kw in cand.keywords if kw.lower() in low]
        if not matched:
            continue
        score = sum(len(kw) for kw in matched)
        key = (-score, cand.depth, cand.rel_display)
        if best_key is None or key < best_key:
            best_key = key
            best_cand = cand
            best_matched = matched
            best_score = score
    if best_cand is None:
        return ClassifyResult(message=message, reason="未匹配到任何目录关键词")
    return ClassifyResult(
        message=message,
        candidate=best_cand,
        matched_keywords=best_matched,
        score=best_score,
    )


def classify_messages(
    messages: list[ChatMessage], candidates: list[CandidateDir]
) -> list[ClassifyResult]:
    return [classify_message(msg, candidates) for msg in messages]


def sanitize_output_name(name: object) -> str:
    """写入文件名清洗：默认“微信聊天记录.txt”，去除非法字符。"""
    text = str(name or "").strip()
    if not text:
        text = "微信聊天记录.txt"
    if not text.lower().endswith(".txt"):
        text += ".txt"
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", text).strip(" .")
    return cleaned or "微信聊天记录.txt"


def apply_writes(
    assignments: list[tuple[CandidateDir, ChatMessage]],
    *,
    output_filename: str,
    source_label: str,
) -> list[WriteReport]:
    """把已确认的消息按目录分组写入目标 txt。

    - 同一目录的消息按时间排序后追加；
    - 目标文件中已存在的整行自动跳过（重复运行不会重复写入）；
    - 新建文件时先写入一行来源说明。
    """
    groups: dict[Path, list[ChatMessage]] = {}
    for cand, msg in assignments:
        groups.setdefault(cand.path, []).append(msg)

    out_name = sanitize_output_name(output_filename)
    reports: list[WriteReport] = []
    for dir_path, msgs in sorted(groups.items(), key=lambda kv: str(kv[0])):
        file_path = dir_path / out_name
        written = 0
        skipped = 0
        error = ""
        try:
            existing: set[str] = set()
            file_exists = file_path.exists()
            if file_exists:
                with file_path.open("r", encoding="utf-8", errors="replace") as handle:
                    for ln in handle:
                        existing.add(ln.rstrip("\r\n"))
            new_lines: list[str] = []
            if not file_exists:
                new_lines.append(f"# 微信聊天记录（来源：{source_label}，按时间排序，重复自动跳过）")
            for msg in sorted(msgs, key=lambda m: m.time_str):
                if msg.line in existing:
                    skipped += 1
                    continue
                existing.add(msg.line)
                new_lines.append(msg.line)
                written += 1
            if new_lines:
                with file_path.open("a", encoding="utf-8", newline="\n") as handle:
                    for ln in new_lines:
                        handle.write(ln + "\n")
        except OSError as exc:
            error = str(exc)
        reports.append(WriteReport(dir_path, file_path, written, skipped, error))
    return reports


def display_rel(cand: CandidateDir) -> str:
    """目录在界面上的显示名：根目录自身显示为“(根目录)”。"""
    return "(根目录)" if cand.rel_display == "." else cand.rel_display


def summarize(results: list[ClassifyResult]) -> str:
    """生成一行统计摘要。"""
    total = len(results)
    classified = sum(1 for r in results if r.candidate is not None)
    noise = sum(1 for r in results if is_noise_content(r.message.content))
    return (
        f"共 {total} 条消息：已推荐 {classified} 条，"
        f"未分类 {total - classified} 条（其中系统/附件 {noise} 条）"
    )


if __name__ == "__main__":
    # 命令行只读自检：python chat_sorter_core.py <会话txt> <素材根目录>
    import sys

    if len(sys.argv) < 3:
        print("用法: python chat_sorter_core.py <会话txt> <素材根目录>")
        sys.exit(1)
    msgs = parse_chat_txt(sys.argv[1])
    cands = scan_candidate_dirs(sys.argv[2])
    results = classify_messages(msgs, cands)
    print(summarize(results))
    counter: dict[str, int] = {}
    for res in results:
        if res.candidate is not None:
            key = display_rel(res.candidate)
            counter[key] = counter.get(key, 0) + 1
    for key, count in sorted(counter.items(), key=lambda kv: -kv[1]):
        print(f"  {count:5d}  {key}")
