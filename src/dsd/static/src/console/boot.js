/** @odoo-module alias=@dsd/console/boot **/
import { mount } from '@odoo/owl';
import { ConsoleApp } from './console_app';

document.addEventListener('DOMContentLoaded', () => {
    const root = document.getElementById('dsd-console-root');
    if (root) {
        mount(ConsoleApp, root, { dev: false });
    }
});
