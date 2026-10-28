# Copyright 2026 Yaser Akhras
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
{
    'name': "GoatCounter Website Stats",
    'summary': "Pull your website's GoatCounter statistics (visits, pages, "
               "click events, referrers, countries, browsers) into Odoo.",
    'author': "Yaser Akhras",
    'maintainers': ["yakhras"],
    'website': "https://yaserakhras.com",
    'category': "Website",
    'version': '19.0.1.2.3',
    'application': True,
    'license': 'AGPL-3',
    'depends': ['base_setup'],
    'external_dependencies': {'python': ['requests']},
    'data': [
        'security/ir.model.access.csv',
        'data/ir_cron.xml',
        'views/goatcounter_views.xml',
        'views/goatcounter_visit_views.xml',
        'views/res_config_settings_views.xml',
        'views/menus.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'goatcounter_stats/static/src/dashboard/*',
        ],
    },
}
