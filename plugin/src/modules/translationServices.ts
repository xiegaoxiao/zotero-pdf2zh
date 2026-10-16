import type { LLMApiData } from "./llmApiManager";

export interface TranslationServiceChoice {
    value: string;
    label: string;
}

type ApiChoice = Pick<LLMApiData, "service" | "model" | "activate">;

const SERVICE_LABELS: Record<string, string> = {
    deepseek: "DeepSeek",
    zhipu: "Zhipu",
    openailiked: "Chat Compatible",
    openai: "OpenAI",
    silicon: "SiliconFlow",
    siliconflow: "SiliconFlow",
    gemini: "Gemini",
    modelscope: "ModelScope",
};

export function canonicalService(service: string): string {
    return service === "openaicompatible" ? "openailiked" : service;
}

export function translationServiceChoices(
    engine: string,
    configs: readonly ApiChoice[],
): TranslationServiceChoice[] {
    const choices: TranslationServiceChoice[] =
        engine === "pdf2zh_next"
            ? [{ value: "siliconflowfree", label: "SiliconFlow Free" }]
            : [];
    const seen = new Set(choices.map((choice) => choice.value));
    for (const api of configs) {
        const service = canonicalService(api.service);
        if (!api.activate || !service || seen.has(service)) continue;
        if (
            engine !== "pdf2zh_next" &&
            ["siliconflowfree", "claudecode", "AliyunDashScope"].includes(
                service,
            )
        ) {
            continue;
        }
        const name = SERVICE_LABELS[service] || service;
        choices.push({
            value: service,
            label: api.model ? `${name} · ${api.model}` : name,
        });
        seen.add(service);
    }
    return choices;
}

export function selectedTranslationService(
    choices: readonly TranslationServiceChoice[],
    current: string,
): string {
    const service = canonicalService(current);
    return choices.some((choice) => choice.value === service)
        ? service
        : choices[0]?.value || "";
}
