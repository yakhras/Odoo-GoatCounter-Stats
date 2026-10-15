# Copyright 2026 Yaser Akhras
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import os
from datetime import date

from odoo import api, fields, models

from .goatcounter_sync import TOKEN_ENV


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    goatcounter_site_code = fields.Char(
        "GoatCounter site code", config_parameter='goatcounter_stats.site_code',
        help="The <code> of https://<code>.goatcounter.com")
    goatcounter_key_found = fields.Boolean("API key found", compute='_compute_goatcounter_status')
    goatcounter_last_sync = fields.Datetime("Last sync", compute='_compute_goatcounter_status')
    goatcounter_last_result = fields.Char("Last result", compute='_compute_goatcounter_status')
    goatcounter_visit_result = fields.Char("Visits import", compute='_compute_goatcounter_status')
    goatcounter_backfill_from = fields.Date("Backfill from", default=date(2026, 10, 15))

    @api.depends('goatcounter_site_code')
    def _compute_goatcounter_status(self):
        params = self.env['ir.config_parameter'].sudo()
        for settings in self:
            settings.goatcounter_key_found = bool(os.environ.get(TOKEN_ENV))
            settings.goatcounter_last_sync = params.get_param('goatcounter_stats.last_sync') or False
            settings.goatcounter_last_result = params.get_param('goatcounter_stats.last_result') or '-'
            settings.goatcounter_visit_result = params.get_param('goatcounter_stats.visit_result') or '-'

    def action_goatcounter_sync_now(self):
        """Same as the hourly cron: today and yesterday."""
        self.set_values()  # use a site code typed in the same form
        self.env['goatcounter.sync']._cron_sync()
        return {'type': 'ir.actions.client', 'tag': 'reload'}

    def action_goatcounter_backfill(self):
        self.set_values()
        sync = self.env['goatcounter.sync']
        today = sync._today()
        sync.run_sync(min(self.goatcounter_backfill_from or today, today), today)
        return {'type': 'ir.actions.client', 'tag': 'reload'}
