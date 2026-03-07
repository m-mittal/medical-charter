let allRecords = [];
let filteredRecords = [];
let currentPage = 1;
const PAGE_SIZE = 50;
let sortColumn = 'date';
let sortAsc = false;
let trendChart = null;
let TEST_CATEGORIES = {};

const STATIC_MODE = typeof window.__STATIC_DATA__ !== 'undefined';

async function loadCategories() {
    try {
        if (STATIC_MODE) {
            TEST_CATEGORIES = window.__STATIC_CATEGORIES__;
            return;
        }
        const res = await fetch('/api/config/categories');
        TEST_CATEGORIES = await res.json();
    } catch (e) {
        console.error('Failed to load test categories:', e);
    }
}

function getCategoryForTest(testName) {
    for (const [cat, tests] of Object.entries(TEST_CATEGORIES)) {
        if (tests.includes(testName)) return cat;
    }
    return 'Other';
}

async function fetchData() {
    if (STATIC_MODE) return window.__STATIC_DATA__;
    const res = await fetch('/api/data');
    return res.json();
}

async function fetchSummary() {
    if (STATIC_MODE) return window.__STATIC_SUMMARY__;
    const res = await fetch('/api/summary');
    return res.json();
}

function parseRefRange(ref) {
    if (!ref) return null;
    ref = ref.trim();
    let match;
    match = ref.match(/(\d+\.?\d*)\s*-\s*(\d+\.?\d*)/);
    if (match) return { low: parseFloat(match[1]), high: parseFloat(match[2]) };
    match = ref.match(/<\s*(\d+\.?\d*)/);
    if (match) return { low: null, high: parseFloat(match[1]) };
    match = ref.match(/>\s*(\d+\.?\d*)/);
    if (match) return { low: parseFloat(match[1]), high: null };
    return null;
}

function classifyValue(value, refStr) {
    const range = parseRefRange(refStr);
    if (!range) return 'normal';
    if (range.low !== null && value < range.low) return 'low';
    if (range.high !== null && value > range.high) return 'high';
    return 'normal';
}

function populateFilters(data) {
    const testFilter = document.getElementById('testFilter');
    testFilter.innerHTML = '';
    data.tests.forEach(t => {
        const opt = document.createElement('option');
        opt.value = t;
        opt.textContent = t;
        testFilter.appendChild(opt);
    });

    const trendTest = document.getElementById('trendTest');
    trendTest.innerHTML = '';
    const grouped = {};
    data.tests.forEach(t => {
        const cat = getCategoryForTest(t);
        if (!grouped[cat]) grouped[cat] = [];
        grouped[cat].push(t);
    });
    for (const [cat, tests] of Object.entries(grouped).sort((a, b) => a[0].localeCompare(b[0]))) {
        const optgroup = document.createElement('optgroup');
        optgroup.label = cat;
        tests.sort().forEach(t => {
            const opt = document.createElement('option');
            opt.value = t;
            opt.textContent = t;
            optgroup.appendChild(opt);
        });
        trendTest.appendChild(optgroup);
    }

    if (data.dates.length) {
        document.getElementById('dateFrom').value = data.dates[0];
        document.getElementById('dateTo').value = data.dates[data.dates.length - 1];
    }
}

function applyFilters() {
    const testFilter = document.getElementById('testFilter');
    const selectedTests = Array.from(testFilter.selectedOptions).map(o => o.value);
    const dateFrom = document.getElementById('dateFrom').value;
    const dateTo = document.getElementById('dateTo').value;
    const search = document.getElementById('searchBox').value.toLowerCase().trim();

    filteredRecords = allRecords.filter(r => {
        if (selectedTests.length && !selectedTests.includes(r.test_name)) return false;
        if (dateFrom && r.date < dateFrom) return false;
        if (dateTo && r.date > dateTo) return false;
        if (search && !r.test_name.toLowerCase().includes(search)) return false;
        return true;
    });

    currentPage = 1;
    sortRecords();
    renderTable();
}

function clearFilters() {
    document.getElementById('testFilter').selectedIndex = -1;
    document.getElementById('searchBox').value = '';
    const dates = allRecords.map(r => r.date);
    if (dates.length) {
        document.getElementById('dateFrom').value = dates.reduce((a, b) => a < b ? a : b);
        document.getElementById('dateTo').value = dates.reduce((a, b) => a > b ? a : b);
    }
    filteredRecords = [...allRecords];
    currentPage = 1;
    sortRecords();
    renderTable();
}

function sortRecords() {
    filteredRecords.sort((a, b) => {
        let va = a[sortColumn];
        let vb = b[sortColumn];
        if (sortColumn === 'value') {
            va = parseFloat(va) || 0;
            vb = parseFloat(vb) || 0;
        }
        if (va < vb) return sortAsc ? -1 : 1;
        if (va > vb) return sortAsc ? 1 : -1;
        return 0;
    });
}

function renderTable() {
    const tbody = document.getElementById('tableBody');
    const start = (currentPage - 1) * PAGE_SIZE;
    const pageData = filteredRecords.slice(start, start + PAGE_SIZE);

    tbody.innerHTML = pageData.map(r => {
        const cls = classifyValue(r.value, r.reference_range);
        const rowClass = cls !== 'normal' ? ' class="abnormal"' : '';
        const valueCls = `value-cell value-${cls}`;
        const lab = r.lab_name || 'Unknown Lab';
        const tooltip = `${lab}\n${r.filename}`;
        return `<tr${rowClass}>
            <td data-label="Date">${r.date}</td>
            <td data-label="Test">${r.test_name}</td>
            <td data-label="Value" class="${valueCls}" title="Lab: ${lab}">${r.value}</td>
            <td data-label="Unit">${r.unit || '-'}</td>
            <td data-label="Ref Range">${r.reference_range || '-'}</td>
            <td data-label="Report" title="${tooltip}">${r.report_name}<span class="lab-badge">${lab}</span></td>
        </tr>`;
    }).join('');

    renderPagination();
}

function renderPagination() {
    const totalPages = Math.ceil(filteredRecords.length / PAGE_SIZE);
    const container = document.getElementById('pagination');
    if (totalPages <= 1) { container.innerHTML = ''; return; }

    let html = `<button ${currentPage === 1 ? 'disabled' : ''} onclick="goToPage(${currentPage - 1})">&laquo;</button>`;
    const startPage = Math.max(1, currentPage - 3);
    const endPage = Math.min(totalPages, currentPage + 3);
    if (startPage > 1) html += `<button onclick="goToPage(1)">1</button><span class="page-info">...</span>`;
    for (let i = startPage; i <= endPage; i++) {
        html += `<button class="${i === currentPage ? 'active' : ''}" onclick="goToPage(${i})">${i}</button>`;
    }
    if (endPage < totalPages) html += `<span class="page-info">...</span><button onclick="goToPage(${totalPages})">${totalPages}</button>`;
    html += `<button ${currentPage === totalPages ? 'disabled' : ''} onclick="goToPage(${currentPage + 1})">&raquo;</button>`;
    html += `<span class="page-info">${filteredRecords.length} records</span>`;
    container.innerHTML = html;
}

function goToPage(p) {
    currentPage = p;
    renderTable();
    document.getElementById('tableView').scrollIntoView({ behavior: 'smooth' });
}

function setupSorting() {
    document.querySelectorAll('#resultsTable th[data-sort]').forEach(th => {
        th.addEventListener('click', () => {
            const col = th.dataset.sort;
            if (sortColumn === col) {
                sortAsc = !sortAsc;
            } else {
                sortColumn = col;
                sortAsc = true;
            }
            sortRecords();
            renderTable();
            document.querySelectorAll('#resultsTable th .sort-icon').forEach(s => s.textContent = '');
            th.querySelector('.sort-icon').textContent = sortAsc ? ' \u25B2' : ' \u25BC';
        });
    });
}

async function renderTrend(testName) {
    let data;
    if (STATIC_MODE) {
        data = window.__STATIC_TRENDS__[testName] || {dates:[], values:[], units:'', refs:[], labs:[]};
    } else {
        const res = await fetch(`/api/trend/${encodeURIComponent(testName)}`);
        data = await res.json();
    }
    const ctx = document.getElementById('trendChart').getContext('2d');

    if (trendChart) trendChart.destroy();

    const isSingle = data.values.length === 1;
    const refRanges = data.refs.map(r => parseRefRange(r)).filter(Boolean);
    const datasets = [{
        label: testName,
        data: data.values,
        borderColor: '#2563eb',
        backgroundColor: isSingle ? 'rgba(37, 99, 235, 0.8)' : 'rgba(37, 99, 235, 0.1)',
        borderWidth: isSingle ? 0 : 2,
        pointBackgroundColor: data.values.map((v, i) => {
            const ref = refRanges[i] || refRanges[0];
            if (!ref) return '#2563eb';
            if (ref.low !== null && v < ref.low) return '#d97706';
            if (ref.high !== null && v > ref.high) return '#dc2626';
            return '#16a34a';
        }),
        pointRadius: isSingle ? 8 : 5,
        pointHoverRadius: isSingle ? 10 : 7,
        pointBorderWidth: isSingle ? 3 : 1,
        pointBorderColor: '#2563eb',
        fill: !isSingle,
        tension: 0.3,
        showLine: !isSingle,
    }];

    if (refRanges.length > 0) {
        const ref = refRanges[refRanges.length - 1] || refRanges[0];
        if (ref && ref.high !== null) {
            datasets.push({
                label: 'Upper Limit',
                data: Array(data.dates.length).fill(ref.high),
                borderColor: 'rgba(220, 38, 38, 0.4)',
                borderWidth: 1,
                borderDash: [5, 5],
                pointRadius: 0,
                fill: false,
            });
        }
        if (ref && ref.low !== null) {
            datasets.push({
                label: 'Lower Limit',
                data: Array(data.dates.length).fill(ref.low),
                borderColor: 'rgba(217, 119, 6, 0.4)',
                borderWidth: 1,
                borderDash: [5, 5],
                pointRadius: 0,
                fill: false,
            });
        }
    }

    // For single data points, compute Y-axis range so the dot isn't squished at the edge
    const yScaleOpts = { title: { display: true, text: data.units || 'Value' } };
    if (isSingle) {
        const v = data.values[0];
        const ref = refRanges[0];
        const margin = v * 0.3 || 10;
        let lo = v - margin;
        let hi = v + margin;
        if (ref) {
            if (ref.low !== null) lo = Math.min(lo, ref.low - margin * 0.2);
            if (ref.high !== null) hi = Math.max(hi, ref.high + margin * 0.2);
        }
        yScaleOpts.min = Math.max(0, lo);
        yScaleOpts.max = hi;
    }

    trendChart = new Chart(ctx, {
        type: 'line',
        data: { labels: data.dates, datasets },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { position: 'top' },
                tooltip: {
                    callbacks: {
                        label: ctx => `${ctx.dataset.label}: ${ctx.parsed.y} ${data.units || ''}`,
                        afterLabel: ctx => {
                            if (ctx.datasetIndex === 0 && data.labs && data.labs[ctx.dataIndex]) {
                                return `Lab: ${data.labs[ctx.dataIndex]}`;
                            }
                            return '';
                        }
                    }
                }
            },
            scales: {
                x: { title: { display: true, text: 'Date' } },
                y: yScaleOpts
            }
        }
    });

    const statsEl = document.getElementById('trendStats');
    if (data.values.length) {
        const vals = data.values;
        const min = Math.min(...vals);
        const max = Math.max(...vals);
        const avg = (vals.reduce((a, b) => a + b, 0) / vals.length).toFixed(2);
        const latest = vals[vals.length - 1];
        const latestDate = data.dates[data.dates.length - 1];
        statsEl.innerHTML = `
            <div class="trend-stat"><div class="ts-label">Latest (${latestDate})</div><div class="ts-value">${latest} ${data.units}</div></div>
            <div class="trend-stat"><div class="ts-label">Min</div><div class="ts-value">${min}</div></div>
            <div class="trend-stat"><div class="ts-label">Max</div><div class="ts-value">${max}</div></div>
            <div class="trend-stat"><div class="ts-label">Average</div><div class="ts-value">${avg}</div></div>
            <div class="trend-stat"><div class="ts-label">Readings</div><div class="ts-value">${vals.length}</div></div>
        `;
    }
}

function renderPivotView() {
    const pivotEl = document.getElementById('pivotContent');
    const latestByTest = {};
    const allByTest = {};

    for (const r of allRecords) {
        if (!allByTest[r.test_name]) allByTest[r.test_name] = [];
        allByTest[r.test_name].push(r);
        if (!latestByTest[r.test_name] || r.date > latestByTest[r.test_name].date) {
            latestByTest[r.test_name] = r;
        }
    }

    const categories = {};
    for (const [test, record] of Object.entries(latestByTest)) {
        const cat = getCategoryForTest(test);
        if (!categories[cat]) categories[cat] = [];
        categories[cat].push({ test, record, count: allByTest[test].length });
    }

    pivotEl.innerHTML = Object.entries(categories)
        .sort((a, b) => a[0].localeCompare(b[0]))
        .map(([cat, items]) => `
            <div class="pivot-category">
                <div class="pivot-category-header">${cat}</div>
                <table>
                    <tr><th>Test</th><th>Value</th><th class="pivot-hide-sm">Unit</th><th class="pivot-hide-sm">Date</th><th class="pivot-hide-sm">#</th></tr>
                    ${items.sort((a, b) => a.test.localeCompare(b.test)).map(({ test, record, count }) => {
                        const cls = classifyValue(record.value, record.reference_range);
                        const lab = record.lab_name || 'Unknown Lab';
                        const unitSuffix = record.unit ? ` <span class="pivot-unit-inline">${record.unit}</span>` : '';
                        return `<tr>
                            <td class="clickable" onclick="showTrend('${test.replace(/'/g, "\\'")}')">${test}</td>
                            <td class="value-cell value-${cls}" title="Lab: ${lab}">${record.value}${unitSuffix}</td>
                            <td class="pivot-hide-sm">${record.unit || '-'}</td>
                            <td class="pivot-hide-sm">${record.date}</td>
                            <td class="pivot-hide-sm">${count}</td>
                        </tr>`;
                    }).join('')}
                </table>
            </div>
        `).join('');
}

function showTrend(testName) {
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
    document.querySelector('[data-view="trends"]').classList.add('active');
    document.getElementById('trendsView').classList.add('active');
    document.getElementById('trendTest').value = testName;
    renderTrend(testName);
}

function setupTabs() {
    document.querySelectorAll('.tab').forEach(tab => {
        tab.addEventListener('click', () => {
            document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
            document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
            tab.classList.add('active');
            document.getElementById(tab.dataset.view + 'View').classList.add('active');
        });
    });
}

function pollRefreshStatus(loadingText, btn, loadingEl) {
    const barContainer = document.getElementById('progressBarContainer');
    const bar = document.getElementById('progressBar');
    barContainer.style.display = 'block';

    const poll = setInterval(async () => {
        try {
            const res = await fetch('/api/refresh/status');
            const status = await res.json();

            if (status.total > 0) {
                const pct = Math.round((status.current / status.total) * 100);
                loadingText.textContent = `Processing PDF ${status.current} of ${status.total} (${pct}%)  —  ${status.current_file}`;
                bar.style.width = pct + '%';
            } else {
                loadingText.textContent = 'Initializing...';
            }

            if (status.done) {
                clearInterval(poll);
                if (status.error) {
                    alert('Refresh failed: ' + status.error);
                    btn.disabled = false;
                    btn.innerHTML = '<span class="btn-icon">&#8635;</span> Refresh Data';
                    loadingEl.classList.add('hidden');
                } else {
                    loadingText.textContent = 'Done! Reloading...';
                    setTimeout(() => location.reload(), 500);
                }
            }
        } catch (e) {
            // Server may be restarting, keep polling
        }
    }, 1000);
}

async function init() {
    setupTabs();
    setupSorting();
    await loadCategories();

    const filterToggle = document.getElementById('filterToggle');
    const filterBody = document.getElementById('filterBody');
    if (filterToggle) {
        filterToggle.addEventListener('click', () => {
            filterToggle.classList.toggle('open');
            filterBody.classList.toggle('open');
        });
    }

    document.getElementById('applyFilters').addEventListener('click', applyFilters);
    document.getElementById('clearFilters').addEventListener('click', clearFilters);
    document.getElementById('trendTest').addEventListener('change', e => renderTrend(e.target.value));
    document.getElementById('searchBox').addEventListener('keyup', e => {
        if (e.key === 'Enter') applyFilters();
    });
    if (STATIC_MODE) {
        document.getElementById('refreshBtn').style.display = 'none';
    }
    document.getElementById('refreshBtn').addEventListener('click', async () => {
        const btn = document.getElementById('refreshBtn');
        btn.disabled = true;
        const loadingEl = document.getElementById('loading');
        const loadingText = loadingEl.querySelector('p');
        loadingEl.classList.remove('hidden');
        loadingText.textContent = 'Starting PDF processing...';

        try {
            const res = await fetch('/api/refresh', { method: 'POST' });
            const data = await res.json();
            if (data.status === 'already_running' || data.status === 'started') {
                pollRefreshStatus(loadingText, btn, loadingEl);
            }
        } catch (err) {
            alert('Refresh failed: ' + err.message);
            btn.disabled = false;
            btn.innerHTML = '<span class="btn-icon">&#8635;</span> Refresh Data';
            loadingEl.classList.add('hidden');
        }
    });

    try {
        const [data, summary] = await Promise.all([fetchData(), fetchSummary()]);

        allRecords = data.records;
        filteredRecords = [...allRecords];

        document.getElementById('statTests').textContent = summary.test_count;
        document.getElementById('statRecords').textContent = summary.record_count;
        document.getElementById('statFiles').textContent = summary.file_count;
        document.getElementById('statDates').textContent = data.dates.length;
        document.getElementById('dateRange').textContent = summary.date_range ? `Reports from ${summary.date_range}` : 'No data';

        populateFilters(data);
        sortRecords();
        renderTable();
        renderPivotView();

        if (data.tests.length) {
            const defaultTest = data.tests.includes('HbA1C') ? 'HbA1C' :
                               data.tests.includes('Fasting Blood Glucose') ? 'Fasting Blood Glucose' :
                               data.tests[0];
            document.getElementById('trendTest').value = defaultTest;
            renderTrend(defaultTest);
        }
    } catch (err) {
        console.error('Failed to load data:', err);
    } finally {
        document.getElementById('loading').classList.add('hidden');
    }
}

document.addEventListener('DOMContentLoaded', init);
