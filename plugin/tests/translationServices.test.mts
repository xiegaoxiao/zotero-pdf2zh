import assert from "node:assert/strict";
import test from "node:test";
import {
    selectedTranslationService,
    translationServiceChoices,
} from "../src/modules/translationServices.ts";

const configs = [
    { service: "zhipu", model: "glm-4.5-flash", activate: true },
    { service: "deepseek", model: "deepseek-v4-flash", activate: false },
    { service: "openailiked", model: "custom-model", activate: true },
];

test("only active providers plus built-in SiliconFlow Free appear in 2.x", () => {
    const choices = translationServiceChoices("pdf2zh_next", configs);
    assert.deepEqual(
        choices.map((choice) => choice.value),
        ["siliconflowfree", "zhipu", "openailiked"],
    );
    assert.equal(choices[2].label, "Chat Compatible · custom-model");
    assert.equal(selectedTranslationService(choices, "zhipu"), "zhipu");
});

test("deactivating or deleting the selected provider returns 2.x to free", () => {
    for (const changed of [
        configs.map((api) => ({ ...api, activate: false })),
        configs.filter((api) => api.service !== "zhipu"),
    ]) {
        const choices = translationServiceChoices("pdf2zh_next", changed);
        assert.equal(
            selectedTranslationService(choices, "zhipu"),
            "siliconflowfree",
        );
        assert.ok(!choices.some((choice) => choice.value === "zhipu"));
    }
});

test("a stale legacy selection never appears merely because it was selected", () => {
    const choices = translationServiceChoices("pdf2zh_next", []);
    assert.deepEqual(choices, [
        { value: "siliconflowfree", label: "SiliconFlow Free" },
    ]);
    for (const old of ["bing", "google", "openai", "zhipu"]) {
        assert.equal(
            selectedTranslationService(choices, old),
            "siliconflowfree",
        );
    }
});

test("1.x shows an empty state when no API is active", () => {
    const choices = translationServiceChoices("pdf2zh", []);
    assert.deepEqual(choices, []);
    assert.equal(selectedTranslationService(choices, "bing"), "");
});

test("1.x excludes providers implemented only by 2.x", () => {
    const choices = translationServiceChoices("pdf2zh", [
        ...configs,
        { service: "claudecode", model: "sonnet", activate: true },
        { service: "siliconflowfree", model: "", activate: true },
    ]);
    assert.deepEqual(
        choices.map((choice) => choice.value),
        ["zhipu", "openailiked"],
    );
});

test("compatible aliases resolve to one choice and the same selection", () => {
    const choices = translationServiceChoices("pdf2zh_next", [
        configs[2],
        { ...configs[2], service: "openaicompatible" },
    ]);
    assert.equal(choices.length, 2);
    assert.equal(
        selectedTranslationService(choices, "openaicompatible"),
        "openailiked",
    );
});
