# Generated demo data for screenshots: about 800 visits over 60 days, and the daily
# page, click and source counts derived from them, so the dashboard and the visitor
# journeys agree. No real visitor data. Same seed, same data.
# Run on a throwaway DB: odoo shell -d goatcounter_stats_demo < tools/demo_data.py
# (scripts/module_lab.ps1 -Do up does this). The file is the same on every series branch.
import random
from collections import Counter
from datetime import datetime, time, timedelta

rnd = random.Random(42)
now = datetime.now()  # UTC in the Odoo container
today = now.date()
DAYS = 60

PAGES = [  # path, title, weight
    ('/', "Yaser Akhras", 30),
    ('/erp/', "ERP", 18),
    ('/erp/stock_valuation/', "Stock Valuation per Warehouse for Odoo", 12),
    ('/erp/trello/', "Trello for Odoo", 10),
    ('/erp/goatcounter_stats/', "GoatCounter Website Stats for Odoo", 8),
    ('/erp/spt/', "SPT: Syrian Pound Exchange Rates for Odoo", 6),
    ('/about/', "About", 7),
    ('/blog/ci_cd/', "CI/CD, explained", 5),
    ('/linux/grep/', "grep, explained step by step", 4),
]
EVENTS = [('sector-erp', 10), ('github-link', 6), ('download-zip', 4), ('email', 2)]
COUNTRIES = [  # GoatCounter location code, weight
    ('TR', 30), ('SY', 14), ('DE', 10), ('US', 9), ('BR', 6), ('AE', 6), ('SA', 5),
    ('GB', 5), ('NL', 4), ('FR', 4), ('EG', 3), ('IN', 3),
]
BROWSERS = [('Chrome 141', 50), ('Safari 26', 18), ('Firefox 144', 12), ('Edge 141', 12), ('Samsung Internet 28', 8)]
SYSTEMS = [('Windows 11', 34), ('Android 16', 26), ('iOS 26', 18), ('macOS 15', 12), ('Linux', 10)]
SIZES = [('Computer monitors', 55), ('Phones', 35), ('Tablets', 10)]
REFERRERS = [('', 45), ('google.com', 25), ('linkedin.com', 14), ('github.com', 10), ('bing.com', 6)]


def pick(rows):
    return rnd.choices([r[0] for r in rows], [r[-1] for r in rows])[0]


env['goatcounter.pageview'].search([]).unlink()
for model in ('goatcounter.visit', 'goatcounter.hit', 'goatcounter.dimension', 'goatcounter.total'):
    env[model].search([]).unlink()

countries = {c.code: c for c in env['res.country'].search([])}
titles = {p: t for p, t, _w in PAGES}
hits = Counter()        # (date, path, is_event) -> count
dims = Counter()        # (date, kind, name) -> count
totals = Counter()      # date -> visits
visits = []


def add_visit(day, code, steps, browser=None, system=None, size=None, ref=None, first=None):
    start = datetime.combine(day, time(rnd.randint(6, 22), rnd.randint(0, 59)))
    if start > now - timedelta(minutes=30):  # today: nothing in the future
        start = now - timedelta(minutes=rnd.randint(30, 600))
    browser, system = browser or pick(BROWSERS), system or pick(SYSTEMS)
    size, ref = size or pick(SIZES), ref if ref is not None else pick(REFERRERS)
    pageviews, moment = [], start
    for path, is_event in steps:
        pageviews.append((0, 0, {'datetime': moment, 'path': path, 'is_event': is_event,
                                 'title': '' if is_event else titles.get(path, '')}))
        hits[(day, path, is_event)] += 1
        moment += timedelta(seconds=rnd.randint(8, 140))
    visits.append({
        'session': f'demo-{len(visits):05d}', 'start': start, 'end': moment,
        'location': code, 'country_id': countries[code].id if code in countries else False,
        'browser': browser, 'system': system, 'screen_size': size,
        'referrer': ref, 'first_visit': rnd.random() < 0.7 if first is None else first,
        'pageview_ids': pageviews,
    })
    totals[day] += 1
    for kind, name in (('locations', countries[code].name if code in countries else code),
                       ('browsers', browser.split(' ')[0]), ('systems', system.split(' ')[0]),
                       ('sizes', size), ('toprefs', ref or '(direct)')):
        dims[(day, kind, name)] += 1


for offset in range(DAYS - 1, -1, -1):
    day = today - timedelta(days=offset)
    weekend = day.weekday() >= 5
    # Traffic grows over the period, with quieter weekends.
    count = int((8 + 10 * (DAYS - offset) / DAYS) * (0.6 if weekend else 1) + rnd.randint(-3, 4))
    for _i in range(max(count, 2)):
        steps = []
        for _p in range(rnd.choices([1, 2, 3, 4, 5], [40, 25, 18, 10, 7])[0]):
            steps.append((pick(PAGES), False))
            if rnd.random() < 0.18:
                steps.append((pick(EVENTS), True))
        add_visit(day, pick(COUNTRIES), steps)

# The README's example: a visitor from Brazil who went from the home page to the ERP
# sector card, read Stock Valuation and opened its GitHub repository.
add_visit(today, 'BR', [('/', False), ('sector-erp', True), ('/erp/', False),
                        ('/erp/stock_valuation/', False), ('github-link', True)],
          browser='Chrome 141', system='Windows 11', size='Computer monitors',
          ref='linkedin.com', first=True)

env['goatcounter.visit'].create(visits)
env['goatcounter.hit'].create([
    {'date': d, 'path': p, 'is_event': e, 'title': '' if e else titles.get(p, ''), 'count': n}
    for (d, p, e), n in hits.items()])
env['goatcounter.dimension'].create([
    {'date': d, 'kind': k, 'name': name, 'count': n} for (d, k, name), n in dims.items()])
env['goatcounter.total'].create([{'date': d, 'count': n} for d, n in totals.items()])

# Settings and sync status as after a successful hourly sync. Odoo 20 replaced
# set_param with typed setters; this file runs unchanged on 18.0 to 20.0.
params = env['ir.config_parameter'].sudo()
set_param = getattr(params, 'set_str', None) or params.set_param
set_param('goatcounter_stats.site_code', 'yourwebsite')
set_param('goatcounter_stats.last_sync', datetime.now().replace(minute=5, second=0).strftime('%Y-%m-%d %H:%M:%S'))
set_param('goatcounter_stats.last_result', f"OK: {DAYS} days synced")
set_param('goatcounter_stats.visit_result', f"OK: {len(visits)} visits imported")
env.cr.commit()
print(f"demo data: {len(visits)} visits, {len(hits)} hit rows, {len(dims)} dimension rows")
