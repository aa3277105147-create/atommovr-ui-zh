"""Regression checks for asynchronous view updates and preset snapshots."""
import copy
import unittest
from unittest.mock import patch
import app
from simulator import DEFAULT_CONFIG

class AppStateTests(unittest.TestCase):
    def setUp(self):
        self.values = [DEFAULT_CONFIG[k] for k in app.KEYS]
        self.config = app.as_config(self.values)
        self.result = {'config':copy.deepcopy(self.config), 'summary':{'status':'success'}}

    def test_delayed_matching_preview_keeps_existing_player(self):
        with patch.object(app,'show_preview') as preview:
            player, layout, status = app.refresh_preview(*self.values, None, self.result)
        preview.assert_not_called()
        self.assertEqual(player, app.gr.skip())
        self.assertIn('仿真已计算',status)

    def test_new_parameters_generate_preview(self):
        values = self.values.copy(); values[app.KEYS.index('pickup_time_us')]=10
        with patch.object(app,'show_preview',return_value=('p','l','s')) as preview:
            self.assertEqual(app.refresh_preview(*values,None,self.result),('p','l','s'))
        preview.assert_called_once()

    def test_matching_failed_result_stays_failed(self):
        self.result['summary']={'status':'blocked','message':'保留安全完成步骤'}
        status = app.refresh_preview(*self.values,None,self.result)[2]
        self.assertIn('保留安全完成步骤',status)
        self.assertNotIn('仿真已计算',status)

    def test_preset_physics_change_marks_both_snapshots_stale_even_same_initial(self):
        compared={'config':self.config,'initial_matrix':[[1]],'status':'complete'}
        benchmarked={'config':self.config,'trials':5,'message':'统计完成'}
        values = app.preset('loss')
        notes = app.refresh_notes(*values,None,5,compared,benchmarked)
        self.assertIn('参数已修改',notes[0]); self.assertIn('设置已修改',notes[1])

    def test_manual_edit_event_with_extended_physical_controls(self):
        config = dict(DEFAULT_CONFIG, n=4, target_size=1, initial_mode='manual', pickup_time_us=10)
        values = [config[k] for k in app.KEYS]
        matrix = [[0]*4 for _ in range(4)]; matrix[3][3] = 1
        event = app.gr.EventData(None, {'matrix':matrix})
        result, layout, status = app.edit_initial(*values, {'matrix':[[0]*4 for _ in range(4)]}, event)
        self.assertEqual(result['summary']['initial_count'], 1)
        self.assertEqual(result['config']['pickup_time_us'], 10)
        self.assertEqual(layout['matrix'], matrix)

    def test_server_settings_keep_local_defaults(self):
        with patch.dict(app.os.environ, {}, clear=True):
            self.assertEqual(app.server_settings(), ('127.0.0.1', None))

    def test_server_settings_use_render_port(self):
        with patch.dict(app.os.environ, {'GRADIO_SERVER_NAME':'0.0.0.0', 'PORT':'10000'}, clear=True):
            self.assertEqual(app.server_settings(), ('0.0.0.0', 10000))

    def test_server_settings_prefer_explicit_gradio_port(self):
        environment = {'GRADIO_SERVER_PORT':'7860', 'PORT':'10000'}
        with patch.dict(app.os.environ, environment, clear=True):
            self.assertEqual(app.server_settings(), ('127.0.0.1', 7860))

    def test_server_settings_reject_invalid_port(self):
        with patch.dict(app.os.environ, {'PORT':'0'}, clear=True):
            with self.assertRaisesRegex(ValueError, 'PORT'):
                app.server_settings()

    def test_public_queue_limit_and_local_default(self):
        with patch.dict(app.os.environ, {}, clear=True):
            self.assertEqual(app.queue_max_size(), 32)
        with patch.dict(app.os.environ, {'ATOMMOVR_QUEUE_MAX_SIZE':'8'}, clear=True):
            self.assertEqual(app.queue_max_size(), 8)

if __name__=='__main__': unittest.main()
