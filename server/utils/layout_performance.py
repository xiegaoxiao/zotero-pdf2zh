"""Cache exact page-layout predictions and expose optional CPU tuning."""
from functools import wraps
from hashlib import sha256
import json
import logging
import marshal
import math
import os
from pathlib import Path
import tempfile
import time

logger = logging.getLogger(__name__)
CACHE_SCHEMA = 1
MAX_CACHE_BYTES = 64 * 1024 * 1024
MAX_CACHE_FILES = 2048
MAX_AGE_SECONDS = 30 * 24 * 3600
_writes = 0


def cpu_session_options(runtime, providers, environ=None):
    """Keep measured defaults; expose explicit CPU tuning without touching GPUs."""
    if not providers or any(p != 'CPUExecutionProvider' for p in providers):
        return None
    environ = os.environ if environ is None else environ
    disable_spinning = environ.get('ZOTERO_PDF2ZH_DISABLE_SPINNING', '0').lower() in {'1', 'true', 'on'}
    if 'ZOTERO_PDF2ZH_CPU_THREADS' not in environ and not disable_spinning:
        return None
    # Keep ORT's automatic parallelism unless explicitly overridden. On hybrid
    # CPUs, reducing intra-op threads can make inference substantially slower.
    default = 0
    try:
        threads = int(environ.get('ZOTERO_PDF2ZH_CPU_THREADS', default))
    except (TypeError, ValueError):
        threads = default
    threads = max(0, min(threads, 8, os.cpu_count() or 1))
    options = runtime.SessionOptions()
    options.intra_op_num_threads = threads
    options.inter_op_num_threads = 1
    options.execution_mode = runtime.ExecutionMode.ORT_SEQUENTIAL
    if disable_spinning:
        options.add_session_config_entry('session.intra_op.allow_spinning', '0')
        options.add_session_config_entry('session.inter_op.allow_spinning', '0')
    logger.info('Layout CPU inference override: %d threads, disable spinning=%s', threads, disable_spinning)
    return options


def _cache_root():
    if os.environ.get('ZOTERO_PDF2ZH_LAYOUT_CACHE', '1').lower() in {'0', 'false', 'off'}:
        return None
    value = os.environ.get('ZOTERO_PDF2ZH_LAYOUT_CACHE_DIR')
    root = Path(value) if value else Path.home()/'.cache/zotero-pdf2zh/layout-v1'
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    return root


def _namespace(instance, function):
    signature = getattr(instance, '_zotero_layout_cache_namespace', None)
    if signature is None:
        digest = sha256()
        with Path(instance.model_path).open('rb') as stream:
            for block in iter(lambda: stream.read(1024*1024), b''):
                digest.update(block)
        # Include preprocessing/postprocessing code and runtime, not only weights.
        digest.update(marshal.dumps(function.__code__))
        for name in ('resize_and_pad_image', 'scale_boxes'):
            method = getattr(type(instance), name, None)
            if method is not None and hasattr(method, '__code__'):
                digest.update(marshal.dumps(method.__code__))
        import onnxruntime
        digest.update(onnxruntime.__version__.encode())
        digest.update(str(instance.model.get_providers()).encode())
        digest.update(str(instance.model.get_session_options().intra_op_num_threads).encode())
        signature = digest.hexdigest()
        instance._zotero_layout_cache_namespace = signature
    return signature


def _read_result(path, names):
    stat = path.stat()
    if time.time()-stat.st_mtime > MAX_AGE_SECONDS:
        raise ValueError('Expired layout cache')
    if stat.st_size > 2*1024*1024:
        raise ValueError('Oversized layout cache')
    data = json.loads(path.read_text(encoding='utf8'))
    boxes = data['boxes']
    if data.get('schema') != CACHE_SCHEMA or not isinstance(boxes, list) or len(boxes) > 5000:
        raise ValueError('Invalid layout cache')
    for box in boxes:
        if not isinstance(box, list) or len(box) != 6 or any(type(v) not in (int, float) or not math.isfinite(v) for v in box):
            raise ValueError('Invalid detection')
        if not 0 <= box[4] <= 1 or box[5] != int(box[5]):
            raise ValueError('Invalid detection class/confidence')
        if (isinstance(names, dict) and int(box[5]) not in names) or (not isinstance(names, dict) and not 0 <= box[5] < len(names)):
            raise ValueError('Unknown detection class')
    import numpy as np
    from babeldoc.docvision.base_doclayout import YoloResult
    return [YoloResult(boxes_data=np.asarray(boxes, dtype=np.float32).reshape(-1, 6), names=names)]


def prune_layout_cache(root, now=None):
    """Bound cache size/age, touching only digest-named cache files."""
    now = time.time() if now is None else now
    entries = []
    for path in root.glob('*.json'):
        if len(path.stem) != 64 or any(c not in '0123456789abcdef' for c in path.stem):
            continue
        try:
            stat = path.stat()
            if now-stat.st_mtime > MAX_AGE_SECONDS:
                path.unlink()
            else:
                entries.append((stat.st_mtime, stat.st_size, path))
        except OSError:
            continue
    size = sum(s for _, s, _ in entries)
    count = len(entries)
    for _, amount, path in sorted(entries):
        if size <= MAX_CACHE_BYTES and count <= MAX_CACHE_FILES:
            break
        try:
            path.unlink()
            size -= amount
            count -= 1
        except OSError:
            continue


def _write_result(path, result):
    global _writes
    if len(result) != 1:
        return
    boxes = [[*[float(v) for v in box.xyxy], float(box.conf), float(box.cls)] for box in result[0].boxes]
    data = json.dumps({'schema': CACHE_SCHEMA, 'boxes': boxes}, allow_nan=False, separators=(',', ':'))
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf8', dir=path.parent, prefix='.layout-', suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(data)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    _writes += 1
    if _writes % 64 == 1:
        prune_layout_cache(path.parent)


def cached_layout_predict(function):
    """Cache the single-image path used by BabelDOC; preserve other calls."""
    @wraps(function)
    def predict(instance, image, *args, **kwargs):
        import numpy as np
        # Only the upstream default single-page path has a verified cache schema.
        if args or kwargs or not isinstance(image, np.ndarray) or image.dtype != np.uint8 or image.ndim != 3 or image.shape[2] != 3:
            return function(instance, image, *args, **kwargs)
        path = None
        try:
            root = _cache_root()
            if root is not None:
                digest = sha256(f'{CACHE_SCHEMA}:{_namespace(instance, function)}:{image.shape}'.encode())
                digest.update(np.ascontiguousarray(image).tobytes())
                path = root/(digest.hexdigest()+'.json')
                if path.exists():
                    result = _read_result(path, instance._names)
                    if not getattr(instance, '_zotero_layout_cache_hits', 0):
                        logger.info('Reusing matching page-layout detections from the local cache')
                    instance._zotero_layout_cache_hits = getattr(instance, '_zotero_layout_cache_hits', 0)+1
                    return result
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            # Unreadable/corrupt caches are misses, never failed translations.
            pass
        result = function(instance, image, *args, **kwargs)
        if path is not None:
            try:
                _write_result(path, result)
            except (OSError, ValueError, TypeError, AttributeError):
                pass
        return result
    return predict
