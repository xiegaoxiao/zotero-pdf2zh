import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { runInNewContext } from "node:vm";
import ts from "typescript";
import {
    selectedTranslationService,
    translationServiceChoices,
} from "../src/modules/translationServices.ts";

test("the author switch defaults off and its saved value reaches the server request config", () => {
    const source = readFileSync(
        new URL("../src/modules/pdf2zhHelper.ts", import.meta.url),
        "utf8",
    );
    const start = source.indexOf(
        "    static getServerConfig(): ServerConfig {",
    );
    const end = source.indexOf("    static getActiveLLMApiConfig", start);
    const code = ts.transpileModule(
        `export class Config { ${source.slice(start, end)} }`,
        { compilerOptions: { module: ts.ModuleKind.CommonJS } },
    ).outputText;
    let saved: boolean | undefined;
    const module = { exports: {} as any };
    runInNewContext(code, {
        module,
        exports: module.exports,
        loadLLMApisFromPrefs() {},
        addon: { data: {} },
        getPref: (name: string) =>
            name === "translateAuthors" ? saved : undefined,
        selectedTranslationService,
        translationServiceChoices,
    });
    assert.equal(
        module.exports.Config.getServerConfig().translateAuthors,
        "false",
    );
    saved = true;
    assert.equal(
        module.exports.Config.getServerConfig().translateAuthors,
        "true",
    );
    saved = false;
    assert.equal(
        module.exports.Config.getServerConfig().translateAuthors,
        "false",
    );
});
