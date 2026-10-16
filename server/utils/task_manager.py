import json
import os
import threading
import time
import signal
import subprocess
from datetime import datetime


# DEBUG_PROGRESS_LOG_PATH = os.path.join(
#     os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
#     "_debug_progress.log",
# )
# _DEBUG_LOG_LOCK = threading.Lock()


# def _debug_progress_log(stage, **fields):
#     try:
#         ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
#         parts = []
#         for key in sorted(fields.keys()):
#             value = str(fields[key]).replace("\r", "\\r").replace("\n", "\\n")
#             if len(value) > 800:
#                 value = value[:800] + "..."
#             parts.append(f"{key}={value}")
#         line = f"[{ts}] [{stage}] " + " ".join(parts)
#         with _DEBUG_LOG_LOCK:
#             with open(DEBUG_PROGRESS_LOG_PATH, "a", encoding="utf-8", errors="replace") as fp:
#                 fp.write(line + "\n")
#     except Exception:
#         pass


class TaskCancelledError(Exception):
    pass


def stop_owned_process(process):
    """Stop only a subprocess registered by this server and its children."""
    if process.poll() is not None:
        return
    if os.name == 'nt':
        result = subprocess.run(
            ['taskkill', '/PID', str(process.pid), '/T', '/F'],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if result.returncode and process.poll() is None:
            process.terminate()
    else:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        if os.name != 'nt':
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        else:
            process.kill()
        process.wait(timeout=3)


class TaskManager:
    def __init__(self):
        self.active_tasks = {}
        self.lock = threading.Lock()
        self.progress_history = []
        self._processes = {}
        self._cancel_events = {}

    @staticmethod
    def _task_snapshot(task_id, task):
        snapshot = {
            "taskId": task_id,
            "fileName": task.get("fileName"),
            "active": task.get("active"),
            "progress": task.get("progress"),
            "status": task.get("status"),
            "message": task.get("message"),
            "engine": task.get("engine"),
            "service": task.get("service"),
        }
        return json.dumps(snapshot, ensure_ascii=False, sort_keys=True)

    def add_task(self, task_id, info):
        with self.lock:
            self.active_tasks[task_id] = info
            self._cancel_events[task_id] = threading.Event()
            # _debug_progress_log("TASK_ADD", task=self._task_snapshot(task_id, self.active_tasks[task_id]))

    def update_task(self, task_id, updates):
        with self.lock:
            if task_id in self.active_tasks:
                if self.active_tasks[task_id].get('cancelRequested') or self.active_tasks[task_id].get('finished'):
                    return
                self.active_tasks[task_id].update(updates)
                # _debug_progress_log(
                #     "TASK_UPDATE",
                #     updates=json.dumps(updates, ensure_ascii=False, sort_keys=True),
                #     task=self._task_snapshot(task_id, self.active_tasks[task_id]),
                # )

    def complete_task(self, task_id, status, message=None, file_list=None, error=None, file_paths=None, output_dir=None, result=None):
        with self.lock:
            if task_id not in self.active_tasks:
                return
            task = self.active_tasks[task_id]
            # Client disconnect after a successful translate can raise while
            # returning HTTP; do not overwrite a completed success as failure.
            if task.get('finished'):
                return
            if task.get('cancelRequested'):
                status, message = 'cancelled', '任务已取消'
                file_list = file_paths = output_dir = result = error = None
            task["active"] = False
            task["finished"] = True
            task["status"] = "完成" if status == "success" else "已取消" if status == 'cancelled' else "失败"
            task['cancelled'] = status == 'cancelled'
            task["progress"] = 100 if status == "success" else task.get("progress", 0)
            if message:
                task["message"] = message
            task["endTime"] = datetime.now().isoformat()
            if file_list:
                task["fileList"] = list(file_list)
            if file_paths:
                task["filePaths"] = list(file_paths)
            if output_dir:
                task["outputDir"] = output_dir
            if result:
                task["result"] = result
            if error:
                task["error"] = str(error)

            history_item = {
                "taskId": task_id,
                "fileName": task.get("fileName"),
                "status": "success" if status == "success" else "cancelled" if status == 'cancelled' else "failed",
                "cancelled": status == 'cancelled',
                "finished": True,
                "active": False,
                "engine": task.get("engine"),
                "service": task.get("service"),
                "startTime": task.get("startTime"),
                "endTime": task.get("endTime"),
                "config": task.get("config"),
            }
            if file_list:
                history_item["fileList"] = list(file_list)
            if file_paths:
                history_item["filePaths"] = list(file_paths)
            if output_dir:
                history_item["outputDir"] = output_dir
            if result:
                history_item["result"] = result
            if error:
                history_item["error"] = str(error)

            self.progress_history.insert(0, history_item)
            if len(self.progress_history) > 200:
                self.progress_history = self.progress_history[:200]

            threading.Thread(target=self._delayed_remove, args=(task_id,), daemon=True).start()

    def check_cancelled(self, task_id):
        if task_id is None:
            return
        with self.lock:
            event = self._cancel_events.get(task_id)
        if event is not None and event.is_set():
            raise TaskCancelledError('任务已取消')

    def register_process(self, task_id, process):
        if task_id is None:
            return
        with self.lock:
            self._processes[task_id] = process
            event = self._cancel_events.get(task_id)
            cancelled = event is not None and event.is_set()
        if cancelled:
            try:
                stop_owned_process(process)
            finally:
                self.unregister_process(task_id, process)
            raise TaskCancelledError('任务已取消')

    def unregister_process(self, task_id, process):
        with self.lock:
            if self._processes.get(task_id) is process:
                self._processes.pop(task_id, None)

    def request_cancel(self, task_id):
        with self.lock:
            task = self.active_tasks.get(task_id)
            if task is None:
                return 'not_found'
            if task.get('finished'):
                return 'finished'
            event = self._cancel_events[task_id]
            task.update(cancelRequested=True, status='正在取消', message='正在停止翻译任务…')
            event.set()
            process = self._processes.get(task_id)
        if process is not None:
            stop_owned_process(process)
        return 'cancelling'

    def get_active_tasks_list(self):
        with self.lock:
            tasks = list(self.active_tasks.values())
            return tasks

    def get_history(self):
        with self.lock:
            return list(self.progress_history)

    def _delayed_remove(self, task_id):
        time.sleep(30)
        with self.lock:
            if task_id in self.active_tasks:
                # _debug_progress_log("TASK_REMOVE", task_id=task_id)
                del self.active_tasks[task_id]
                self._cancel_events.pop(task_id, None)
                self._processes.pop(task_id, None)


# global singleton
task_manager = TaskManager()
