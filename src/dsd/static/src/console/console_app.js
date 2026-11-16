"""DSD driver console OWL app (phone-first)."""
import { Component, useState, onWillStart } from '@odoo/owl';

function api(method, args = {}) {
    return fetch(`/dsd/api/v1/${method}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ jsonrpc: '2.0', method: 'call', params: args }),
        credentials: 'same-origin',
    }).then((r) => r.json());
}

const STATUS_LABELS = {
    np: 'Not visited', sp: 'Done', pp: 'Partial', up: 'Failed', rs: 'Rescheduled',
};

export class ConsoleApp extends Component {
    setup() {
        this.state = useState({
            screen: 'today',
            data: null,
            stop: null,
            message: '',
            loading: false,
        });
        onWillStart(() => this.refresh());
    }

    async refresh() {
        this.state.loading = true;
        const result = await api('get_console_data');
        this.state.loading = false;
        this.state.data = result.ok ? result.data : null;
        this.state.message = result.ok ? '' : result.error;
    }

    async openStop(stopId) {
        this.state.loading = true;
        const result = await api('get_stop', { visit_line_id: stopId });
        this.state.loading = false;
        if (result.ok) {
            this.state.stop = result.data;
            this.state.screen = 'stop';
        } else {
            this.state.message = result.error;
        }
    }

    back() {
        this.state.screen = 'today';
        this.state.stop = null;
        this.refresh();
    }

    async do(method, args = {}) {
        this.state.loading = true;
        const result = await api(method, args);
        this.state.loading = false;
        this.state.message = result.ok ? _('Done.') : result.error;
        return result.ok;
    }
}

ConsoleApp.template = 'dsd.console.app';

export class TodayScreen extends Component {
    static template = 'dsd.console.today';
    static props = ['data', 'app'];

    openStop(id) {
        this.props.app.openStop(id);
    }
}

export class StopScreen extends Component {
    static template = 'dsd.console.stop';
    static props = ['stop', 'app'];

    setup() {
        this.state = useState({
            quantities: {},
            saleLines: [{ product_id: null, qty: 1, discount: 0 }],
            collectionAmount: 0,
            collectionJournal: null,
            collectionInvoice: null,
            reasonId: null,
            note: '',
        });
    }

    get route() {
        return this.props.app.route.bind(this.props.app);
    }

    async arrive() {
        await this.props.app.do('set_arrival', { visit_line_id: this.props.stop.id });
    }

    async depart() {
        await this.props.app.do('set_departure', { visit_line_id: this.props.stop.id });
    }

    async setStatus(status) {
        await this.props.app.do('set_visit_status', {
            visit_line_id: this.props.stop.id, status, reason_id: this.state.reasonId,
        });
        this.props.app.back();
    }

    async saveNote() {
        await this.props.app.do('set_visit_note', {
            visit_line_id: this.props.stop.id, note: this.state.note,
        });
    }

    qtyKey(moveId) {
        return 'q' + moveId;
    }

    async confirmDelivery() {
        const quantities = {};
        for (const line of this.props.stop.delivery.lines) {
            const value = this.state.quantities[this.qtyKey(line.move_id)];
            if (value !== undefined && value !== null) {
                quantities[line.product_id ? line.product_id : line.product_id] =
                    parseFloat(value) || 0;
            }
        }
        // quantities keyed by product id as the service expects
        const byProduct = {};
        for (const line of this.props.stop.delivery.lines) {
            const value = this.state.quantities[this.qtyKey(line.move_id)];
            if (value !== undefined && value !== null) {
                byProduct[this.productIdOf(line)] = parseFloat(value) || 0;
            }
        }
        const ok = await this.props.app.do('confirm_delivery', {
            picking_id: this.props.stop.delivery.id, quantities: byProduct,
        });
        if (ok) {
            this.props.app.back();
        }
    }

    productIdOf(line) {
        // the API returns product display names; the service keys by product id.
        // The stop payload therefore also carries product ids (see get_stop).
        return line.product_id_int;
    }

    addSaleLine() {
        this.state.saleLines.push({ product_id: null, qty: 1, discount: 0 });
    }

    async submitVanSale() {
        const lines = this.state.saleLines
            .filter((l) => l.product_id && l.qty > 0)
            .map((l) => ({
                product_id: parseInt(l.product_id, 10),
                qty: parseFloat(l.qty),
                discount: parseFloat(l.discount) || 0,
            }));
        const ok = await this.props.app.do('create_van_sale', {
            visit_line_id: this.props.stop.id, lines,
        });
        if (ok) {
            this.props.app.back();
        }
    }

    async submitCollection() {
        const invoiceId = this.state.collectionInvoice;
        const ok = await this.props.app.do('create_collection', {
            visit_line_id: this.props.stop.id,
            amount: parseFloat(this.state.collectionAmount) || 0,
            journal_id: parseInt(this.state.collectionJournal, 10),
            invoice_ids: invoiceId ? [parseInt(invoiceId, 10)] : [],
        });
        if (ok) {
            this.props.app.back();
        }
    }
}

export function mountConsole() {
    const mountPoint = document.getElementById('dsd-console-root');
    if (mountPoint) {
        mount(ConsoleApp, mountPoint, { dev: false });
    }
}
