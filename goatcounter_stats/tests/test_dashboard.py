# Copyright 2026 Yaser Akhras
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from datetime import date
from unittest.mock import patch

from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, new_test_user, tagged

TODAY = date(2026, 10, 20)


@tagged('post_install', '-at_install')
class TestGoatcounterDashboard(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        for model in ('goatcounter.hit', 'goatcounter.dimension', 'goatcounter.total'):
            cls.env[model].search([]).unlink()
        hit = cls.env['goatcounter.hit']
        hit.create([
            # current 7-day period: 2026-10-14 .. 2026-10-20
            {'date': date(2026, 10, 15), 'path': '/', 'title': 'Home', 'count': 4},
            {'date': date(2026, 10, 18), 'path': '/', 'title': 'Home', 'count': 2},
            {'date': date(2026, 10, 18), 'path': '/erp', 'title': 'ERP', 'count': 3},
            {'date': date(2026, 10, 18), 'path': 'sector-erp', 'is_event': True, 'count': 2},
            # previous 7-day period: 2026-10-07 .. 2026-10-13
            {'date': date(2026, 10, 10), 'path': '/', 'title': 'Home', 'count': 6},
            {'date': date(2026, 10, 10), 'path': 'social-github', 'is_event': True, 'count': 1},
        ])
        cls.env['goatcounter.dimension'].create([
            {'date': date(2026, 10, 15), 'kind': 'locations', 'name': 'Turkey', 'count': 5},
            {'date': date(2026, 10, 18), 'kind': 'locations', 'name': 'Turkey', 'count': 2},
            {'date': date(2026, 10, 18), 'kind': 'locations', 'name': 'Brazil', 'count': 3},
            {'date': date(2026, 10, 10), 'kind': 'locations', 'name': 'Germany', 'count': 9},
        ])
        cls.Dashboard = cls.env['goatcounter.dashboard']

    def data(self, days):
        with patch('odoo.fields.Date.context_today', return_value=TODAY):
            return self.Dashboard.get_dashboard_data(days)

    def test_kpis_and_previous_period(self):
        data = self.data(7)
        self.assertEqual((data['date_from'], data['date_to'], data['span']), ('2026-10-14', '2026-10-20', 7))
        self.assertEqual(data['kpis'], {
            'pageviews': 9, 'pageviews_prev': 6,
            'clicks': 2, 'clicks_prev': 1,
            'pages': 2, 'countries': 2,
        })

    def test_daily_series_has_every_day(self):
        daily = self.data(7)['daily']
        self.assertEqual(len(daily), 7)
        self.assertEqual(daily[0], {'date': '2026-10-14', 'pageviews': 0, 'clicks': 0})
        self.assertEqual(daily[1], {'date': '2026-10-15', 'pageviews': 4, 'clicks': 0})
        self.assertEqual(daily[4], {'date': '2026-10-18', 'pageviews': 5, 'clicks': 2})

    def test_rankings_and_sources(self):
        data = self.data(7)
        self.assertEqual(data['top_pages'], [{'name': '/', 'count': 6, 'title': 'Home'},
                                             {'name': '/erp', 'count': 3, 'title': 'ERP'}])
        self.assertEqual(data['clicks'], [{'name': 'sector-erp', 'count': 2}])
        countries = data['sources']['locations']
        self.assertEqual(countries['total'], 10)
        self.assertEqual(countries['rows'], [{'name': 'Turkey', 'count': 7}, {'name': 'Brazil', 'count': 3}])
        self.assertEqual(data['sources']['toprefs']['rows'], [])

    def test_all_time_starts_at_first_data(self):
        data = self.data(0)
        self.assertEqual(data['date_from'], '2026-10-10')
        self.assertEqual(data['kpis']['pageviews'], 15)
        self.assertEqual(data['kpis']['countries'], 3)

    def test_dashboard_is_admin_only(self):
        user = new_test_user(self.env, login='gc_dash_user', groups='base.group_user')
        with self.assertRaises(AccessError):
            self.Dashboard.with_user(user).get_dashboard_data(30)
        self.assertFalse(self.Dashboard.with_user(user).action_sync_now())
