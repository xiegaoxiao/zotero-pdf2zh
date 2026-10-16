import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { runInNewContext } from "node:vm";
import ts from "typescript";
import {
    BatchCancellation,
    JobCancelledError,
} from "../src/modules/jobCancellation.ts";

test("cancelling queued work prevents submission", async () => {
    let calls = 0;
    const control = new BatchCancellation(async () => {
        calls++;
    });
    await control.request();
    assert.throws(() => control.checkpoint(), JobCancelledError);
    assert.equal(calls, 0);
});

test("cancellation while the POST is pending is sent as soon as the task ID arrives", async () => {
    const jobs: string[] = [];
    const control = new BatchCancellation(async (job) => {
        jobs.push(job.taskId);
    });
    await control.request();
    await control.bindJob({
        serverUrl: "http://localhost:8890",
        taskId: "late-id",
    });
    assert.deepEqual(jobs, ["late-id"]);
    // Continue polling until the backend confirms its final state.
    assert.doesNotThrow(() => control.checkpoint());
    control.clearJob();
    assert.throws(() => control.checkpoint(), JobCancelledError);
});

test("a failed backend cancellation reports the error and keeps the running task monitored", async () => {
    const errors: unknown[] = [];
    const control = new BatchCancellation(
        async () => {
            throw new Error("Server needs update");
        },
        (error) => errors.push(error),
    );
    await control.bindJob({
        serverUrl: "http://localhost:8890",
        taskId: "active",
    });
    await control.request();
    assert.equal(errors.length, 1);
    assert.equal(control.requested, false);
    assert.doesNotThrow(() => control.checkpoint());
});

function compiled(source: string) {
    return ts.transpileModule(source, {
        compilerOptions: {
            module: ts.ModuleKind.CommonJS,
            target: ts.ScriptTarget.ES2022,
        },
    }).outputText;
}

test("a confirmed cancellation is never retried as a new server job", async () => {
    const source = readFileSync(
        new URL("../src/modules/pdf2zhHelper.ts", import.meta.url),
        "utf8",
    );
    const start = source.indexOf("    static async retryOperation<T>(");
    const end = source.indexOf("    // 获取item", start);
    const module = { exports: {} as any };
    runInNewContext(
        compiled(`export class Retry { ${source.slice(start, end)} }`),
        {
            module,
            exports: module.exports,
            JobCancelledError,
            Error,
            setTimeout,
            ztoolkit: { log() {} },
        },
    );
    let submitted = 0;
    await assert.rejects(
        module.exports.Retry.retryOperation(
            async () => {
                submitted++;
                throw new JobCancelledError();
            },
            3,
            0,
        ),
        JobCancelledError,
    );
    assert.equal(submitted, 1);
});

test("cancelling an active batch stops later files and counts cancellations separately", async () => {
    let processed = 0;
    const updates: any[] = [];
    const control = new BatchCancellation(async () => {});
    const module = { exports: {} as any };
    const source = readFileSync(
        new URL("../src/modules/pdf2zhFileProcessor.ts", import.meta.url),
        "utf8",
    );
    runInNewContext(compiled(source), {
        module,
        exports: module.exports,
        ztoolkit: { log() {} },
        require: (name: string) =>
            name === "./jobCancellation"
                ? { BatchCancellation, JobCancelledError }
                : {
                      PDF2zhHelperFactory: {
                          processSingleFile: async () => {
                              processed++;
                              await control.bindJob({
                                  serverUrl: "http://localhost:8890",
                                  taskId: "current",
                              });
                              await control.request();
                              control.clearJob();
                              control.checkpoint();
                          },
                      },
                  },
    });
    const tasks = ["first", "second", "third"].map((fileName) => ({
        fileName,
        endpoint: "translate",
    }));
    const result =
        await module.exports.FileProcessor.getInstance().processBatch(
            tasks,
            (update: any) => updates.push(update),
            control,
        );
    assert.equal(processed, 1);
    assert.equal(result.cancelled, 3);
    assert.equal(result.failed, 0);
    assert.equal(result.succeeded, 0);
    assert.equal(
        updates.filter((update) => update.phase === "file-cancelled").length,
        3,
    );
});

function popupHarness(control: BatchCancellation) {
    let opened = 0;
    let renders = 0;
    const dialogs: any[] = [];
    const body = {
        replaceChildren() {
            renders++;
        },
        appendChild() {},
    };
    class Dialog {
        buttons = new Map<string, any>();
        data: any;
        window = {
            closed: false,
            document: {
                getElementById: (id: string) =>
                    id === "pdf2zh-job-progress-body"
                        ? body
                        : this.buttons.get(id),
                createElementNS: () => ({ textContent: "", style: {} }),
            },
        };
        constructor() {
            dialogs.push(this);
        }
        addCell() {
            return this;
        }
        addButton(_label: string, id: string, options: any = {}) {
            this.buttons.set(id, { ...options, disabled: false });
            return this;
        }
        setDialogData(data: any) {
            this.data = data;
            return this;
        }
        open() {
            opened++;
            return this;
        }
    }
    const source = readFileSync(
        new URL("../src/modules/pdf2zhHelper.ts", import.meta.url),
        "utf8",
    );
    const module = { exports: {} as any };
    runInNewContext(
        compiled(source.slice(source.indexOf("export class JobProgressPopup"))),
        {
            module,
            exports: module.exports,
            ztoolkit: { Dialog },
            getPref: () => true,
            getString: (key: string) => key,
            PDF2zhHelperFactory: {
                isTrue: () => true,
                formatJobProgressText: () => "running",
                jobProgressPercent: () => 15,
            },
        },
    );
    const popup = module.exports.JobProgressPopup.open(["paper.pdf"], control);
    const dialog = dialogs[0];
    dialog.data.loadCallback();
    return { popup, dialog, opened: () => opened, renders: () => renders };
}

test("closing the progress window never reopens it or cancels the task", async () => {
    const control = new BatchCancellation(async () => {});
    const ui = popupHarness(control);
    ui.dialog.buttons.get("pdf2zh-job-close").callback();
    ui.dialog.window.closed = true;
    ui.dialog.data.unloadCallback();
    const before = ui.renders();
    ui.popup.updateFile({
        current: 1,
        total: 1,
        phase: "running",
        percent: 30,
    });
    ui.popup.complete(1, 0);
    assert.equal(ui.opened(), 1);
    assert.equal(ui.renders(), before);
    assert.equal(control.requested, false);
});

test("the cancel button requests server cancellation and stays pending until task completion", async () => {
    let sent = 0;
    const control = new BatchCancellation(async () => {
        sent++;
    });
    await control.bindJob({
        serverUrl: "http://localhost:8890",
        taskId: "active",
    });
    const ui = popupHarness(control);
    const button = ui.dialog.buttons.get("pdf2zh-job-cancel");
    assert.equal(button.noClose, true);
    await button.callback();
    assert.equal(sent, 1);
    assert.equal(button.disabled, true);
    ui.popup.complete(0, 0, 1);
    assert.equal(button.disabled, true);
    assert.equal(ui.dialog.window.closed, false);
});
