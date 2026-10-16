"""回复推荐的工作空间读取：递归收集小文本文件拼接为参考资料。"""
from __future__ import annotations

from pathlib import Path

TEXT_EXTENSIONS = {
    '.txt', '.md', '.json', '.csv', '.py', '.js', '.ts', '.vue', '.html', '.xml',
    '.log', '.yaml', '.yml', '.toml', '.ini', '.cfg',
}
MAX_FILE_BYTES = 100 * 1024
MAX_TOTAL_BYTES = 500 * 1024
MAX_FILES = 100


def _decode_text(raw: bytes) -> str | None:
    for encoding in ('utf-8', 'gbk'):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return None


def read_workspace(directory: str) -> dict:
    """递归读取目录下的小文本文件；单个坏文件不影响整体。

    返回 {files: [{path, size}], digest, truncated}；目录无效或无可用文件
    时返回空结果（truncated=False），由调用方决定是否提示。
    """
    result = {'files': [], 'digest': '', 'truncated': False}
    raw = str(directory or '').strip()
    if not raw:
        return result
    root = Path(raw).expanduser()
    if not root.is_dir():
        return result
    try:
        candidates = sorted(
            p for p in root.rglob('*')
            if p.is_file() and p.suffix.lower() in TEXT_EXTENSIONS
        )
    except OSError:
        return result

    parts: list[str] = []
    total = 0
    for path in candidates:
        if len(result['files']) >= MAX_FILES:
            result['truncated'] = True
            break
        try:
            size = path.stat().st_size
        except OSError:
            continue
        if size > MAX_FILE_BYTES:
            # 超大文件直接跳过，不读入内存。
            result['truncated'] = True
            continue
        try:
            content = _decode_text(path.read_bytes())
        except OSError:
            continue
        if content is None:
            continue
        if total + size > MAX_TOTAL_BYTES:
            result['truncated'] = True
            break
        rel = path.relative_to(root).as_posix()
        result['files'].append({'path': rel, 'size': size})
        parts.append(f'----- {rel} -----\n{content}')
        total += size
    result['digest'] = '\n\n'.join(parts)
    return result
