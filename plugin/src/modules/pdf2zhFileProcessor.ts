import { PDF2zhHelperFactory } from "./pdf2zhHelper";
import { JobProgressUpdate, ServerConfig } from "./pdf2zhTypes";
import { BatchCancellation, JobCancelledError } from "./jobCancellation";

export class FileProcessor {
    private static instance: FileProcessor;
    private eventListeners: Array<(event: string, data: any) => void> = [];

    static getInstance(): FileProcessor {
        if (!FileProcessor.instance) {
            FileProcessor.instance = new FileProcessor();
        }
        return FileProcessor.instance;
    }
    addEventListener(listener: (event: string, data: any) => void) {
        this.eventListeners.push(listener);
        return () => {
            this.eventListeners = this.eventListeners.filter(
                (candidate) => candidate !== listener,
            );
        };
    }

    private emit(event: string, data: any) {
        [...this.eventListeners].forEach((listener) => {
            try {
                listener(event, data);
            } catch (error) {
                ztoolkit.log(`事件监听器错误:`, error);
            }
        });
    }

    // 批量处理文件
    async processBatch(
        tasks: Array<{
            fileName: string;
            item: Zotero.Item;
            config: ServerConfig;
            endpoint: string;
        }>,
        onProgress?: (update: JobProgressUpdate) => void,
        cancellation?: BatchCancellation,
    ): Promise<{
        total: number;
        succeeded: number;
        failed: number;
        cancelled: number;
    }> {
        this.emit("batchStarted", { totalTasks: tasks.length });
        let succeeded = 0;
        let failed = 0;
        let cancelled = 0;
        for (let index = 0; index < tasks.length; index++) {
            const task = tasks[index];
            const report = (
                update: Omit<JobProgressUpdate, "current" | "total">,
            ) => {
                onProgress?.({
                    ...update,
                    current: index + 1,
                    total: tasks.length,
                });
            };
            try {
                cancellation?.checkpoint();
                await PDF2zhHelperFactory.processSingleFile(
                    { ...task, cancellation },
                    report,
                );
                succeeded++;
            } catch (error) {
                if (error instanceof JobCancelledError) {
                    cancelled = tasks.length - index;
                    for (
                        let remaining = index;
                        remaining < tasks.length;
                        remaining++
                    ) {
                        onProgress?.({
                            phase: "file-cancelled",
                            fileName: tasks[remaining].fileName,
                            endpoint: tasks[remaining].endpoint,
                            current: remaining + 1,
                            total: tasks.length,
                        });
                    }
                    break;
                }
                failed++;
            }
        }
        this.emit("batchCompleted", {
            total: tasks.length,
            succeeded,
            failed,
            cancelled,
        });
        return { total: tasks.length, succeeded, failed, cancelled };
    }
}
