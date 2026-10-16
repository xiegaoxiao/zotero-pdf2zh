export interface ActiveServerJob {
    serverUrl: string;
    taskId: string;
}

export class JobCancelledError extends Error {
    constructor() {
        super("Task cancelled");
        this.name = "JobCancelledError";
    }
}

export class BatchCancellation {
    requested = false;
    private activeJob?: ActiveServerJob;
    private pending?: Promise<void>;
    private cancelServerJob: (job: ActiveServerJob) => Promise<void>;
    private onError: (error: unknown) => void;

    constructor(
        cancelServerJob: (job: ActiveServerJob) => Promise<void>,
        onError: (error: unknown) => void = () => {},
    ) {
        this.cancelServerJob = cancelServerJob;
        this.onError = onError;
    }

    async request(): Promise<void> {
        this.requested = true;
        if (this.activeJob) await this.cancelActiveJob();
    }

    async bindJob(job: ActiveServerJob): Promise<void> {
        this.activeJob = job;
        if (this.requested) await this.cancelActiveJob();
    }

    clearJob(): void {
        this.activeJob = undefined;
    }

    checkpoint(): void {
        // While a server job is active, keep polling until it confirms its
        // terminal state. A local flag alone must not pretend the server stopped.
        if (this.requested && !this.activeJob) throw new JobCancelledError();
    }

    private async cancelActiveJob(): Promise<void> {
        if (this.pending) return this.pending;
        const job = this.activeJob;
        if (!job) return;
        this.pending = this.cancelServerJob(job)
            .catch((error) => {
                this.requested = false;
                this.onError(error);
            })
            .finally(() => {
                this.pending = undefined;
            });
        return this.pending;
    }
}
