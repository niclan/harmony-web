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

// Hub strings must remain text and event-listener arguments, never executable HTML.
const cardsContainer = { replaceChildren: (...cards) => { cardsContainer.cards = cards; } };
const calls = [];
const cardContext = vm.createContext({
    document: {
        getElementById: () => cardsContainer,
        createElement: tag => ({
            tag,
            children: [],
            listeners: {},
            set innerHTML(value) { throw new Error('Hub data entered HTML'); },
            setAttribute() { throw new Error('Unexpected attribute interpolation'); },
            addEventListener(name, handler) { this.listeners[name] = handler; },
            append(...children) { this.children.push(...children); },
        }),
    },
    startActivity: (...args) => calls.push(args),
});
const hostileName = `John's "Music"><img src=x onerror=alert(1)>`;
const hostileId = `123');alert(1);//`;
cardContext.fixture = [{ id: hostileId, label: hostileName, type: 'VirtualCdMulti' },
    { id: '456', label: hostileName, cachedImageUrl: '/static/images/activities/456.png' }];
const renderer = html.slice(html.indexOf('        function renderActivities()'),
    html.indexOf('        async function startActivity('));
vm.runInContext(`let activities = fixture; let currentActivityId = '456'; ${renderer}; renderActivities();`, cardContext);
const [textCard, imageCard] = cardsContainer.cards;
assert.equal(textCard.children[1].textContent, hostileName);
assert.equal(imageCard.children[0].alt, hostileName);
assert.equal(imageCard.className, 'activity-card active');
const clickEvent = { currentTarget: textCard };
textCard.listeners.click(clickEvent);
assert.deepEqual(calls[0], [hostileId, hostileName, clickEvent]);
console.log('Activity cards: unsafe names remain text and click arguments');

// Every volume press must send a request even while earlier ones are pending.
(async () => {
    const pending = [];
    const sent = [];
    const volumeErrors = [];
    const volumeContext = vm.createContext({
        fetch: (url, options) => {
            assert.equal(url, '/api/volume');
            sent.push(JSON.parse(options.body).action);
            return new Promise(resolve => pending.push(resolve));
        },
        showError: message => volumeErrors.push(message),
    });
    const volume = html.slice(html.indexOf('        async function volumeControl('),
        html.indexOf('        async function powerOff('));
    vm.runInContext(volume, volumeContext);
    const event = { currentTarget: { classList: {
        add() { throw new Error('Volume presses must not lock the button'); },
    } } };
    const actions = ['up', 'up', 'up', 'down', 'down'];
    const requests = actions.map(action => volumeContext.volumeControl(action, event));
    assert.deepEqual(sent, actions, 'all rapid presses sent before any response');
    pending.forEach(resolve => resolve({ json: async () => ({ success: true }) }));
    await Promise.all(requests);
    assert.deepEqual(volumeErrors, []);

    const failed = volumeContext.volumeControl('down');
    pending.at(-1)({ json: async () => ({ error: 'Hub unavailable' }) });
    await failed;
    assert.deepEqual(volumeErrors, ['Hub unavailable']);
    const recovered = volumeContext.volumeControl('up');
    pending.at(-1)({ json: async () => ({ success: true }) });
    await recovered;
    assert.equal(sent.at(-1), 'up', 'presses still work after a failed command');
    console.log('Volume controls: rapid presses and recovery passed');
})().catch(error => {
    console.error(error);
    process.exitCode = 1;
});
