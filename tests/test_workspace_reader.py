"""工作空间读取器：类型过滤、递归、三重上限、编码回退、坏文件跳过。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from wechat_decrypt_tool.workspace_reader import read_workspace, MAX_FILES


def _write(path: Path, text: str, encoding='utf-8'):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding=encoding)


def test_missing_directory_returns_empty(tmp_path):
    result = read_workspace(str(tmp_path / 'nope'))
    assert result == {'files': [], 'digest': '', 'truncated': False}


def test_filters_extensions_and_recurses(tmp_path):
    _write(tmp_path / 'a.md', '说明')
    _write(tmp_path / 'sub' / 'b.txt', '文本')
    _write(tmp_path / 'sub' / 'c.png', 'binary')
    _write(tmp_path / 'd.exe', 'nope')
    result = read_workspace(str(tmp_path))
    assert [f['path'] for f in result['files']] == ['a.md', 'sub/b.txt']
    assert '说明' in result['digest'] and '文本' in result['digest']
    assert result['truncated'] is False


def test_file_count_cap_marks_truncated(tmp_path):
    for i in range(MAX_FILES + 5):
        _write(tmp_path / f'{i}.txt', str(i))
    result = read_workspace(str(tmp_path))
    assert len(result['files']) == MAX_FILES
    assert result['truncated'] is True


def test_oversize_file_skipped_and_marked(tmp_path):
    (tmp_path / 'big.txt').write_bytes(b'x' * (100 * 1024 + 1))
    _write(tmp_path / 'small.txt', 'ok')
    result = read_workspace(str(tmp_path))
    assert [f['path'] for f in result['files']] == ['small.txt']
    assert result['truncated'] is True


def test_total_size_cap_stops_and_marks_truncated(tmp_path):
    # 6 个 99KB 文件共约 594KB，超过 500KB 总量上限
    for i in range(6):
        (tmp_path / f'{i}.txt').write_bytes(b'x' * (99 * 1024))
    result = read_workspace(str(tmp_path))
    assert len(result['files']) < 6
    assert result['truncated'] is True


def test_gbk_decoded_and_undecodable_skipped(tmp_path):
    _write(tmp_path / 'gbk.txt', '中文内容', encoding='gbk')
    (tmp_path / 'bad.txt').write_bytes(b'\xff\xfe\x00\xd8\x00\x00\xff')
    _write(tmp_path / 'ok.txt', '正常')
    result = read_workspace(str(tmp_path))
    assert [f['path'] for f in result['files']] == ['gbk.txt', 'ok.txt']
    assert '中文内容' in result['digest']
