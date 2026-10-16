"""Per-request thinking controls for the managed OpenAI-compatible translators."""
from __future__ import annotations

import ast
import os
from pathlib import Path
import re
import threading
from urllib.parse import urlparse

MODE_ENV = "ZOTERO_PDF2ZH_THINKING_MODE"
MARKER = "# zotero-pdf2zh thinking control v1"
_LOCK = threading.Lock()


def resolve_thinking_mode(value=None):
    mode = str(value or "disabled").strip().lower()
    if mode not in {"enabled", "disabled"}:
        raise ValueError("思考模式只能是 enabled 或 disabled。")
    return mode


def thinking_request_body(model, base_url, mode="disabled"):
    """Use provider-specific parameters only for recognized hybrid models."""
    mode = resolve_thinking_mode(mode)
    name = str(model or "").lower().split("/")[-1]
    host = urlparse(str(base_url or "")).hostname or ""
    # These reasoning-only variants cannot honor an off switch.
    if "-thinking" in name or name.startswith(("deepseek-r1", "qwq")):
        return {}
    glm = bool(re.match(r"glm-4\.[567]", name))
    deepseek = name.startswith(("deepseek-v4", "deepseek-v3.1", "deepseek-v3.2"))
    qwen = name.startswith(("qwen3", "qwen-plus", "qwen-flash"))
    if not (glm or deepseek or qwen):
        return {}
    provider_bool = (
        host.endswith(".aliyuncs.com") or host in {"api.siliconflow.cn", "api.siliconflow.com"}
    )
    if provider_bool:
        return {"enable_thinking": mode == "enabled"}
    if glm or deepseek:
        return {"thinking": {"type": mode}}
    # Local vLLM/SGLang OpenAI-compatible Qwen deployments use chat templates.
    if host in {"localhost", "127.0.0.1", "::1"}:
        return {"chat_template_kwargs": {"enable_thinking": mode == "enabled"}}
    return {}


def configure_thinking(translator, model, base_url):
    body = thinking_request_body(model, base_url, os.environ.get(MODE_ENV, "disabled"))
    if not body:
        return
    extra = dict(translator.options.get("extra_body") or {})
    extra.pop("thinking", None)
    extra.pop("enable_thinking", None)
    if "chat_template_kwargs" in body:
        body["chat_template_kwargs"] = {
            **extra.get("chat_template_kwargs", {}),
            **body["chat_template_kwargs"],
        }
    extra.update(body)
    translator.options["extra_body"] = extra
    translator.extra_body = extra
    if resolve_thinking_mode(os.environ.get(MODE_ENV)) == "disabled":
        translator.options.pop("reasoning_effort", None)
    translator.add_cache_impact_parameters("thinking_control", extra)


def install_thinking_control(env_dir, engine):
    root = Path(env_dir)
    sites = [root / "Lib/site-packages", *root.glob("lib/python*/site-packages")]
    relative = (
        "pdf2zh_next/translator/translator_impl/openai.py"
        if engine == "pdf2zh_next" else "pdf2zh/translator.py"
    )
    site = next((site for site in sites if (site / relative).is_file()), None)
    if site is None:
        raise RuntimeError(f"找不到 {engine} 的思考模式控制入口。")
    target = site / relative
    with _LOCK:
        source = target.read_text(encoding="utf-8")
        changed = MARKER not in source
        if changed:
            if engine == "pdf2zh_next":
                anchor = "        self.model = settings.translate_engine_settings.openai_model\n"
                base_url = "settings.translate_engine_settings.openai_base_url"
            else:
                anchor = "        self.think_filter_regex = re.compile(think_filter_regex, flags=re.DOTALL)\n"
                base_url = "str(self.client.base_url)"
            if source.count(anchor) != 1:
                raise RuntimeError(f"不支持的 {engine} 思考控制入口；未修改引擎文件。")
            hook = (
                f"        {MARKER}\n"
                "        from zotero_pdf_thinking_control import configure_thinking\n"
                f"        configure_thinking(self, self.model, {base_url})\n"
            )
            source = source.replace(anchor, anchor + hook, 1)
            ast.parse(source)
        helper = site / "zotero_pdf_thinking_control.py"
        module = Path(__file__).read_text(encoding="utf-8")
        helper_changed = not helper.exists() or helper.read_text(encoding="utf-8") != module
        if helper_changed:
            helper.write_text(module, encoding="utf-8")
        if changed:
            backup = target.with_suffix(target.suffix + ".before_zotero_thinking_control")
            if not backup.exists():
                backup.write_bytes(target.read_bytes())
            target.write_text(source, encoding="utf-8")
    return changed or helper_changed
