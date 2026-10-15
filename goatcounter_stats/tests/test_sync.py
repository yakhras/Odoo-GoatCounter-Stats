# Copyright 2026 Yaser Akhras
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import json
import os
from datetime import date
from pathlib import Path
from unittest.mock import patch

import requests

from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, new_test_user, tagged

DATA = Path(__file__).parent / 'data'
SYNC = 'odoo.addons.goatcounter_stats.models.goatcounter_sync'
DAY = date(2026, 10, 15)  # the recorded samples in tests/data hold this day


class FakeResponse:
    def __init__(self, payload, status=200):
        self.status_code = status
        self._payload = payload
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


def sample(name):
    return json.loads((DATA / f'{name}.json').read_text())


def recorded_api(url, params=None, headers=None, timeout=None):
    """Answers every endpoint the sync calls with the samples recorded from the real API."""
    return FakeResponse(sample(url.rsplit('/', 1)[-1]))


@tagged('post_install', '-at_install')
class TestGoatcounterSync(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env['ir.config_parameter'].sudo().set_param('goatcounter_stats.site_code', 'yaserakhras')
        cls.sync = cls.env['goatcounter.sync']
        cls.Total = cls.env['goatcounter.total']
        cls.Hit = cls.env['goatcounter.hit']
        cls.Dimension = cls.env['goatcounter.dimension']

    def setUp(self):
        super().setUp()
        for patcher in (patch.dict(os.environ, {'GOAT_COUNTER_KEY': 'test-key'}),
                        patch(f'{SYNC}.time.sleep')):
            patcher.start()
            self.addCleanup(patcher.stop)

    def run_sync(self, api=recorded_api):
        with patch(f'{SYNC}.requests.get', side_effect=api) as get:
            ok = self.sync.run_sync(DAY, DAY)
        return ok, get

    def last_result(self):
        return self.env['ir.config_parameter'].sudo().get_param('goatcounter_stats.last_result')

    def test_sync_stores_recorded_day(self):
        ok, get = self.run_sync()
        self.assertTrue(ok, self.last_result())
        self.assertTrue(self.last_result().startswith('OK'))

        self.assertEqual([(t.date, t.count) for t in self.Total.search([])], [(DAY, 6)])

        pages = self.Hit.search([('is_event', '=', False)])
        self.assertEqual(sorted(pages.mapped('path')),
                         ['/', '/404.html', '/about', '/erp', '/erp/stock_valuation'])
        self.assertEqual(set(pages.mapped('count')), {1})
        clicks = self.Hit.search([('is_event', '=', True)])
        self.assertEqual([(c.path, c.count) for c in clicks], [('sector-erp', 1)])

        rows = {(d.kind, d.name): d.count for d in self.Dimension.search([])}
        self.assertEqual(rows, {
            ('toprefs', '(direct / unknown)'): 2,  # empty referrer name
            ('locations', 'Turkey'): 5,
            ('locations', 'Brazil'): 1,
            ('browsers', 'Chrome'): 6,
            ('systems', 'Windows'): 6,
            ('sizes', 'desktop'): 6,  # empty name falls back to the id; zero counts skipped
        })

        _args, kwargs = get.call_args
        self.assertEqual(kwargs['headers']['Authorization'], 'Bearer test-key')
        self.assertEqual(kwargs['params']['start'], '2026-10-15T00:00:00+03:00')  # site timezone

    def test_resync_does_not_duplicate(self):
        self.run_sync()
        before = (self.Total.search_count([]), self.Hit.search_count([]), self.Dimension.search_count([]))
        self.run_sync()
        after = (self.Total.search_count([]), self.Hit.search_count([]), self.Dimension.search_count([]))
        self.assertEqual(before, after)
        self.assertEqual(sum(self.Total.search([]).mapped('count')), 6)

    def test_days_outside_range_are_ignored(self):
        self.run_sync()  # the API also returns 2026-10-16 for a one-day window
        self.assertFalse(self.Hit.search([('date', '!=', DAY)]))
        self.assertFalse(self.Total.search([('date', '!=', DAY)]))

    def test_hits_pagination_uses_exclude_paths(self):
        first = sample('hits')
        second = {'hits': [first['hits'].pop()], 'total': 1, 'more': False}
        first['more'] = True
        pages = iter([first, second])
        sent = []

        def api(url, params=None, **kwargs):
            if url.endswith('/stats/hits'):
                sent.append(dict(params))
                return FakeResponse(next(pages))
            return recorded_api(url)

        ok, _get = self.run_sync(api)
        self.assertTrue(ok, self.last_result())
        self.assertNotIn('exclude_paths', sent[0])
        self.assertEqual(sent[1]['exclude_paths'], ','.join(str(h['path_id']) for h in first['hits']))
        self.assertEqual(self.Hit.search_count([]), 6)

    def test_api_error_keeps_old_rows_and_is_reported(self):
        self.run_sync()

        def unauthorized(url, **kwargs):
            if url.endswith('/me'):
                return recorded_api(url)
            return FakeResponse({'error': 'invalid token'}, status=401)

        ok, _get = self.run_sync(unauthorized)
        self.assertFalse(ok)
        self.assertIn('HTTP 401', self.last_result())
        self.assertIn('invalid token', self.last_result())
        self.assertEqual(self.Total.search([]).mapped('count'), [6])

    def test_missing_key_is_reported(self):
        with patch.dict(os.environ, {}, clear=True):
            ok, get = self.run_sync()
        self.assertFalse(ok)
        self.assertIn('GOAT_COUNTER_KEY', self.last_result())
        get.assert_not_called()

    def test_cron_never_raises(self):
        down = requests.ConnectionError('network down')
        with patch(f'{SYNC}.requests.get', side_effect=down), patch(f'{SYNC}.requests.post', side_effect=down):
            self.sync._cron_sync()
        self.assertIn('network down', self.last_result())
        visit_result = self.env['ir.config_parameter'].sudo().get_param('goatcounter_stats.visit_result')
        self.assertIn('network down', visit_result)

    def test_stats_are_admin_only(self):
        user = new_test_user(self.env, login='gc_plain_user', groups='base.group_user')
        for model in ('goatcounter.total', 'goatcounter.hit', 'goatcounter.dimension'):
            with self.assertRaises(AccessError):
                self.env[model].with_user(user).search([])
        menu = self.env.ref('goatcounter_stats.menu_goatcounter_root')
        self.assertEqual(menu.group_ids, self.env.ref('base.group_system'))
