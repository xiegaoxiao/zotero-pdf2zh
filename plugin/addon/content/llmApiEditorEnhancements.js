/* eslint-disable no-restricted-globals */
/* global AbortController, URL, setTimeout, clearTimeout, Zotero, DEFAULT_SERVICES, bindInputSelectValue, currentData, document, fetch, findExtraFieldRow, mergedServices, navigator, normalizeZhipuBaseUrl, updateDeepSeekReasoningEffortState, updateModelOptions */

(() => {
    "use strict";

    const DEPRECATED_DEEPSEEK_MODELS = new Set([
        "deepseek-chat",
        "deepseek-reasoner",
    ]);

    const TEXT = {
        zh: {
            fetchModels: "获取模型列表",
            fetching: "正在获取模型列表…",
            fetched: (count) => `已获取 ${count} 个模型；默认模型仍保留`,
            noModels: "接口返回成功，但没有识别到模型列表",
            baseUrlRequired: "请先填写 Base URL",
            apiKeyRequired: "该服务获取模型列表需要 API Key",
            testConnection: "测试连通性",
            testingConnection: "正在测试 API 连通性…",
            testKeyRequired: "请先填写 API Key",
            modelRequired: "请先选择或填写模型名称",
            invalidBaseUrl: "Base URL 必须是 http:// 或 https:// 地址",
            testUnsupported:
                "此旧服务不使用 Chat Completions 接口，请使用 Chat Compatible 配置测试",
            connected: (model, seconds, reply) =>
                `连接成功 · ${model} · ${seconds} 秒\n返回：${reply}`,
            connectionFailed: (message) => `连接失败：${message}`,
            emptyReply: "接口未返回有效的对话正文，请检查模型与响应格式",
            timeout: "请求超时（30 秒），请稍后重试",
            networkError: "无法连接到 API，请检查地址、网络或代理设置",
            unauthorized: "鉴权失败，请检查 API Key",
            forbidden: "没有访问权限，请检查模型权限或账户状态",
            notFound: "接口或模型不存在，请检查 Base URL 与模型名称",
            rateLimited: "请求受限，请检查服务负载或账户额度",
            serverError: "API 服务暂时不可用，请稍后重试",
            failed: (message) => `获取失败：${message}`,
            legacyChat:
                "旧 deepseek-chat 已迁移为 deepseek-v4-flash（思考关闭）",
            legacyReasoner:
                "旧 deepseek-reasoner 已迁移为 deepseek-v4-flash（思考开启）",
            unsupported:
                "当前服务可能没有兼容的模型列表接口；默认模型选项不会受影响",
            disabled: "关闭",
            enabled: "开启",
            high: "高",
            max: "最大",
        },
        en: {
            fetchModels: "Fetch Model List",
            fetching: "Fetching model list…",
            fetched: (count) =>
                `Fetched ${count} models; built-in defaults are still available`,
            noModels: "The request succeeded, but no model list was recognized",
            baseUrlRequired: "Enter a Base URL first",
            apiKeyRequired:
                "An API Key is required to fetch models for this service",
            testConnection: "Test Connection",
            testingConnection: "Testing API connection…",
            testKeyRequired: "Enter an API Key first",
            modelRequired: "Select or enter a model first",
            invalidBaseUrl: "Base URL must start with http:// or https://",
            testUnsupported:
                "This legacy service does not use Chat Completions. Test it using a Chat Compatible configuration.",
            connected: (model, seconds, reply) =>
                `Connected · ${model} · ${seconds}s\nReply: ${reply}`,
            connectionFailed: (message) => `Connection failed: ${message}`,
            emptyReply:
                "The API returned no valid chat content. Check the model and response format.",
            timeout: "Request timed out after 30 seconds. Try again later.",
            networkError:
                "Cannot connect to the API. Check the URL, network, or proxy.",
            unauthorized: "Authentication failed. Check the API Key.",
            forbidden:
                "Access denied. Check model permissions or account status.",
            notFound:
                "Endpoint or model not found. Check the Base URL and model.",
            rateLimited:
                "Request limited. Check service load or account quota.",
            serverError: "The API is temporarily unavailable. Try again later.",
            failed: (message) => `Fetch failed: ${message}`,
            legacyChat:
                "Legacy deepseek-chat migrated to deepseek-v4-flash (thinking disabled)",
            legacyReasoner:
                "Legacy deepseek-reasoner migrated to deepseek-v4-flash (thinking enabled)",
            unsupported:
                "This provider may not expose a compatible model-list endpoint; built-in defaults are unchanged",
            disabled: "Disabled",
            enabled: "Enabled",
            high: "High",
            max: "Max",
        },
    };

    function languageKey() {
        const lang = String(
            document.documentElement.lang || navigator.language || "en",
        ).toLowerCase();
        return lang.startsWith("zh") ? "zh" : "en";
    }

    function text(key, ...args) {
        const value = TEXT[languageKey()][key] ?? TEXT.en[key] ?? key;
        return typeof value === "function" ? value(...args) : value;
    }

    function normalizeBaseUrl(value) {
        return String(value || "")
            .trim()
            .replace(/\/+$/, "");
    }

    function modelRequestSpec(service, baseUrl, apiKey) {
        const serviceConfig = DEFAULT_SERVICES[service] || {};
        const defaultBase = serviceConfig.urls?.[0] || "";
        const base = normalizeBaseUrl(baseUrl || defaultBase);

        if (service === "zhipu") {
            if (!apiKey) throw new Error(text("apiKeyRequired"));
            const zhipuBase = normalizeZhipuBaseUrl(base);
            return {
                url: zhipuBase.endsWith("/models")
                    ? zhipuBase
                    : `${zhipuBase}/models`,
                headers: { Authorization: `Bearer ${apiKey}` },
            };
        }

        if (service === "deepseek") {
            if (!apiKey) throw new Error(text("apiKeyRequired"));
            return {
                url: "https://api.deepseek.com/models",
                headers: { Authorization: `Bearer ${apiKey}` },
            };
        }

        if (service === "openai") {
            if (!apiKey) throw new Error(text("apiKeyRequired"));
            return {
                url: `${base || "https://api.openai.com/v1"}/models`,
                headers: { Authorization: `Bearer ${apiKey}` },
            };
        }

        if (service === "gemini") {
            if (!apiKey) throw new Error(text("apiKeyRequired"));
            const geminiBase =
                base || "https://generativelanguage.googleapis.com/v1beta";
            return {
                url: `${geminiBase}/models?key=${encodeURIComponent(apiKey)}`,
                headers: {},
            };
        }

        if (service === "ollama") {
            const ollamaBase = base || "http://localhost:11434";
            return { url: `${ollamaBase}/api/tags`, headers: {} };
        }

        if (!base) throw new Error(text("baseUrlRequired"));
        return {
            url: base.endsWith("/models") ? base : `${base}/models`,
            headers: apiKey ? { Authorization: `Bearer ${apiKey}` } : {},
        };
    }

    function responseError(status, payload) {
        const detail = payload?.error;
        const message = typeof detail === "string" ? detail : detail?.message;
        const code = detail?.code;
        const kind = {
            401: "unauthorized",
            403: "forbidden",
            404: "notFound",
            429: "rateLimited",
        }[status];
        const hint = kind
            ? text(kind)
            : status >= 500
              ? text("serverError")
              : "";
        return new Error(
            [
                status ? `HTTP ${status}` : "",
                code ? `[${code}]` : "",
                message || hint,
            ]
                .filter(Boolean)
                .join(" "),
        );
    }

    async function requestJson(
        url,
        headers,
        method = "GET",
        body = null,
        timeout = 20000,
    ) {
        // Match the session header used by the translation runtime. Match the
        // hostname exactly so unrelated gateways do not receive routing hints.
        if (new URL(url).hostname === "opencode.ai") {
            headers = { ...headers, "x-opencode-session": "zotero-pdf2zh" };
        }
        if (typeof Zotero !== "undefined" && Zotero.HTTP?.request) {
            const xhr = await Zotero.HTTP.request(method, url, {
                headers,
                ...(body ? { body: JSON.stringify(body) } : {}),
                responseType: "json",
                timeout,
                successCodes: false,
            });
            let payload = xhr.response;
            if (!payload || typeof payload !== "object") {
                let raw = payload || "";
                // Native XHR forbids responseText when responseType is json.
                try {
                    raw = xhr.responseText || raw;
                } catch {
                    /* No text fallback. */
                }
                try {
                    payload = JSON.parse(raw);
                } catch {
                    payload = null;
                }
            }
            if (xhr.status < 200 || xhr.status >= 300) {
                throw responseError(xhr.status, payload);
            }
            if (payload?.error) throw responseError(xhr.status, payload);
            return payload;
        }

        const controller = new AbortController();
        const timer = setTimeout(() => controller.abort(), timeout);
        try {
            const response = await fetch(url, {
                method,
                headers,
                ...(body ? { body: JSON.stringify(body) } : {}),
                signal: controller.signal,
            });
            let payload;
            try {
                payload = await response.json();
            } catch {
                payload = null;
            }
            if (!response.ok || payload?.error)
                throw responseError(response.status, payload);
            return payload;
        } finally {
            clearTimeout(timer);
        }
    }

    function connectionRequestSpec(service, baseUrl, apiKey, model) {
        if (
            ![
                "zhipu",
                "deepseek",
                "openailiked",
                "openaicompatible",
                "openai",
            ].includes(service)
        ) {
            throw new Error(text("testUnsupported"));
        }
        if (!model) throw new Error(text("modelRequired"));
        if (["zhipu", "deepseek", "openai"].includes(service) && !apiKey) {
            throw new Error(text("testKeyRequired"));
        }
        let base = normalizeBaseUrl(baseUrl);
        if (service === "zhipu") base = normalizeZhipuBaseUrl(base);
        if (!base) throw new Error(text("baseUrlRequired"));
        if (!/^https?:\/\//i.test(base))
            throw new Error(text("invalidBaseUrl"));
        const body = {
            model,
            messages: [{ role: "user", content: "Reply with exactly: OK" }],
            max_tokens: 64,
            stream: false,
        };
        // Keep this tiny probe non-thinking, independent of translation settings.
        const host = new URL(base).hostname;
        const name = model.toLowerCase().split("/").pop();
        const hybrid =
            /^(glm-4\.[567]|deepseek-v4|deepseek-v3\.[12]|qwen3|qwen-plus|qwen-flash)/.test(
                name,
            ) && !name.includes("-thinking");
        if (hybrid) {
            if (
                host.endsWith(".aliyuncs.com") ||
                ["api.siliconflow.cn", "api.siliconflow.com"].includes(host)
            ) {
                body.enable_thinking = false;
            } else if (/^(glm-|deepseek-)/.test(name)) {
                body.thinking = { type: "disabled" };
            } else if (["localhost", "127.0.0.1", "[::1]"].includes(host)) {
                body.chat_template_kwargs = { enable_thinking: false };
            }
        }
        if (/^(gpt-5|o[1-9])/.test(name)) {
            delete body.max_tokens;
            body.max_completion_tokens = 64;
        }
        return {
            url: base.endsWith("/chat/completions")
                ? base
                : `${base}/chat/completions`,
            headers: {
                "Content-Type": "application/json",
                ...(apiKey ? { Authorization: `Bearer ${apiKey}` } : {}),
            },
            body,
        };
    }

    function connectionErrorMessage(error, apiKey) {
        const raw = error?.message || String(error || "");
        const name = error?.name || "";
        let message = /timeout|timed out|abort/i.test(`${name} ${raw}`)
            ? text("timeout")
            : /network|failed to fetch|status.*0\b/i.test(`${name} ${raw}`)
              ? text("networkError")
              : raw || text("networkError");
        if (apiKey) message = message.split(apiKey).join("********");
        return message.slice(0, 800);
    }

    function installConnectionTestControls() {
        const controls = document.querySelector(".model-list-actions");
        const status = document.getElementById("api-test-status");
        if (!controls || !status || document.getElementById("test-api-btn"))
            return;
        const button = document.createElement("button");
        button.type = "button";
        button.id = "test-api-btn";
        button.className = "btn btn-secondary btn-compact";
        button.textContent = text("testConnection");
        controls.insertBefore(button, controls.firstChild);
        let generation = 0;
        const formValues = () =>
            ["service", "apiUrl", "apiKey", "model"].map((id) =>
                document.getElementById(id).value.trim(),
            );
        for (const id of [
            "service",
            "serviceselect",
            "apiUrl",
            "apiUrlSelect",
            "apiKey",
            "apiKeySelect",
            "model",
            "modelselect",
        ]) {
            for (const event of ["input", "change"]) {
                document.getElementById(id).addEventListener(event, () => {
                    generation++;
                    status.textContent = "";
                    status.title = "";
                });
            }
        }
        button.addEventListener("click", async () => {
            if (button.disabled) return;
            const values = formValues();
            const [service, base, apiKey, model] = values;
            const current = ++generation;
            const unchanged = () =>
                current === generation &&
                JSON.stringify(values) === JSON.stringify(formValues());
            const started = Date.now();
            button.disabled = true;
            status.classList.remove("error");
            status.classList.remove("success");
            status.textContent = text("testingConnection");
            try {
                const spec = connectionRequestSpec(
                    service,
                    base,
                    apiKey,
                    model,
                );
                const payload = await requestJson(
                    spec.url,
                    spec.headers,
                    "POST",
                    spec.body,
                    30000,
                );
                const content = payload?.choices?.[0]?.message?.content;
                if (typeof content !== "string" || !content.trim())
                    throw new Error(text("emptyReply"));
                if (!unchanged()) return;
                const reply = (
                    apiKey ? content.split(apiKey).join("********") : content
                )
                    .trim()
                    .slice(0, 120);
                status.textContent = text(
                    "connected",
                    model,
                    ((Date.now() - started) / 1000).toFixed(2),
                    reply,
                );
                status.title = status.textContent;
                status.classList.add("success");
            } catch (error) {
                if (!unchanged()) return;
                status.textContent = text(
                    "connectionFailed",
                    connectionErrorMessage(error, apiKey),
                );
                status.title = status.textContent;
                status.classList.add("error");
            } finally {
                button.disabled = false;
            }
        });
    }

    function extractModelIds(payload) {
        let list = [];
        if (Array.isArray(payload)) list = payload;
        else if (Array.isArray(payload?.data)) list = payload.data;
        else if (Array.isArray(payload?.models)) list = payload.models;
        else if (Array.isArray(payload?.result?.data))
            list = payload.result.data;
        else if (Array.isArray(payload?.result)) list = payload.result;

        return [
            ...new Set(
                list
                    .map((item) => {
                        if (typeof item === "string") return item;
                        return (
                            item?.id ||
                            item?.name ||
                            item?.model ||
                            item?.model_name ||
                            ""
                        );
                    })
                    .map((value) => {
                        const normalized = String(value);
                        return normalized.startsWith("models/")
                            ? normalized.slice("models/".length)
                            : normalized;
                    })
                    .filter(Boolean),
            ),
        ];
    }

    function installModelFetchControls() {
        const footer = document.querySelector(".button-container");
        const link = document.getElementById("service-doc-link");
        if (!footer || !link || document.getElementById("fetch-models-btn"))
            return;

        const left = document.createElement("div");
        left.className = "model-list-actions";
        footer.insertBefore(left, link);
        left.appendChild(link);

        const button = document.createElement("button");
        button.type = "button";
        button.id = "fetch-models-btn";
        button.className = "btn btn-secondary btn-compact";
        button.textContent = text("fetchModels");
        left.insertBefore(button, link);

        const status = document.createElement("span");
        status.id = "fetch-models-status";
        status.className = "model-fetch-status";
        left.appendChild(status);

        const style = document.createElement("style");
        style.textContent = `
            .model-list-actions {
                display: flex;
                flex: 1;
                flex-wrap: wrap;
                align-items: center;
                gap: 8px;
                min-width: 0;
            }
            .model-list-actions .btn-compact {
                margin-left: 0;
                padding: 6px 10px;
                font-size: 12px;
                white-space: nowrap;
            }
            .model-fetch-status {
                max-width: 320px;
                white-space: normal;
                overflow-wrap: anywhere;
                color: #666;
                font-size: 12px;
            }
            .model-fetch-status.error {
                color: #c0392b;
            }
        `;
        document.head.appendChild(style);

        button.addEventListener("click", async () => {
            const service = document.getElementById("service").value.trim();
            const baseUrl = document.getElementById("apiUrl").value.trim();
            const apiKey = document.getElementById("apiKey").value.trim();

            button.disabled = true;
            status.classList.remove("error");
            status.textContent = text("fetching");
            try {
                const spec = modelRequestSpec(service, baseUrl, apiKey);
                const payload = await requestJson(spec.url, spec.headers);
                let models = extractModelIds(payload);
                if (service === "deepseek") {
                    models = models.filter(
                        (model) => !DEPRECATED_DEEPSEEK_MODELS.has(model),
                    );
                }
                if (!models.length) throw new Error(text("noModels"));

                if (!mergedServices[service]) {
                    mergedServices[service] = {
                        name: service,
                        models: [],
                        urls: baseUrl ? [baseUrl] : [],
                        apiKeys: [],
                    };
                }
                const defaults = DEFAULT_SERVICES[service]?.models || [];
                const existing = mergedServices[service].models || [];
                mergedServices[service].models = [
                    ...new Set([...defaults, ...existing, ...models.sort()]),
                ];
                updateModelOptions(service);
                status.textContent = text("fetched", models.length);
                status.title = status.textContent;
            } catch (error) {
                const message =
                    error?.message || String(error || "Unknown error");
                status.textContent = text("failed", message);
                status.title = `${status.textContent}\n${text("unsupported")}`;
                status.classList.add("error");
            } finally {
                button.disabled = false;
            }
        });
    }

    function setExtraSelectValue(key, value) {
        const row = findExtraFieldRow(key);
        const select = row?.querySelector(".extra-value");
        if (select) select.value = value;
    }

    function localizeDeepSeekSelectLabels() {
        const labels = {
            disabled: text("disabled"),
            enabled: text("enabled"),
            high: text("high"),
            max: text("max"),
        };
        for (const key of [
            "deepseek_thinking_mode",
            "deepseek_reasoning_effort",
        ]) {
            const select =
                findExtraFieldRow(key)?.querySelector(".extra-value");
            if (!select || select.tagName.toLowerCase() !== "select") continue;
            for (const option of select.options) {
                if (labels[option.value])
                    option.textContent = labels[option.value];
            }
        }
    }

    function migrateLegacyDeepSeekModel() {
        const service = document.getElementById("service").value;
        const modelInput = document.getElementById("model");
        if (
            service !== "deepseek" ||
            !DEPRECATED_DEEPSEEK_MODELS.has(modelInput.value)
        ) {
            return;
        }

        const legacyModel = modelInput.value;
        const explicitMode = Object.prototype.hasOwnProperty.call(
            currentData?.extraData || {},
            "deepseek_thinking_mode",
        );

        bindInputSelectValue("deepseek-v4-flash", "model");
        updateModelOptions("deepseek");

        if (!explicitMode) {
            if (legacyModel === "deepseek-reasoner") {
                setExtraSelectValue("deepseek_thinking_mode", "enabled");
                setExtraSelectValue("deepseek_reasoning_effort", "high");
            } else {
                setExtraSelectValue("deepseek_thinking_mode", "disabled");
            }
            updateDeepSeekReasoningEffortState();
        }

        const status = document.getElementById("fetch-models-status");
        if (status) {
            status.textContent =
                legacyModel === "deepseek-reasoner"
                    ? text("legacyReasoner")
                    : text("legacyChat");
        }
    }

    document.addEventListener("DOMContentLoaded", () => {
        installModelFetchControls();
        installConnectionTestControls();
        migrateLegacyDeepSeekModel();
        localizeDeepSeekSelectLabels();
    });
})();
