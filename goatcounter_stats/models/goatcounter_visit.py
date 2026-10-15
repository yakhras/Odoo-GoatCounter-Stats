# Copyright 2026 Yaser Akhras
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import api, fields, models


class GoatcounterVisit(models.Model):
    """One visit = the page views and clicks GoatCounter grouped under one session.

    A session is one browser on the site for a few hours, not a person: GoatCounter
    sets no cookies and stores no IP, so a returning visitor is a new visit.
    """
    _name = 'goatcounter.visit'
    _description = "GoatCounter visit (one session)"
    _order = 'start desc'
    _rec_name = 'start'

    session = fields.Char(required=True, index=True, readonly=True)
    start = fields.Datetime(index=True, readonly=True)
    end = fields.Datetime(readonly=True)
    location = fields.Char(readonly=True, help="GoatCounter location code, e.g. BR or TR-34.")
    country_id = fields.Many2one('res.country', "Country", index=True, readonly=True)
    browser = fields.Char(readonly=True)
    system = fields.Char(readonly=True)
    screen_size = fields.Char(readonly=True)
    referrer = fields.Char(readonly=True)
    first_visit = fields.Boolean(readonly=True, help="GoatCounter thinks this browser had not visited before.")
    pageview_ids = fields.One2many('goatcounter.pageview', 'visit_id', "Timeline", readonly=True)
    pageview_count = fields.Integer("Pages", compute='_compute_summary', store=True)
    click_count = fields.Integer("Clicks", compute='_compute_summary', store=True)
    journey = fields.Char(compute='_compute_summary', store=True,
                          help="Pages and clicks in order; clicks are marked with ★.")

    _session_uniq = models.Constraint('unique(session)', "One visit per session.")

    @api.depends('start', 'country_id', 'location')
    def _compute_display_name(self):
        for visit in self:
            when = fields.Datetime.context_timestamp(visit, visit.start).strftime('%Y-%m-%d %H:%M') \
                if visit.start else ''
            visit.display_name = f"{visit.country_id.name or visit.location or '?'} · {when}"

    @api.depends('pageview_ids.path', 'pageview_ids.is_event', 'pageview_ids.datetime')
    def _compute_summary(self):
        for visit in self:
            steps = visit.pageview_ids.sorted('datetime')
            visit.pageview_count = len(steps.filtered(lambda s: not s.is_event))
            visit.click_count = len(steps.filtered('is_event'))
            visit.journey = " → ".join(f"★{s.path}" if s.is_event else s.path for s in steps)[:500]


class GoatcounterPageview(models.Model):
    _name = 'goatcounter.pageview'
    _description = "GoatCounter page view or click inside a visit"
    _order = 'datetime, id'
    _rec_name = 'path'

    visit_id = fields.Many2one('goatcounter.visit', required=True, ondelete='cascade', index=True)
    datetime = fields.Datetime("Time", required=True)
    path = fields.Char(required=True)
    title = fields.Char()
    is_event = fields.Boolean("Click")
    country_id = fields.Many2one(related='visit_id.country_id', store=True)

    _step_uniq = models.Constraint('unique(visit_id, datetime, path, is_event)', "Duplicate page view.")
