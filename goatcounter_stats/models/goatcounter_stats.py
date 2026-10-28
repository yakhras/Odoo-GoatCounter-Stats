# Copyright 2026 Yaser Akhras
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import fields, models

DIMENSION_KINDS = [
    ('toprefs', "Referrer"),
    ('locations', "Country"),
    ('browsers', "Browser"),
    ('systems', "System"),
    ('sizes', "Screen size"),
]


class GoatcounterTotal(models.Model):
    _name = 'goatcounter.total'
    _description = "GoatCounter visits per day"
    _order = 'date desc'
    _rec_name = 'date'

    date = fields.Date(required=True, index=True)
    count = fields.Integer("Visits")

    _sql_constraints = [('date_uniq', 'unique(date)', "One total per day.")]


class GoatcounterHit(models.Model):
    _name = 'goatcounter.hit'
    _description = "GoatCounter visits per page or click event per day"
    _order = 'date desc, count desc'
    _rec_name = 'path'

    date = fields.Date(required=True, index=True)
    path = fields.Char(required=True, index=True,
                       help="Page path, or the click event name (data-goatcounter-click).")
    title = fields.Char()
    is_event = fields.Boolean("Click event", index=True)
    count = fields.Integer("Count")

    _sql_constraints = [('date_path_uniq', 'unique(date, path, is_event)', "One row per page per day.")]


class GoatcounterDimension(models.Model):
    _name = 'goatcounter.dimension'
    _description = "GoatCounter visits per referrer, country, browser, system or size per day"
    _order = 'date desc, kind, count desc'

    date = fields.Date(required=True, index=True)
    kind = fields.Selection(DIMENSION_KINDS, required=True, index=True)
    name = fields.Char(required=True)
    count = fields.Integer("Visits")

    _sql_constraints = [('date_kind_name_uniq', 'unique(date, kind, name)', "One row per value per day.")]
