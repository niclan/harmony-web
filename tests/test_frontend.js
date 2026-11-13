// Exercise the actual activity loader with fake network responses and timers.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const html = fs.readFileSync(`${__dirname}/../templates/index.html`, 'utf8');
const loader = html.slice(html.indexOf('        async function fetchActivities()'),
    html.indexOf('        async function fetchCurrentActivity()'));
const timers = [];
const errors = [];
let renders = 0;
let response;
const context = vm.createContext({
    fetch: async () => {
        if (response instanceof Error) throw response;
        return response;
    },
    setTimeout: (callback, delay) => timers.push({ callback, delay }),
    showError: message => errors.push(message),
    renderActivities: () => renders++,
});
vm.runInContext(`let activities = []; ${loader}`, context);

async function next(expectedDelay) {
    assert.equal(timers.length, 1, 'one pending refresh');
    const timer = timers.shift();
    assert.equal(timer.delay, expectedDelay);
    await timer.callback();
}

(async () => {
    response = { ok: false, json: async () => ({ error: 'Hub unavailable' }) };
    await context.fetchActivities();
    assert.equal(renders, 0);
    assert.equal(errors[0], 'Hub unavailable');

    response = { ok: true, json: async () => ({ activities: [{ id: '123', label: 'TV' }] }) };
    await next(5000);
    assert.equal(renders, 1, 'recovered without reloading the page');
    await next(60000);
    assert.equal(renders, 1, 'unchanged list does not redraw');

    response = new Error('Network offline');
    await next(60000);
    assert.equal(renders, 1, 'failure preserves the visible list');
    response = { ok: true, json: async () => ({ activities: [{ id: '456', label: 'Music' }] }) };
    await next(5000);
    assert.equal(renders, 2, 'changed list redraws');
    assert.equal(timers.length, 1);
    assert.equal(timers[0].delay, 60000);
    console.log('Activity refresh: retry, recovery, and unchanged-list checks passed');
})().catch(error => {
    console.error(error);
    process.exitCode = 1;
});
