// Copyright 2026 Yaser Akhras
// License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import { Component, onMounted, onWillStart, onWillUnmount, proxy, signal } from "@odoo/owl";
import { loadBundle } from "@web/core/assets";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

const PERIODS = [
    { days: 7, label: _t("7 days") },
    { days: 30, label: _t("30 days") },
    { days: 90, label: _t("90 days") },
    { days: 0, label: _t("All time") },
];
const SOURCE_ORDER = ["locations", "toprefs", "browsers", "systems", "sizes"];
const COLORS = { pageviews: "#2E7D6B", clicks: "#E07A2E" };

export class GoatcounterDashboard extends Component {
    static template = "goatcounter_stats.Dashboard";
    canvasRef = signal.ref();

    setup() {
        this.orm = useService("orm");
        this.actionService = useService("action");
        this.notification = useService("notification");
        this.periods = PERIODS;
        this.sourceOrder = SOURCE_ORDER;
        this.state = proxy({ days: 30, data: null, syncing: false });

        onWillStart(async () => {
            await loadBundle("web.chartjs_lib");
            await this.load();
        });
        onMounted(() => this.renderChart());
        onWillUnmount(() => this.chart?.destroy());
    }

    async load() {
        this.state.data = await this.orm.call("goatcounter.dashboard", "get_dashboard_data", [this.state.days]);
    }

    async setPeriod(days) {
        this.state.days = days;
        await this.load();
        this.renderChart();
    }

    async syncNow() {
        this.state.syncing = true;
        try {
            const ok = await this.orm.call("goatcounter.dashboard", "action_sync_now", []);
            await this.load();
            this.renderChart();
            this.notification.add(this.state.data.last_result, { type: ok ? "success" : "danger" });
        } finally {
            this.state.syncing = false;
        }
    }

    // ------------------------------------------------------------ helpers

    delta(current, previous) {
        if (!previous) {
            return null;
        }
        return Math.round(((current - previous) / previous) * 100);
    }

    percent(count, total) {
        return total ? Math.round((count / total) * 100) : 0;
    }

    barWidth(count, rows) {
        const max = Math.max(...rows.map((r) => r.count), 1);
        return `width: ${Math.max(2, Math.round((count / max) * 100))}%`;
    }

    get periodDomain() {
        const { date_from, date_to } = this.state.data;
        return [["date", ">=", date_from], ["date", "<=", date_to]];
    }

    // ------------------------------------------------------------ drill-down

    openRecords(name, model, domain) {
        this.actionService.doAction({
            type: "ir.actions.act_window",
            name,
            res_model: model,
            views: [[false, "list"], [false, "pivot"], [false, "graph"]],
            domain: [...this.periodDomain, ...domain],
        });
    }

    openPages(path) {
        const domain = [["is_event", "=", false]];
        this.openRecords(path || _t("Pages"), "goatcounter.hit", path ? [...domain, ["path", "=", path]] : domain);
    }

    openClicks(name) {
        const domain = [["is_event", "=", true]];
        this.openRecords(name || _t("Clicks"), "goatcounter.hit", name ? [...domain, ["path", "=", name]] : domain);
    }

    openVisits(name, domain = []) {
        this.actionService.doAction({
            type: "ir.actions.act_window",
            name: name || _t("Visitor journeys"),
            res_model: "goatcounter.visit",
            views: [[false, "list"], [false, "form"]],
            domain: [["start", ">=", `${this.state.data.date_from} 00:00:00`], ...domain],
        });
    }

    openVisit(id) {
        this.actionService.doAction({
            type: "ir.actions.act_window",
            res_model: "goatcounter.visit",
            res_id: id,
            views: [[false, "form"]],
        });
    }

    openSource(kind, name) {
        if (kind === "locations" && name) {
            // A country row answers "what did the visitors from there do?"
            this.openVisits(name, [["country_id.name", "=", name]]);
            return;
        }
        const domain = [["kind", "=", kind]];
        this.openRecords(name || this.state.data.sources[kind].label, "goatcounter.dimension",
            name ? [...domain, ["name", "=", name]] : domain);
    }

    // ------------------------------------------------------------ chart

    renderChart() {
        if (!this.canvasRef() || !this.state.data) {
            return;
        }
        this.chart?.destroy();
        const daily = this.state.data.daily;
        const dataset = (key, label) => ({
            label,
            data: daily.map((d) => d[key]),
            borderColor: COLORS[key],
            backgroundColor: COLORS[key] + "33",
            fill: key === "pageviews",
            tension: 0.3,
            pointRadius: daily.length > 45 ? 0 : 3,
        });
        this.chart = new window.Chart(this.canvasRef(), {
            type: "line",
            data: {
                labels: daily.map((d) => d.date),
                datasets: [dataset("pageviews", _t("Page views")), dataset("clicks", _t("Clicks"))],
            },
            options: {
                maintainAspectRatio: false,
                interaction: { mode: "index", intersect: false },
                scales: { y: { beginAtZero: true, ticks: { precision: 0 } } },
                plugins: { legend: { position: "bottom" } },
            },
        });
    }
}

registry.category("actions").add("goatcounter_stats.dashboard", GoatcounterDashboard);
