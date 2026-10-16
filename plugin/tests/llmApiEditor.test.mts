import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { createContext, runInContext } from "node:vm";

const editor = readFileSync(
    new URL("../addon/content/llmApiEditor.xhtml", import.meta.url),
    "utf8",
);
const enhancements = readFileSync(
    new URL("../addon/content/llmApiEditorEnhancements.js", import.meta.url),
    "utf8",
);
const officialBase = "https://open.bigmodel.cn/api/paas/v4";

// A small DOM adapter runs the shipped editor scripts and their real event
// handlers, without Zotero, network calls, or access to a user's preferences.
class Element {
    tagName: string;
    id = "";
    value = "";
    className = "";
    textContent = "";
    title = "";
    hidden = false;
    checked = false;
    disabled = false;
    style: Record<string, string> = {};
    children: Element[] = [];
    parent: Element | undefined;
    attributes = new Map<string, string>();
    listeners = new Map<string, Array<(event: any) => unknown>>();
    constructor(tag: string) {
        this.tagName = tag.toUpperCase();
    }
    classList = {
        add: (name: string) => {
            this.className = `${this.className} ${name}`.trim();
        },
        remove: (name: string) => {
            this.className = this.className
                .split(/\s+/)
                .filter((value) => value !== name)
                .join(" ");
        },
        contains: (name: string) => this.className.split(/\s+/).includes(name),
    };
    get firstChild() {
        return this.children[0];
    }
    get options() {
        return this.children;
    }
    appendChild(child: Element) {
        child.remove();
        child.parent = this;
        this.children.push(child);
        return child;
    }
    insertBefore(child: Element, reference: Element) {
        child.remove();
        child.parent = this;
        this.children.splice(this.children.indexOf(reference), 0, child);
    }
    removeChild(child: Element) {
        this.children.splice(this.children.indexOf(child), 1);
        child.parent = undefined;
    }
    remove() {
        this.parent?.removeChild(this);
    }
    setAttribute(name: string, value: string) {
        this.attributes.set(name, value);
    }
    getAttribute(name: string) {
        return this.attributes.get(name);
    }
    getElementsByClassName(name: string): Element[] {
        return this.children.flatMap((child) => [
            ...(child.classList.contains(name) ? [child] : []),
            ...child.getElementsByClassName(name),
        ]);
    }
    querySelector(selector: string) {
        return this.getElementsByClassName(selector.slice(1))[0];
    }
    addEventListener(type: string, listener: (event: any) => unknown) {
        this.listeners.set(type, [
            ...(this.listeners.get(type) || []),
            listener,
        ]);
    }
    async dispatch(type: string) {
        for (const listener of this.listeners.get(type) || []) {
            await listener({ target: this, preventDefault() {} });
        }
    }
}

function openEditor(
    {
        data = {},
        history = {},
        request = async () => ({
            status: 200,
            response: { data: [{ id: "glm-4.7-flash" }] },
        }),
    } = {} as any,
) {
    const root = new Element("html");
    const elements = new Map<string, Element>();
    for (const match of editor.matchAll(/<(\w+)\b[^>]*\bid="([^"]+)"/g)) {
        const element = new Element(match[1]);
        element.id = match[2];
        root.appendChild(element);
        elements.set(element.id, element);
    }
    const head = new Element("head");
    root.appendChild(head);
    const footer = new Element("div");
    footer.className = "button-container";
    root.appendChild(footer);
    footer.appendChild(elements.get("service-doc-link")!);
    const ready: Array<() => unknown> = [];
    let stored = JSON.stringify(history);
    const args: any = { data, isEdit: !!data.key };
    const calls: any[] = [];
    const context = createContext({
        URL,
        document: {
            documentElement: root,
            head,
            getElementById: (id: string) =>
                elements.get(id) || findById(root, id),
            createElement: (tag: string) => new Element(tag),
            querySelector: (selector: string) => root.querySelector(selector),
            getElementsByClassName: (name: string) =>
                root.getElementsByClassName(name),
            addEventListener: (_type: string, listener: () => unknown) =>
                ready.push(listener),
        },
        navigator: { language: "zh-CN" },
        window: { arguments: [args], close() {} },
        Zotero: {
            locale: "zh-CN",
            Prefs: {
                get: () => stored,
                set: (_key: string, value: string) => {
                    stored = value;
                },
            },
            HTTP: {
                request: async (...values: any[]) => {
                    calls.push(values);
                    return request(...values);
                },
            },
        },
        alert: (message: string) => {
            throw new Error(message);
        },
    });
    for (const match of editor.matchAll(/<script>([\s\S]*?)<\/script>/g)) {
        runInContext(match[1], context);
    }
    runInContext(enhancements, context);
    for (const listener of ready) listener();
    return {
        element: (id: string) => elements.get(id) || findById(root, id)!,
        saved: () => args.result.data,
        history: () => JSON.parse(stored),
        calls,
    };
}

function findById(root: Element, id: string): Element | undefined {
    for (const child of root.children) {
        if (child.id === id) return child;
        const found = findById(child, id);
        if (found) return found;
    }
}

test("selecting Zhipu fills the preferred Flash model and official URL", async () => {
    const ui = openEditor();
    ui.element("serviceselect").value = "zhipu";
    await ui.element("serviceselect").dispatch("change");
    assert.equal(ui.element("model").value, "glm-4.5-flash");
    assert.equal(ui.element("apiUrl").value, officialBase);
    assert.equal(ui.element("modelselect").options[1].value, "glm-4.5-flash");
    assert.equal(ui.element("zhipu-preset-hint").hidden, false);
    await ui.element("save-btn").dispatch("click");
    assert.equal(ui.saved().model, "glm-4.5-flash");
    assert.equal(ui.saved().apiUrl, officialBase);
});

test("new configurations offer only the three preferred providers", () => {
    const ui = openEditor({ history: { gemini: { models: ["gemini-test"] } } });
    assert.deepEqual(
        ui.element("serviceselect").options.map((option) => option.value),
        ["", "zhipu", "deepseek", "openailiked"],
    );
});

test("legacy providers remain editable without restoring all presets", () => {
    const ui = openEditor({
        data: { key: "old", service: "gemini", model: "saved-model" },
    });
    assert.deepEqual(
        ui.element("serviceselect").options.map((option) => option.value),
        ["", "zhipu", "deepseek", "openailiked", "gemini"],
    );
    assert.equal(ui.element("model").value, "saved-model");
});

test("DeepSeek gets its own model and URL when switching providers", async () => {
    const ui = openEditor({ data: { service: "zhipu" } });
    ui.element("serviceselect").value = "deepseek";
    await ui.element("serviceselect").dispatch("change");
    assert.equal(ui.element("model").value, "deepseek-v4-flash");
    assert.equal(ui.element("apiUrl").value, "https://api.deepseek.com/v1");
});

test("typing Zhipu replaces another provider's built-in defaults", async () => {
    const ui = openEditor({
        data: {
            service: "openai",
            model: "gpt-5",
            apiUrl: "https://api.openai.com/v1",
        },
    });
    ui.element("service").value = "zhipu";
    await ui.element("service").dispatch("input");
    assert.equal(ui.element("model").value, "glm-4.5-flash");
    assert.equal(ui.element("apiUrl").value, officialBase);
});

test("editing migrates the obsolete URL while preserving credentials and model", async () => {
    const ui = openEditor({
        data: {
            key: "existing",
            service: "zhipu",
            model: "glm-4.5-air",
            apiKey: "test-key",
            apiUrl: "https://api.zhipu.com/v1/",
            activate: false,
        },
        history: {
            zhipu: {
                models: ["custom-glm"],
                urls: ["https://api.zhipu.com/v1/"],
                apiKeys: ["test-key"],
            },
        },
    });
    assert.equal(ui.element("apiUrl").value, officialBase);
    assert.equal(ui.element("modelselect").options[1].value, "glm-4.5-flash");
    assert.ok(
        ui
            .element("modelselect")
            .options.some((option) => option.value === "custom-glm"),
    );
    assert.deepEqual(ui.history().zhipu.urls, [officialBase]);
    await ui.element("save-btn").dispatch("click");
    assert.equal(ui.saved().model, "glm-4.5-air");
    assert.equal(ui.saved().apiKey, "test-key");
    assert.equal(ui.saved().activate, false);
});

test("custom URLs and models survive opening and saving", async () => {
    const ui = openEditor({
        data: {
            key: "custom",
            service: "zhipu",
            apiUrl: "https://gateway.example/v1",
            model: "my-custom-model",
        },
    });
    await ui.element("save-btn").dispatch("click");
    assert.equal(ui.saved().apiUrl, "https://gateway.example/v1");
    assert.equal(ui.saved().model, "my-custom-model");
});

test("fetching uses the official authenticated endpoint and retains Flash defaults", async () => {
    const ui = openEditor({ data: { service: "zhipu", apiKey: "test-key" } });
    await ui.element("fetch-models-btn").dispatch("click");
    assert.equal(ui.calls[0][0], "GET");
    assert.equal(ui.calls[0][1], `${officialBase}/models`);
    assert.equal(ui.calls[0][2].headers.Authorization, "Bearer test-key");
    assert.equal(ui.element("model").value, "glm-4.5-flash");
    assert.equal(ui.element("modelselect").options[1].value, "glm-4.5-flash");
    assert.match(ui.element("fetch-models-status").textContent, /已获取 1/);
});

test("a missing key does not send a request or remove built-in models", async () => {
    const ui = openEditor({ data: { service: "zhipu" } });
    await ui.element("fetch-models-btn").dispatch("click");
    assert.equal(ui.calls.length, 0);
    assert.match(ui.element("fetch-models-status").textContent, /需要 API Key/);
    assert.equal(ui.element("model").value, "glm-4.5-flash");
    assert.equal(ui.element("fetch-models-btn").disabled, false);
});

test("fetch errors keep presets and expose the full error in the tooltip", async () => {
    const ui = openEditor({
        data: { service: "zhipu", apiKey: "test-key" },
        request: async () => {
            throw new Error("HTTP 429: model service busy");
        },
    });
    await ui.element("fetch-models-btn").dispatch("click");
    const status = ui.element("fetch-models-status");
    assert.ok(status.classList.contains("error"));
    assert.match(status.title, /HTTP 429: model service busy/);
    assert.equal(ui.element("model").value, "glm-4.5-flash");
    assert.equal(ui.element("fetch-models-btn").disabled, false);
});

test("connection test uses unsaved form fields and performs a tiny authenticated chat request", async () => {
    const ui = openEditor({
        data: { service: "zhipu", apiKey: "test-key" },
        request: async () => ({
            status: 200,
            response: {
                model: "glm-4.5-flash",
                choices: [{ message: { content: "OK" } }],
            },
        }),
    });
    const before = ui.history();
    await ui.element("test-api-btn").dispatch("click");
    assert.equal(ui.calls[0][0], "POST");
    assert.equal(ui.calls[0][1], `${officialBase}/chat/completions`);
    const options = ui.calls[0][2];
    assert.equal(options.headers.Authorization, "Bearer test-key");
    assert.equal(options.timeout, 30000);
    assert.equal(options.successCodes, false);
    const body = JSON.parse(options.body);
    assert.equal(body.model, "glm-4.5-flash");
    assert.equal(body.max_tokens, 64);
    assert.equal(body.thinking.type, "disabled");
    assert.match(
        ui.element("api-test-status").textContent,
        /连接成功.*glm-4.5-flash/,
    );
    assert.match(ui.element("api-test-status").textContent, /返回：OK/);
    assert.ok(ui.element("api-test-status").classList.contains("success"));
    assert.deepEqual(ui.history(), before);
    assert.equal(ui.element("test-api-btn").disabled, false);
});

test("OpenCode connection tests include the routing session header required by the gateway", async () => {
    const ui = openEditor({
        data: {
            service: "openailiked",
            apiKey: "test-key",
            apiUrl: "https://opencode.ai/zen/go/v1",
            model: "deepseek-v4.1-flash",
        },
        request: async (_method, _url, options) =>
            options.headers["x-opencode-session"]
                ? {
                      status: 200,
                      response: { choices: [{ message: { content: "OK" } }] },
                  }
                : {
                      status: 400,
                      response: {
                          error: {
                              message: "Request is missing x-opencode-session",
                          },
                      },
                  },
    });
    await ui.element("test-api-btn").dispatch("click");
    assert.equal(
        ui.calls[0][1],
        "https://opencode.ai/zen/go/v1/chat/completions",
    );
    assert.equal(ui.calls[0][2].headers["x-opencode-session"], "zotero-pdf2zh");
    assert.equal(ui.calls[0][2].headers.Authorization, "Bearer test-key");
    assert.match(ui.element("api-test-status").textContent, /连接成功/);
});

test("OpenCode model-list requests use the same routing session header", async () => {
    const ui = openEditor({
        data: {
            service: "openailiked",
            apiKey: "test-key",
            apiUrl: "https://opencode.ai/zen/go/v1",
            model: "deepseek-v4.1-flash",
        },
    });
    await ui.element("fetch-models-btn").dispatch("click");
    assert.equal(ui.calls[0][1], "https://opencode.ai/zen/go/v1/models");
    assert.equal(ui.calls[0][2].headers["x-opencode-session"], "zotero-pdf2zh");
});

test("ordinary providers and lookalike hosts do not receive OpenCode routing headers", async () => {
    for (const base of [
        "https://gateway.example/v1",
        "https://opencode.ai.example/v1",
    ]) {
        const ui = openEditor({
            data: {
                service: "openailiked",
                apiKey: "test-key",
                apiUrl: base,
                model: "custom-model",
            },
        });
        await ui.element("fetch-models-btn").dispatch("click");
        assert.equal(ui.calls[0][2].headers["x-opencode-session"], undefined);
    }
});

test("connection errors preserve HTTP and provider codes while redacting credentials", async () => {
    for (const [http, code, message] of [
        [401, "1002", "Invalid key: test-key"],
        [429, "1113", "余额不足或无可用资源包"],
        [429, "1305", "该模型当前访问量过大"],
    ]) {
        const ui = openEditor({
            data: { service: "zhipu", apiKey: "test-key" },
            request: async () => ({
                status: http,
                response: { error: { code, message } },
            }),
        });
        await ui.element("test-api-btn").dispatch("click");
        const status = ui.element("api-test-status");
        assert.match(status.textContent, new RegExp(`HTTP ${http}.*${code}`));
        assert.ok(!status.textContent.includes("test-key"));
        assert.ok(status.classList.contains("error"));
        assert.equal(ui.element("test-api-btn").disabled, false);
    }
});

test("missing connection-test fields fail before sending any request", async () => {
    for (const data of [
        { service: "zhipu", apiKey: "" },
        {
            service: "openailiked",
            model: "",
            apiUrl: "https://gateway.example/v1",
        },
        { service: "openailiked", model: "custom-model", apiUrl: "" },
    ]) {
        const ui = openEditor({ data });
        await ui.element("test-api-btn").dispatch("click");
        assert.equal(ui.calls.length, 0);
        assert.match(ui.element("api-test-status").textContent, /连接失败/);
        assert.equal(ui.element("test-api-btn").disabled, false);
    }
});

test("compatible local endpoints can be tested without an API key or a duplicated path", async () => {
    const ui = openEditor({
        data: {
            service: "openailiked",
            model: "custom-model",
            apiUrl: "http://localhost:8000/v1/chat/completions/",
        },
        request: async () => ({
            status: 200,
            response: { choices: [{ message: { content: "OK" } }] },
        }),
    });
    await ui.element("test-api-btn").dispatch("click");
    assert.equal(ui.calls[0][1], "http://localhost:8000/v1/chat/completions");
    assert.equal(ui.calls[0][2].headers.Authorization, undefined);
    assert.match(ui.element("api-test-status").textContent, /连接成功/);
});

test("HTTP 200 without valid chat content is not reported as a successful connection", async () => {
    const ui = openEditor({
        data: { service: "zhipu", apiKey: "test-key" },
        request: async () => ({ status: 200, response: { data: [] } }),
    });
    await ui.element("test-api-btn").dispatch("click");
    assert.match(
        ui.element("api-test-status").textContent,
        /未返回有效的对话正文/,
    );
    assert.ok(ui.element("api-test-status").classList.contains("error"));
});

test("a timeout produces a useful error and allows another test", async () => {
    const ui = openEditor({
        data: { service: "zhipu", apiKey: "test-key" },
        request: async () => {
            const error = new Error("timeout");
            error.name = "TimeoutException";
            throw error;
        },
    });
    await ui.element("test-api-btn").dispatch("click");
    assert.match(
        ui.element("api-test-status").textContent,
        /请求超时（30 秒）/,
    );
    assert.equal(ui.element("test-api-btn").disabled, false);
});

test("non-JSON gateway errors retain their HTTP status with native JSON XHR", async () => {
    const ui = openEditor({
        data: { service: "zhipu", apiKey: "test-key" },
        request: async () => ({
            status: 503,
            response: null,
            get responseText() {
                throw new Error("InvalidStateError");
            },
        }),
    });
    await ui.element("test-api-btn").dispatch("click");
    assert.match(ui.element("api-test-status").textContent, /HTTP 503/);
    assert.match(ui.element("api-test-status").textContent, /暂时不可用/);
});

test("changing form fields discards results for the previous configuration", async () => {
    let finish: (value: any) => void = () => {};
    const response = new Promise((resolve) => {
        finish = resolve;
    });
    const ui = openEditor({
        data: { service: "zhipu", apiKey: "test-key" },
        request: () => response,
    });
    const pending = ui.element("test-api-btn").dispatch("click");
    assert.equal(ui.element("test-api-btn").disabled, true);
    ui.element("model").value = "glm-4.7-flash";
    await ui.element("model").dispatch("input");
    finish({
        status: 200,
        response: { choices: [{ message: { content: "OK" } }] },
    });
    await pending;
    assert.equal(ui.element("api-test-status").textContent, "");
    assert.equal(ui.element("test-api-btn").disabled, false);
});
