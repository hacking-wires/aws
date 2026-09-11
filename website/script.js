const tbody = document.querySelector('#actions tbody');
const status = document.querySelector('#status');
const refreshBtn = document.querySelector('#refresh');

const OUTCOME_CLASS = {
    ok: 'ok',
};

function outcomeClass(outcome) {
    if (!outcome) return 'unknown';
    if (outcome === 'ok') return 'ok';
    if (outcome.startsWith('error')) return 'err';
    return 'unknown';
}

function actionClass(action) {
    return action === 'terminate' ? 'action-terminate' : 'action-reboot';
}

function fmtWhen(iso) {
    if (!iso) return '—';
    return iso.replace('T', ' ').replace(/\..*/, '');
}

async function loadActions() {
    status.textContent = 'loading…';
    tbody.innerHTML = '';
    try {
        const url = new URL(window.SELF_HEALING_ENDPOINT);
        url.searchParams.set('view', 'actions');
        const res = await fetch(url.toString());
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        const rows = data.actions || [];
        if (rows.length === 0) {
            status.textContent = 'no actions yet — waiting for the first alarm';
            return;
        }
        for (const a of rows) {
            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td>${fmtWhen(a.timestamp)}</td>
                <td><code>${a.instance_id || '—'}</code></td>
                <td class="${actionClass(a.action)}">${a.action || '—'}</td>
                <td class="${outcomeClass(a.outcome)}">${a.outcome || '—'}</td>
                <td>${a.reason || ''}</td>
            `;
            tbody.appendChild(tr);
        }
        status.textContent = `${rows.length} action${rows.length === 1 ? '' : 's'}`;
    } catch (err) {
        status.textContent = `error: ${err.message}`;
    }
}

refreshBtn.addEventListener('click', loadActions);
loadActions();
setInterval(loadActions, 30000);
