# Copyright 2026 Yaser Akhras
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import os
from datetime import timedelta

from odoo import api, fields, models

from .goatcounter_stats import DIMENSION_KINDS
from .goatcounter_sync import TOKEN_ENV

TOP = 10


class GoatcounterDashboard(models.AbstractModel):
    """Data for the Website Stats dashboard (client action goatcounter_stats.dashboard).

    Reads the goatcounter.* models as the current user, so their access rules
    (admins only) apply here too.
    """
    _name = 'goatcounter.dashboard'
    _description = "GoatCounter dashboard"

    def _period(self, days):
        today = fields.Date.context_today(self)
        if days:
            return today - timedelta(days=days - 1), today
        first = self.env['goatcounter.hit'].search([], order='date asc', limit=1).date
        return (first or today), today

    def _sum(self, model, domain):
        [(total,)] = self.env[model]._read_group(domain, aggregates=['count:sum'])
        return total or 0

    def _top(self, model, domain, groupby, limit=TOP):
        rows = self.env[model]._read_group(domain, [groupby], ['count:sum'], order='count:sum desc')
        return [{'name': name, 'count': count} for name, count in rows[:limit] if count]

    @api.model
    def get_dashboard_data(self, days=30):
        days = int(days or 0)
        date_from, date_to = self._period(days)
        span = (date_to - date_from).days + 1
        prev_from, prev_to = date_from - timedelta(days=span), date_from - timedelta(days=1)
        in_period = [('date', '>=', date_from), ('date', '<=', date_to)]
        in_prev = [('date', '>=', prev_from), ('date', '<=', prev_to)]
        pages, events = [('is_event', '=', False)], [('is_event', '=', True)]

        # Daily series with every day of the period, zeros included.
        series = {date_from + timedelta(days=i): [0, 0] for i in range(span)}
        for day, is_event, count in self.env['goatcounter.hit']._read_group(
                in_period, ['date:day', 'is_event'], ['count:sum']):
            series[day][int(is_event)] += count

        titles = dict(self.env['goatcounter.hit']._read_group(in_period + pages, ['path'], ['title:max']))
        top_pages = self._top('goatcounter.hit', in_period + pages, 'path')
        for page in top_pages:
            page['title'] = titles.get(page['name']) or ''

        sources = {}
        for kind, label in DIMENSION_KINDS:
            domain = in_period + [('kind', '=', kind)]
            sources[kind] = {'label': label,
                             'total': self._sum('goatcounter.dimension', domain),
                             'rows': self._top('goatcounter.dimension', domain, 'name', limit=8)}

        moment_from = fields.Datetime.to_datetime(date_from)
        visits = self.env['goatcounter.visit'].search([('start', '>=', moment_from)], limit=10)
        latest_visits = [{
            'id': v.id,
            'start': fields.Datetime.context_timestamp(self, v.start).strftime('%Y-%m-%d %H:%M') if v.start else '',
            'country': v.country_id.name or v.location or '',
            'browser': ' / '.join(filter(None, [v.browser, v.system])),
            'journey': v.journey or '',
            'clicks': v.click_count,
        } for v in visits]

        params = self.env['ir.config_parameter'].sudo()
        return {
            'latest_visits': latest_visits,
            'visit_count': self.env['goatcounter.visit'].search_count([('start', '>=', moment_from)]),
            'visit_result': params.get_param('goatcounter_stats.visit_result') or '',
            'date_from': fields.Date.to_string(date_from),
            'date_to': fields.Date.to_string(date_to),
            'span': span,
            'kpis': {
                'pageviews': self._sum('goatcounter.hit', in_period + pages),
                'pageviews_prev': self._sum('goatcounter.hit', in_prev + pages),
                'clicks': self._sum('goatcounter.hit', in_period + events),
                'clicks_prev': self._sum('goatcounter.hit', in_prev + events),
                'pages': len(self.env['goatcounter.hit']._read_group(in_period + pages, ['path'])),
                'countries': len(self.env['goatcounter.dimension']._read_group(
                    in_period + [('kind', '=', 'locations')], ['name'])),
            },
            'daily': [{'date': fields.Date.to_string(day), 'pageviews': pv, 'clicks': cl}
                      for day, (pv, cl) in sorted(series.items())],
            'top_pages': top_pages,
            'clicks': self._top('goatcounter.hit', in_period + events, 'path'),
            'sources': sources,
            'last_sync': params.get_param('goatcounter_stats.last_sync') or '',
            'last_result': params.get_param('goatcounter_stats.last_result') or '',
            'key_found': bool(os.environ.get(TOKEN_ENV)),
        }

    @api.model
    def action_sync_now(self):
        """Dashboard button: same as the hourly cron. Admins only."""
        if not self.env.user.has_group('base.group_system'):
            return False
        return self.env['goatcounter.sync']._cron_sync()
