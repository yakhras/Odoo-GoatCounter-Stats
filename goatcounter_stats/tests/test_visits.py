# Copyright 2026 Yaser Akhras
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import gzip
import json
import os
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from odoo.tests import TransactionCase, tagged

DATA = Path(__file__).parent / 'data'
SYNC = 'odoo.addons.goatcounter_stats.models.goatcounter_sync'
EXPORT = (DATA / 'export.csv').read_bytes()


class FakeResponse:
    def __init__(self, status=200, payload=None, content=b''):
        self.status_code = status
        self._payload = payload or {}
        self.content = content or json.dumps(self._payload).encode()
        self.text = self.content.decode('utf-8', 'replace')

    def json(self):
        return self._payload


@tagged('post_install', '-at_install')
class TestGoatcounterVisits(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env['goatcounter.visit'].search([]).unlink()
        cls.params = cls.env['ir.config_parameter'].sudo()
        cls.params.set_param('goatcounter_stats.site_code', 'yaserakhras')
        cls.params.set_param('goatcounter_stats.last_hit_id', False)
        cls.params.set_param('goatcounter_stats.export_id', False)
        cls.sync = cls.env['goatcounter.sync']
        cls.Visit = cls.env['goatcounter.visit']

    def setUp(self):
        super().setUp()
        self.posted = []
        for patcher in (patch.dict(os.environ, {'GOAT_COUNTER_KEY': 'test-key'}),
                        patch(f'{SYNC}.time.sleep')):
            patcher.start()
            self.addCleanup(patcher.stop)

    def api(self, export=EXPORT, post_status=200, download_status=200):
        def post(url, json=None, **kwargs):
            self.posted.append(json)
            return FakeResponse(post_status, {'id': 77} if post_status == 200 else {'error': 'rate limited'})

        def get(url, **kwargs):
            if url.endswith('/download'):
                return FakeResponse(download_status, content=gzip.compress(export))
            if url.endswith('/export/77'):
                return FakeResponse(payload={'id': 77, 'last_hit_id': 1234})
            return FakeResponse(404, {'error': 'unexpected ' + url})

        return patch(f'{SYNC}.requests.post', side_effect=post), patch(f'{SYNC}.requests.get', side_effect=get)

    def run_import(self, **kwargs):
        post, get = self.api(**kwargs)
        with post, get:
            ok = self.sync.run_visit_sync()
        return ok, self.params.get_param('goatcounter_stats.visit_result')

    def test_visit_journey_from_brazil(self):
        ok, result = self.run_import()
        self.assertTrue(ok, result)
        self.assertEqual(result, 'OK: 2 new visits, 5 new page views/clicks.')  # the bot row is skipped

        brazil = self.Visit.search([('session', '=', 'sess-brazil')])
        self.assertEqual(brazil.country_id, self.env.ref('base.br'))
        self.assertEqual((brazil.browser, brazil.system, brazil.location), ('Chrome 141', 'Windows 11', 'BR-SP'))
        self.assertTrue(brazil.first_visit)
        # in time order, whatever the CSV order; the click is starred
        self.assertEqual(brazil.journey, '/ → ★sector-erp → /erp → /erp/stock_valuation')
        self.assertEqual((brazil.pageview_count, brazil.click_count), (3, 1))
        self.assertEqual(brazil.start, datetime(2026, 10, 15, 12, 2, 10))
        self.assertEqual(brazil.end, datetime(2026, 10, 15, 12, 4, 30))

        turkey = self.Visit.search([('session', '=', 'sess-turkey')])
        self.assertEqual((turkey.country_id, turkey.referrer, turkey.journey),
                         (self.env.ref('base.tr'), 'linkedin.com', '/about'))
        self.assertFalse(self.Visit.search([('session', '=', 'sess-bot')]))

    def test_incremental_import(self):
        self.run_import()
        self.assertEqual(self.posted, [{}])  # first export: everything
        self.assertEqual(self.params.get_param('goatcounter_stats.last_hit_id'), '1234')
        self.assertFalse(self.params.get_param('goatcounter_stats.export_id'))

        later = EXPORT.decode().splitlines()[0] + '\n' + \
            '/linux,Linux,false,UA,Chrome 141,Windows 11,sess-brazil,0,,o,"1920,1080,1",BR-SP,false,2026-10-15T12:06:00Z\n'
        ok, result = self.run_import(export=EXPORT + later.split('\n', 1)[1].encode())
        self.assertTrue(ok, result)
        self.assertEqual(self.posted[-1], {'start_from_hit_id': 1235})
        self.assertEqual(result, 'OK: 0 new visits, 1 new page views/clicks.')  # re-sent rows not duplicated
        brazil = self.Visit.search([('session', '=', 'sess-brazil')])
        self.assertTrue(brazil.journey.endswith('→ /linux'))
        self.assertEqual(self.Visit.search_count([]), 2)

    def test_hourly_export_limit_is_a_wait_not_an_error(self):
        ok, result = self.run_import(post_status=429)
        self.assertTrue(ok)
        self.assertTrue(result.startswith('Waiting'), result)

    def test_export_still_running_is_kept_for_next_hour(self):
        ok, result = self.run_import(download_status=202)
        self.assertTrue(ok)
        self.assertTrue(result.startswith('Waiting'), result)
        self.assertEqual(self.params.get_param('goatcounter_stats.export_id'), '77')
        ok, result = self.run_import()  # next hour: same export is downloaded, no new POST
        self.assertEqual(len(self.posted), 1)
        self.assertTrue(result.startswith('OK'), result)

    def test_missing_permission_is_reported(self):
        ok, result = self.run_import(post_status=403)
        self.assertFalse(ok)
        self.assertIn('HTTP 403', result)
        self.assertFalse(self.params.get_param('goatcounter_stats.export_id'))
