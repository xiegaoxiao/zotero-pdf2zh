import io
import subprocess
import sys
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest.mock import Mock, patch

import server
from utils import execute
from utils.task_manager import TaskManager, TaskCancelledError


class TaskCancellationTest(unittest.TestCase):
    def setUp(self):
        self.manager = TaskManager()
        self.manager.add_task('first', {'taskId': 'first', 'active': True, 'finished': False})

    def test_cancel_before_spawn_blocks_the_task(self):
        self.assertEqual(self.manager.request_cancel('first'), 'cancelling')
        with self.assertRaises(TaskCancelledError):
            self.manager.check_cancelled('first')

    def test_cancelling_stops_only_the_registered_job(self):
        first, other = Mock(), Mock()
        self.manager.add_task('other', {'taskId': 'other', 'active': True})
        self.manager.register_process('first', first)
        self.manager.register_process('other', other)
        with patch('utils.task_manager.stop_owned_process') as stop:
            self.manager.request_cancel('first')
        stop.assert_called_once_with(first)
        self.manager.check_cancelled('other')

    def test_cancellation_arriving_before_registration_stops_new_child(self):
        self.manager.request_cancel('first')
        process = Mock()
        with patch('utils.task_manager.stop_owned_process') as stop:
            with self.assertRaises(TaskCancelledError):
                self.manager.register_process('first', process)
        stop.assert_called_once_with(process)
        self.assertNotIn('first', self.manager._processes)

    def test_cancelled_task_cannot_be_overwritten_by_progress_or_success(self):
        self.manager.request_cancel('first')
        self.manager.update_task('first', {'status': '翻译中'})
        self.assertEqual(self.manager.active_tasks['first']['status'], '正在取消')
        self.manager.complete_task('first', 'success', file_list=['must-not-import.pdf'])
        self.manager.complete_task('first', 'failed', error='late exception')
        task = self.manager.active_tasks['first']
        self.assertEqual(task['status'], '已取消')
        self.assertTrue(task['finished'])
        self.assertTrue(task['cancelled'])
        self.assertNotIn('fileList', task)
        self.assertEqual(len(self.manager.get_history()), 1)
        self.assertEqual(self.manager.get_history()[0]['status'], 'cancelled')

    def test_finished_and_unknown_jobs_are_not_terminated(self):
        self.manager.complete_task('first', 'success')
        with patch('utils.task_manager.stop_owned_process') as stop:
            self.assertEqual(self.manager.request_cancel('first'), 'finished')
            self.assertEqual(self.manager.request_cancel('unknown'), 'not_found')
        stop.assert_not_called()

    def test_cancel_api_reports_acknowledgement_and_unknown_ids(self):
        translator = server.PDFTranslator(SimpleNamespace(enable_venv=False))
        with patch.object(server, 'task_manager', self.manager):
            client = translator.app.test_client()
            response = client.post('/api/tasks/first/cancel', json={})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json['status'], 'cancelling')
            self.assertEqual(client.post('/api/tasks/missing/cancel', json={}).status_code, 404)

    def test_cancelled_engine_exit_does_not_become_an_ordinary_failure(self):
        def exit_after_cancel(*_args):
            self.manager.request_cancel('first')
            raise subprocess.CalledProcessError(1, ['test-engine'])
        with patch.object(execute, 'task_manager', self.manager), \
             patch.object(execute, 'prepare_deepseek_runtime_command', side_effect=lambda cmd, env: cmd), \
             patch.object(execute, '_execute_with_pty', side_effect=exit_after_cancel), \
             patch.object(execute, '_execute_with_inherit', side_effect=exit_after_cancel), \
             redirect_stdout(io.StringIO()):
            with self.assertRaises(TaskCancelledError):
                execute.execute_with_progress(['test-engine'], 'first', SimpleNamespace(enable_venv=False), None)

    def test_real_owned_subprocess_is_stopped(self):
        process = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'], start_new_session=True)
        try:
            self.manager.register_process('first', process)
            self.manager.request_cancel('first')
            self.assertIsNotNone(process.poll())
        finally:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=5)


if __name__ == '__main__':
    unittest.main()
