
let API_BASE = "";

async function detectApiBase() {
    const candidates = [];

    if (window.location.protocol !== "file:") {
        candidates.push(window.location.origin);
    }

    candidates.push("http://127.0.0.1:8000", "http://localhost:8000");

    for (const base of candidates) {
        try {
            const response = await fetch(`${base}/health`);
            if (response.ok) {
                return base;
            }
        } catch (error) {}
    }

    throw new Error("Backend not reachable on same-origin or localhost:8000");
}

let companies = [];
let activeSymbol = null;
let currentTimeframe = 30;
let chart = null;
let isPredictionVisible = false;
let isComparisonMode = false;
let compareSymbol = null;
let isListExpanded = false;
const COLLAPSED_CARD_COUNT = 8;

async function apiGet(path) {
    const response = await fetch(`${API_BASE}${path}`);
    if (!response.ok) {
        const body = await response.text();
        throw new Error(`API ${response.status} ${path} -> ${body}`);
    }
    return response.json();
}

async function initDashboard() {
    try {
        API_BASE = await detectApiBase();
        const companyRes = await apiGet("/companies");
        companies = companyRes.companies || [];
        if (!companies.length) {
            throw new Error("No companies found");
        }

        activeSymbol = companies[0].symbol;
        compareSymbol = companies.find((c) => c.symbol !== activeSymbol)?.symbol || activeSymbol;
        hydrateCompareDropdown();
        renderCompanyList();
        updateMarketBreadth(companies);
        await updateDashboard(activeSymbol);
    } catch (error) {
        console.error(error);
        alert(`Unable to load stock data. ${error.message}`);
    }

    setupSearch();
    setupCompareListener();
}

function hydrateCompareDropdown() {
    const select = document.getElementById("compareSelect");
    select.innerHTML = companies
        .map((company) => `<option value="${company.symbol}">${company.name} (${company.symbol})</option>`)
        .join("");

    if (compareSymbol) {
        select.value = compareSymbol;
    }
}

function renderCompanyList(filterTerm = "") {
    const list = document.getElementById('companyList');
    const listCard = document.getElementById('listCard');
    const viewAllBtn = document.getElementById('viewAllBtn');
    const normalized = filterTerm.trim().toUpperCase();
    const hasSearch = Boolean(normalized);

    const filtered = companies.filter((company) => {
        if (!normalized) {
            return true;
        }
        return (
            company.symbol.toUpperCase().includes(normalized) ||
            company.name.toUpperCase().includes(normalized)
        );
    });

    const ranked = filtered
        .slice()
        .sort((a, b) => Number(b.latest_daily_return || 0) - Number(a.latest_daily_return || 0));

    const visible = (!isListExpanded && !hasSearch)
        ? ranked.slice(0, COLLAPSED_CARD_COUNT)
        : ranked;

    const canExpand = !hasSearch && ranked.length > COLLAPSED_CARD_COUNT;
    if (listCard) {
        listCard.classList.toggle('expanded', isListExpanded && canExpand);
    }
    if (viewAllBtn) {
        viewAllBtn.style.visibility = canExpand ? 'visible' : 'hidden';
        viewAllBtn.textContent = isListExpanded ? 'Show Less' : 'View All';
    }

    list.innerHTML = visible.map(company => {
        const dailyReturn = Number(company.latest_daily_return || 0) * 100;
        const close = Number(company.latest_close || 0);
        return `
        <div class="stock-card glass ${company.symbol === activeSymbol ? 'selected' : ''}" 
              onclick="updateDashboard('${company.symbol}')">
            <div class="stock-left">
                <div class="stock-avatar">
                    ${company.symbol[0]}
                </div>
                <div>
                    <div class="stock-symbol">${company.symbol}</div>
                    <div class="stock-sector">${company.sector}</div>
                </div>
            </div>
            <div class="stock-right">
                <div class="stock-price">$${close.toFixed(2)}</div>
                <div class="stock-change ${dailyReturn >= 0 ? 'positive' : 'negative'}">
                    ${dailyReturn >= 0 ? 'UP' : 'DOWN'} ${Math.abs(dailyReturn).toFixed(2)}%
                </div>
            </div>
        </div>
    `;
    }).join('');

    syncListCardHeight();
}

function syncListCardHeight() {
    const listCard = document.getElementById('listCard');
    const chartCard = document.querySelector('.chart-card');
    if (!listCard || !chartCard) {
        return;
    }

    const isDesktop = window.matchMedia('(min-width: 1025px)').matches;
    if (!isDesktop || isListExpanded) {
        listCard.style.height = '';
        return;
    }

    const chartHeight = Math.ceil(chartCard.getBoundingClientRect().height);
    if (chartHeight > 0) {
        listCard.style.height = `${chartHeight}px`;
    }
}

function updateMarketBreadth(companyRows = []) {
    const advancersEl = document.getElementById('advancersCount');
    const declinersEl = document.getElementById('declinersCount');
    const avgMoveEl = document.getElementById('avgMove');
    const topMoverEl = document.getElementById('topMover');
    const meterFillEl = document.getElementById('breadthMeterFill');
    const noteEl = document.getElementById('breadthNote');
    const breadthBiasEl = document.getElementById('breadthBias');
    const advancerShareEl = document.getElementById('advancerShare');
    const flatShareEl = document.getElementById('flatShare');
    const declinerShareEl = document.getElementById('declinerShare');
    const advancerPctEl = document.getElementById('advancerPct');
    const flatPctEl = document.getElementById('flatPct');
    const declinerPctEl = document.getElementById('declinerPct');
    const sectorTiltEl = document.getElementById('sectorTilt');
    const breadthCoverageEl = document.getElementById('breadthCoverage');

    if (
        !advancersEl ||
        !declinersEl ||
        !avgMoveEl ||
        !topMoverEl ||
        !meterFillEl ||
        !noteEl ||
        !breadthBiasEl ||
        !advancerShareEl ||
        !flatShareEl ||
        !declinerShareEl ||
        !advancerPctEl ||
        !flatPctEl ||
        !declinerPctEl ||
        !sectorTiltEl ||
        !breadthCoverageEl
    ) {
        return;
    }

    if (!companyRows.length) {
        advancersEl.innerText = '0';
        declinersEl.innerText = '0';
        avgMoveEl.innerText = '0.00%';
        topMoverEl.innerText = '-';
        meterFillEl.style.width = '50%';
        noteEl.innerText = 'Neutral breadth';
        breadthBiasEl.innerText = 'Even Tape';
        advancerShareEl.style.width = '33.33%';
        flatShareEl.style.width = '33.34%';
        declinerShareEl.style.width = '33.33%';
        advancerPctEl.innerText = '0%';
        flatPctEl.innerText = '0%';
        declinerPctEl.innerText = '0%';
        sectorTiltEl.innerText = '-';
        breadthCoverageEl.innerText = '0 tracked';
        return;
    }

    const returns = companyRows.map((c) => Number(c.latest_daily_return || 0));
    const advancers = returns.filter((v) => v > 0).length;
    const decliners = returns.filter((v) => v < 0).length;
    const flat = Math.max(0, companyRows.length - advancers - decliners);
    const avgMovePct = (returns.reduce((sum, v) => sum + v, 0) / returns.length) * 100;

    const strongest = companyRows
        .slice()
        .sort((a, b) => Math.abs(Number(b.latest_daily_return || 0)) - Math.abs(Number(a.latest_daily_return || 0)))[0];

    const topMovePct = Number(strongest?.latest_daily_return || 0) * 100;
    const breadthPercent = Math.round((advancers / Math.max(1, advancers + decliners)) * 100);
    const advancerPct = Math.round((advancers / companyRows.length) * 100);
    const flatPct = Math.round((flat / companyRows.length) * 100);
    const declinerPct = Math.max(0, 100 - advancerPct - flatPct);
    const sectorScores = companyRows.reduce((scores, company) => {
        const sector = company.sector || 'Unclassified';
        scores[sector] = (scores[sector] || 0) + Number(company.latest_daily_return || 0);
        return scores;
    }, {});
    const leadingSector = Object.entries(sectorScores)
        .sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]))[0];

    advancersEl.innerText = String(advancers);
    declinersEl.innerText = String(decliners);
    avgMoveEl.innerText = `${avgMovePct >= 0 ? '+' : ''}${avgMovePct.toFixed(2)}%`;
    topMoverEl.innerText = strongest
        ? `${strongest.symbol} ${topMovePct >= 0 ? '+' : ''}${topMovePct.toFixed(2)}%`
        : '-';
    meterFillEl.style.width = `${breadthPercent}%`;
    advancerShareEl.style.width = `${Math.max(advancerPct, advancers ? 8 : 0)}%`;
    flatShareEl.style.width = `${Math.max(flatPct, flat ? 8 : 0)}%`;
    declinerShareEl.style.width = `${Math.max(declinerPct, decliners ? 8 : 0)}%`;
    advancerPctEl.innerText = `${advancerPct}%`;
    flatPctEl.innerText = `${flatPct}%`;
    declinerPctEl.innerText = `${declinerPct}%`;
    sectorTiltEl.innerText = leadingSector ? `${leadingSector[0]} ${leadingSector[1] >= 0 ? '+' : ''}${(leadingSector[1] * 100).toFixed(2)}%` : '-';
    breadthCoverageEl.innerText = `${companyRows.length} tracked`;

    if (advancers > decliners) {
        noteEl.innerText = 'Positive breadth across tracked symbols';
        breadthBiasEl.innerText = 'Risk-On Bias';
    } else if (decliners > advancers) {
        noteEl.innerText = 'Defensive session, declines outnumber gains';
        breadthBiasEl.innerText = 'Defensive Bias';
    } else {
        noteEl.innerText = 'Balanced breadth with mixed momentum';
        breadthBiasEl.innerText = 'Even Tape';
    }
}

async function updateDashboard(symbol) {
    activeSymbol = symbol;
    const company = companies.find(c => c.symbol === symbol);

    if (!company) {
        return;
    }

    if (compareSymbol === activeSymbol) {
        compareSymbol = companies.find((c) => c.symbol !== activeSymbol)?.symbol || activeSymbol;
        const compareSelect = document.getElementById("compareSelect");
        if (compareSelect) {
            compareSelect.value = compareSymbol;
        }
    }

    try {
        const [dataRes, summaryRes] = await Promise.all([
            apiGet(`/data/${symbol}?days=${currentTimeframe}`),
            apiGet(`/summary/${symbol}`),
        ]);

        let compareSeries = null;
        if (isComparisonMode && compareSymbol && compareSymbol !== symbol) {
            const compareRes = await apiGet(`/compare?symbol1=${symbol}&symbol2=${compareSymbol}&days=${currentTimeframe}`);
            compareSeries = compareRes.series2 || null;
        }

        document.getElementById('currentSymbol').innerText = symbol;
        document.getElementById('currentPrice').innerText = `$${Number(summaryRes.latest_close).toFixed(2)}`;
        document.getElementById('currentSector').innerText = company.sector;
        document.getElementById('currentCompSymbol').innerText = symbol;
        document.getElementById('52wHigh').innerText = `$${Number(summaryRes.high_52w).toFixed(2)}`;
        document.getElementById('52wLow').innerText = `$${Number(summaryRes.low_52w).toFixed(2)}`;
        document.getElementById('ma7').innerText = `$${Number(summaryRes.latest_ma7).toFixed(2)}`;
        document.getElementById('volatility').innerText = Number(summaryRes.volatility_score).toFixed(4);

        const changeValue = Number(summaryRes.latest_daily_return || 0) * 100;
        const changeEl = document.getElementById('currentChange');
        changeEl.innerText = `${changeValue >= 0 ? '+' : ''}${changeValue.toFixed(2)}%`;
        changeEl.className = `change-pill ${changeValue >= 0 ? 'positive' : 'negative'}`;

        renderChart(dataRes.points || [], dataRes.prediction || [], compareSeries);

        const refreshCompanyRes = await apiGet("/companies");
        companies = refreshCompanyRes.companies || companies;
        updateMarketBreadth(companies);
        renderCompanyList(document.getElementById("stockSearch").value);
    } catch (error) {
        console.error(error);
        alert(`Failed to load dashboard data from backend. ${error.message}`);
    }
}

function formatLabel(isoDate) {
    const date = new Date(isoDate);
    if (Number.isNaN(date.getTime())) {
        return isoDate;
    }
    return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}

function renderChart(points, prediction, compareSeries) {
    if (!points.length) {
        return;
    }

    const ctx = document.getElementById('mainChart').getContext('2d');

    if (chart) {
        chart.destroy();
    }

    const labels = points.map((d) => formatLabel(d.trade_date));
    const prices = points.map((d) => Number(d.close));

    const predictionPrices = [...prices];
    if (isPredictionVisible && prediction.length) {
        prediction.forEach((value, idx) => {
            predictionPrices.push(Number(value));
            labels.push(`Future ${idx + 1}`);
        });
    }

    const gradient = ctx.createLinearGradient(0, 0, 0, 400);
    gradient.addColorStop(0, 'rgba(59, 130, 246, 0.4)');
    gradient.addColorStop(1, 'rgba(59, 130, 246, 0)');

    const datasets = [
        {
            label: activeSymbol,
            data: prices,
            borderColor: '#3b82f6',
            borderWidth: 3,
            pointRadius: 0,
            pointHoverRadius: 6,
            fill: true,
            backgroundColor: gradient,
            tension: 0.4,
        },
    ];

    if (isPredictionVisible && prediction.length) {
        datasets.push({
            label: 'AI Forecast',
            data: predictionPrices,
            borderColor: '#a855f7',
            borderWidth: 2,
            borderDash: [5, 5],
            pointRadius: 0,
            fill: false,
            tension: 0.4,
        });
    }

    if (isComparisonMode && compareSeries && compareSeries.length) {
        datasets.push({
            label: compareSymbol,
            data: compareSeries.map((row) => Number(row.close)),
            borderColor: '#10b981',
            borderWidth: 2,
            pointRadius: 0,
            fill: false,
            tension: 0.4,
        });
    }

    chart = new Chart(ctx, {
        type: 'line',
        data: { labels, datasets },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false },
                tooltip: {
                    mode: 'index',
                    intersect: false,
                    backgroundColor: 'rgba(0,0,0,0.8)',
                    padding: 12,
                    titleFont: { size: 14, weight: 'bold' },
                    bodyFont: { size: 13 },
                    cornerRadius: 12,
                },
            },
            scales: {
                x: {
                    grid: { display: false },
                    ticks: { color: 'rgba(255,255,255,0.4)', maxRotation: 0 },
                },
                y: {
                    grid: { color: 'rgba(255,255,255,0.05)' },
                    ticks: {
                        color: 'rgba(255,255,255,0.4)',
                        callback: (value) => '$' + value,
                    },
                },
            },
        },
    });

    // Keep the list panel aligned after Chart.js finishes sizing the canvas.
    requestAnimationFrame(syncListCardHeight);
}

function updateTimeframe(days) {
    currentTimeframe = days;
    document.querySelectorAll('.time-btn').forEach(btn => {
        btn.classList.toggle('active', btn.innerText.includes(days));
    });
    updateDashboard(activeSymbol);
}

function togglePrediction() {
    isPredictionVisible = !isPredictionVisible;
    updateDashboard(activeSymbol);
}

function toggleCompare() {
    isComparisonMode = !isComparisonMode;
    document.getElementById('comparePanel').classList.toggle('hidden');
    updateDashboard(activeSymbol);
}

function setupCompareListener() {
    document.getElementById('compareSelect').addEventListener('change', (event) => {
        compareSymbol = event.target.value;
        if (isComparisonMode) {
            updateDashboard(activeSymbol);
        }
    });
}

function setupSearch() {
    document.getElementById('stockSearch').addEventListener('input', (e) => {
        isListExpanded = false;
        renderCompanyList(e.target.value);
    });
}

function viewAllCompanies() {
    const searchInput = document.getElementById('stockSearch');
    isListExpanded = !isListExpanded;
    if (searchInput) {
        searchInput.value = '';
    }
    renderCompanyList('');
}

window.onload = initDashboard;
window.addEventListener('resize', syncListCardHeight);
