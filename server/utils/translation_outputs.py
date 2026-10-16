"""Validate and publish outputs from a private translation attempt directory."""
from pathlib import Path
import os
from pypdf import PdfReader


def require_pdf_outputs(paths):
    if not paths:
        raise RuntimeError('没有指定需要生成的译文文件。')
    missing = [str(Path(p).name) for p in paths if not Path(p).is_file() or Path(p).stat().st_size == 0]
    if missing:
        raise RuntimeError('翻译引擎未生成本次任务所需的文件：' + '、'.join(missing) + '。请查看前面的引擎错误；旧译文不会被当作本次成功结果。')
    for path in paths:
        try:
            if len(PdfReader(path).pages) == 0:
                raise ValueError('PDF has no pages')
        except Exception as exc:
            raise RuntimeError(f'本次生成的 PDF 无法读取：{Path(path).name}：{exc}') from exc
    return list(paths)


def publish_pdf_outputs(paths, output_dir):
    require_pdf_outputs(paths)
    root = Path(output_dir)
    backup_dir = Path(paths[0]).parent / '_previous_outputs'
    backup_dir.mkdir(exist_ok=True)
    backups, published = [], []
    try:
        for path in paths:
            source = Path(path)
            destination = root / source.name
            if destination.exists():
                backup = backup_dir / source.name
                os.replace(destination, backup)
                backups.append((backup, destination))
            os.replace(source, destination)
            published.append(destination)
    except OSError as exc:
        for destination in reversed(published):
            destination.unlink(missing_ok=True)
        for backup, destination in reversed(backups):
            os.replace(backup, destination)
        raise RuntimeError('无法保存新译文，已还原旧文件；请关闭占用译文的程序后重试。') from exc
    return [str(p) for p in published]
