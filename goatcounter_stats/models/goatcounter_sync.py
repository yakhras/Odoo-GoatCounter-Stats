# Copyright 2026 Yaser Akhras
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import csv
import gzip
import io
import logging
import os
import re
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests

from odoo import fields, models
from odoo.exceptions import UserError

from .goatcounter_stats import DIMENSION_KINDS

_logger = logging.getLogger(__name__)

TOKEN_ENV = 'GOAT_COUNTER_KEY'
TIMEOUT = 30
PAUSE = 0.3  # GoatCounter allows 4 API requests per second
PAGE_LIMIT = 100
EXPORT_POLLS = 10  # a small site's export is ready within seconds
EXPORT_WAIT = 2


class GoatcounterSync(models.AbstractModel):
    """Fetches statistics from the GoatCounter API (v0) into the goatcounter.* models.

    The API token is read from the GOAT_COUNTER_KEY environment variable of the
    Odoo process, so it is never stored in the database.
    """
    _name = 'goatcounter.sync'
    _description = "GoatCounter synchronisation"

    # ------------------------------------------------------------------ API

    def _base_url(self):
        code = self.env['ir.config_parameter'].sudo().get_str('goatcounter_stats.site_code')
        if not code:
            raise UserError(self.env._("Set the GoatCounter site code in Settings first."))
        return f"https://{code.strip()}.goatcounter.com/api/v0"

    def _request(self, method, path, params=None, body=None):
        token = os.environ.get(TOKEN_ENV)
        if not token:
            raise UserError(self.env._("%s not set in the Odoo container environment.", TOKEN_ENV))
        url = f"{self._base_url()}/{path}"
        headers = {'Authorization': f"Bearer {token}", 'Content-Type': 'application/json'}
        for attempt in range(2):
            if method == 'POST':
                response = requests.post(url, json=body or {}, headers=headers, timeout=TIMEOUT)
            else:
                response = requests.get(url, params=params, headers=headers, timeout=TIMEOUT)
            time.sleep(PAUSE)
            # The per-second limit clears quickly; the hourly export limit does not.
            if response.status_code == 429 and not attempt and path != 'export':
                time.sleep(2)
                continue
            return response

    def _get(self, path, params=None, method='GET', body=None):
        response = self._request(method, path, params, body)
        if response.status_code != 200:
            try:
                detail = response.json().get('error') or response.text
            except ValueError:
                detail = response.text
            raise UserError(self.env._("GoatCounter %(path)s returned HTTP %(status)s: %(detail)s",
                                       path=path, status=response.status_code, detail=str(detail)[:200]))
        return response.json()

    def _site_tz(self):
        """GoatCounter groups days in the user's timezone, e.g. 'TR.Europe/Istanbul'."""
        tz_name = (self._get('me').get('user', {}).get('settings', {}).get('timezone') or 'UTC')
        try:
            return ZoneInfo(tz_name.split('.', 1)[-1])
        except (KeyError, ValueError):
            return ZoneInfo('UTC')

    @staticmethod
    def _window(tz, date_from, date_to):
        start = datetime.combine(date_from, datetime.min.time(), tz)
        end = datetime.combine(date_to, datetime.max.time().replace(microsecond=0), tz)
        return {'start': start.isoformat(), 'end': end.isoformat()}

    # ------------------------------------------------------------------ fetch

    def _fetch_totals(self, tz, date_from, date_to):
        data = self._get('stats/total', self._window(tz, date_from, date_to))
        totals = {}
        for stat in data.get('stats', []):
            day = fields.Date.to_date(stat['day'])
            if date_from <= day <= date_to and stat.get('daily'):
                totals[day] = stat['daily']
        return totals

    def _fetch_hits(self, tz, date_from, date_to):
        """{(day, path, is_event): [title, count]}, following the exclude_paths pagination."""
        params = dict(self._window(tz, date_from, date_to), limit=PAGE_LIMIT)
        seen, hits = [], defaultdict(lambda: ['', 0])
        while True:
            if seen:
                params['exclude_paths'] = ','.join(map(str, seen))
            data = self._get('stats/hits', params)
            for hit in data.get('hits', []):
                seen.append(hit['path_id'])
                for stat in hit.get('stats', []):
                    day = fields.Date.to_date(stat['day'])
                    if date_from <= day <= date_to and stat.get('daily'):
                        row = hits[(day, hit['path'], bool(hit.get('event')))]
                        row[0] = row[0] or hit.get('title') or ''
                        row[1] += stat['daily']
            if not data.get('more') or not data.get('hits'):
                return hits

    def _fetch_dimension(self, tz, kind, day):
        """{name: count} for one kind on one day (these endpoints only return range totals)."""
        params = dict(self._window(tz, day, day), limit=PAGE_LIMIT, offset=0)
        counts = defaultdict(int)
        while True:
            data = self._get(f'stats/{kind}', params)
            for stat in data.get('stats', []):
                if stat.get('count'):
                    name = stat.get('name') or stat.get('id') or self.env._("(direct / unknown)")
                    counts[name] += stat['count']
            if not data.get('more') or not data.get('stats'):
                return counts
            params['offset'] += PAGE_LIMIT

    # ------------------------------------------------------------------ store

    def _sync_range(self, date_from, date_to):
        """Replace the stored rows of [date_from, date_to] with fresh API data."""
        tz = self._site_tz()
        totals = self._fetch_totals(tz, date_from, date_to)
        hits = self._fetch_hits(tz, date_from, date_to)
        dimensions = []
        day = date_from
        while day <= date_to:
            for kind, _label in DIMENSION_KINDS:
                for name, count in self._fetch_dimension(tz, kind, day).items():
                    dimensions.append({'date': day, 'kind': kind, 'name': name, 'count': count})
            day += timedelta(days=1)

        # Everything is fetched before anything is deleted, so an API error leaves the old rows.
        domain = [('date', '>=', date_from), ('date', '<=', date_to)]
        Total, Hit, Dimension = (self.env[m].sudo() for m in
                                 ('goatcounter.total', 'goatcounter.hit', 'goatcounter.dimension'))
        for model in (Total, Hit, Dimension):
            model.search(domain).unlink()
        Total.create([{'date': d, 'count': c} for d, c in totals.items()])
        Hit.create([{'date': d, 'path': p, 'is_event': e, 'title': t, 'count': c}
                    for (d, p, e), (t, c) in hits.items()])
        Dimension.create(dimensions)
        return sum(totals.values()), len(hits), len(dimensions)

    def run_sync(self, date_from, date_to):
        """Sync and record the outcome in Settings. Never raises, so the cron keeps running."""
        params = self.env['ir.config_parameter'].sudo()
        try:
            with self.env.cr.savepoint():
                visits, hit_rows, dim_rows = self._sync_range(date_from, date_to)
            result = self.env._("OK: %(from)s → %(to)s, %(visits)s visits, %(hits)s page/click rows, "
                                "%(dims)s source rows.", visits=visits, hits=hit_rows, dims=dim_rows,
                                **{'from': date_from, 'to': date_to})
            ok = True
        except (UserError, requests.RequestException, ValueError, KeyError) as error:
            _logger.warning("GoatCounter sync failed: %s", error)
            result = self.env._("Error: %s", error.args[0] if error.args else error)
            ok = False
        params.set_str('goatcounter_stats.last_sync', fields.Datetime.to_string(fields.Datetime.now()))
        params.set_str('goatcounter_stats.last_result', result)
        return ok

    # ------------------------------------------------------------------ visits (CSV export)

    def _download_export(self, export_id):
        """Poll the export briefly; returns the CSV text, or None while it is still running."""
        for _poll in range(EXPORT_POLLS):
            response = self._request('GET', f'export/{export_id}/download')
            if response.status_code == 200:
                content = response.content
                if content[:2] == b'\x1f\x8b':
                    content = gzip.decompress(content)
                return content.decode('utf-8-sig')
            if response.status_code != 202:
                raise UserError(self.env._("Export %(id)s download returned HTTP %(status)s.",
                                           id=export_id, status=response.status_code))
            time.sleep(EXPORT_WAIT)
        return None

    @staticmethod
    def _parse_export(text):
        """Rows of the export CSV with normalised keys (the first header carries the
        format version, e.g. '2Path')."""
        reader = csv.reader(io.StringIO(text))
        header = next(reader, None)
        if not header:
            return []
        keys = [re.sub(r'[^a-z]', '', h.lower()) for h in header]
        keys[0] = keys[0].lstrip('0123456789') or keys[0]
        return [dict(zip(keys, row)) for row in reader if row]

    @staticmethod
    def _parse_time(value):
        moment = datetime.fromisoformat(value.strip().replace('Z', '+00:00'))
        if moment.tzinfo:
            moment = moment.astimezone(timezone.utc).replace(tzinfo=None)
        return moment

    def _import_export_rows(self, rows):
        """Group rows by session into goatcounter.visit / goatcounter.pageview.
        Returns (new visits, new steps); rows already imported are skipped."""
        Visit = self.env['goatcounter.visit'].sudo()
        countries = {}
        sessions = defaultdict(list)
        for row in rows:
            if row.get('bot') not in (None, '', '0'):
                continue
            moment = self._parse_time(row['date'])
            session = row.get('session') or f"single-{row['date']}-{row.get('path')}"
            sessions[session].append((moment, row))

        new_visits = new_steps = 0
        for session, steps in sessions.items():
            steps.sort(key=lambda step: step[0])
            first = steps[0][1]
            visit = Visit.search([('session', '=', session)], limit=1)
            if not visit:
                location = (first.get('location') or '').strip()
                code = location.split('-')[0].upper()
                if code and code not in countries:
                    countries[code] = self.env['res.country'].search([('code', '=', code)], limit=1).id
                visit = Visit.create({
                    'session': session,
                    'location': location,
                    'country_id': countries.get(code) or False,
                    'browser': first.get('browser'),
                    'system': first.get('system'),
                    'screen_size': first.get('screensize'),
                    'referrer': first.get('referrer'),
                    'first_visit': (first.get('firstvisit') or '').lower() in ('true', '1'),
                })
                new_visits += 1
            known = {(s.datetime, s.path, s.is_event) for s in visit.pageview_ids}
            values = []
            for moment, row in steps:
                is_event = (row.get('event') or '').lower() in ('true', '1')
                key = (moment, row.get('path') or '/', is_event)
                if key not in known:
                    known.add(key)
                    values.append({'visit_id': visit.id, 'datetime': moment, 'path': key[1],
                                   'title': row.get('title'), 'is_event': is_event})
            self.env['goatcounter.pageview'].sudo().create(values)
            new_steps += len(values)
            times = [s.datetime for s in visit.pageview_ids]
            visit.write({'start': min(times), 'end': max(times)})
        return new_visits, new_steps

    def _sync_visits(self):
        params = self.env['ir.config_parameter'].sudo()
        export_id = params.get_str('goatcounter_stats.export_id')
        if not export_id:
            last_hit = int(params.get_str('goatcounter_stats.last_hit_id') or 0)
            # The API rejects a missing format, despite documenting csv as the default.
            # start_from_hit_id exports hits with an ID *greater than* it: pass the last imported one.
            body = {'format': 'csv'}
            if last_hit:
                body['start_from_hit_id'] = last_hit
            response = self._request('POST', 'export', body=body)
            if response.status_code == 429:
                return self.env._("Waiting: GoatCounter allows one export per hour.")
            if response.status_code not in (200, 202):
                raise UserError(self.env._("Export returned HTTP %(status)s: %(detail)s",
                                           status=response.status_code, detail=response.text[:200]))
            export_id = str(response.json()['id'])
            params.set_str('goatcounter_stats.export_id', export_id)
        text = self._download_export(export_id)
        if text is None:
            return self.env._("Waiting: export %s is still running, it will be imported next hour.", export_id)
        visits, steps = self._import_export_rows(self._parse_export(text))
        last_hit = self._get(f'export/{export_id}').get('last_hit_id')
        if last_hit:
            params.set_str('goatcounter_stats.last_hit_id', str(last_hit))
        params.set_str('goatcounter_stats.export_id', False)
        return self.env._("OK: %(visits)s new visits, %(steps)s new page views/clicks.",
                          visits=visits, steps=steps)

    def run_visit_sync(self):
        """Import new visits; the outcome goes to Settings. Never raises."""
        params = self.env['ir.config_parameter'].sudo()
        try:
            with self.env.cr.savepoint():
                result = self._sync_visits()
            ok = True
        except (UserError, requests.RequestException, ValueError, KeyError, csv.Error) as error:
            _logger.warning("GoatCounter visit import failed: %s", error)
            result = self.env._("Error: %s", error.args[0] if error.args else error)
            ok = False
            # Start a fresh export next time (from the unchanged last_hit_id) instead of
            # retrying a broken one forever.
            params.set_str('goatcounter_stats.export_id', False)
        params.set_str('goatcounter_stats.visit_result', result)
        return ok

    def _today(self):
        try:
            return datetime.now(self._site_tz()).date()
        except (UserError, requests.RequestException, ValueError):
            return fields.Date.today()

    def _cron_sync(self):
        """Hourly: totals for today and yesterday (GoatCounter keeps updating them),
        then the new visits from the export."""
        today = self._today()
        ok = self.run_sync(today - timedelta(days=1), today)
        self.run_visit_sync()
        return ok
