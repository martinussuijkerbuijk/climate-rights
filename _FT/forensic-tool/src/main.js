import * as d3 from 'd3';
import * as topojson from 'topojson-client';

// --- GLOBAL VARIABLES ---
let disasterData = [];
let caseData = [];
let chartInstance = null;
let allCountries = [];
let selectedCountry = 'Philippines'; // Default country
let dateSlider = null;
let worldGeoData = null; // For the country map

const caseDataUrl = 'CASES_COMBINED_status.csv';
const disasterDataUrl = 'public_emdat_custom_request_Natural.csv';
const worldJsonUrl = 'countries-50m.json';

// --- DATA LOADING ---
function loadData() {
    console.log("Starting to load data...");

    const disasterPromise = d3.csv(disasterDataUrl).then(data => {
        disasterData = data.map(d => ({
            ...d,
            'Start Year': parseInt(d['Start Year'], 10),
            'Total Deaths': d['Total Deaths'] ? parseInt(d['Total Deaths'], 10) : 0,
            'Total Affected': d['Total Affected'] ? parseInt(d['Total Affected'], 10) : 0,
            // 'Latitude': parseFloat(d['Latitude']),
            // 'Longitude': parseFloat(d['Longitude'])
        })).filter(d => !isNaN(d['Start Year']) && !isNaN(d.Latitude) && !isNaN(d.Longitude));
        console.log("Disaster data processed.");
    });

    const casePromise = d3.csv(caseDataUrl).then(data => {
        caseData = data.map(c => ({
            ...c,
            'Filing Year': parseInt(c['Filing Year'], 10)
        })).filter(c => !isNaN(c['Filing Year']));
        console.log("Case data processed.");
    });

    const geoPromise = d3.json(worldJsonUrl).then(data => {
        worldGeoData = topojson.feature(data, data.objects.countries);
        console.log("Geospatial data processed.");
    });
    
    return Promise.all([disasterPromise, casePromise, geoPromise]);
}

// --- UI & CHART & MAP FUNCTIONS ---
function renderTimeline(events, containerId) {
    const timelineContainer = document.getElementById(containerId);
    timelineContainer.innerHTML = ''; // Clear previous entries

    if (events.length === 0) {
        timelineContainer.innerHTML = '<p style="color: #888; padding: 0.5rem;">No events found.</p>';
        return;
    }

    events.forEach(item => {
        const itemEl = document.createElement('div');
        itemEl.className = 'timeline-item';
        
        let dotHtml;
        if (item.type === 'disaster') {
            const size = item.dotSize || 4; // Use calculated size or a default
            const offset = size / 2;
            dotHtml = `<div class="dot bg-disaster" style="width: ${size}px; height: ${size}px; left: -${offset}px;"></div>`;
        } else {
            // Litigation dots remain a fixed size
            const size = 8;
            const offset = size / 2;
            dotHtml = `<div class="dot bg-litigation" style="width: ${size}px; height: ${size}px; left: -${offset}px;"></div>`;
        }
        
        let statusLabel = '';
        if (item.type === 'litigation' && item.status) {
            statusLabel = `<span class="case-status">${item.status}</span>`;
        }

        itemEl.innerHTML = `
            ${dotHtml}
            <div class="timeline-content">
                <p class="year">${item.year}</p>
                <h4 class="title"><u>${item.title}</u> ${statusLabel}</h4>
                <h2 class="subtitle">${item.subtitle || ''}</h4>
                <p class="description">${item.description || ''}</p>
            </div>
        `;
        timelineContainer.appendChild(itemEl);
    });
}

function updateChart(disasters) {
    const disasterCounts = {};
    disasters.forEach(d => {
        const type = d['Disaster Type'];
        if (type) {
             disasterCounts[type] = (disasterCounts[type] || 0) + 1;
        }
    });

    const labels = Object.keys(disasterCounts);
    const data = Object.values(disasterCounts);

    if (chartInstance) {
        chartInstance.data.labels = labels;
        chartInstance.data.datasets[0].data = data;
        chartInstance.update();
    }
}

function renderCountryMap(countryName, disasters) {
    if (!worldGeoData) return;

    const container = d3.select('#country-map-container');
    container.html(''); // Clear previous map

    const width = container.node().getBoundingClientRect().width;
    const height = container.node().getBoundingClientRect().height;

    const svg = container.append('svg')
        .attr('width', width)
        .attr('height', height);

    const countryFeature = worldGeoData.features.find(f => f.properties.name === countryName);

    if (!countryFeature) {
        svg.append('text')
           .attr('x', width / 2)
           .attr('y', height / 2)
           .attr('text-anchor', 'middle')
           .attr('fill', 'var(--text-muted-color)')
           .text('Map data not available');
        return;
    }

    const projection = d3.geoMercator().fitSize([width, height], countryFeature);
    const path = d3.geoPath().projection(projection);

    // Draw all countries as a base layer
    svg.append('g')
        .selectAll('path')
        .data(worldGeoData.features)
        .join('path')
        .attr('d', path)
        .attr('fill', '#2a2a2a')
        .attr('stroke', '#0d0d0d');
    
    // Draw the highlighted country
    svg.append('path')
        .datum(countryFeature)
        .attr('d', path)
        .attr('fill', 'var(--accent-color)');

    // Draw disaster hotspots
    svg.append('g')
        .selectAll('circle')
        .data(disasters)
        .join('circle')
        .attr('cx', d => projection([d.Longitude, d.Latitude])[0])
        .attr('cy', d => projection([d.Longitude, d.Latitude])[1])
        .attr('r', 3)
        .attr('fill', '#000')
        .attr('stroke', '#ffffffff')
        .attr('stroke-width', 0.5)
        .attr('fill-opacity', 0.7);
}


 function initializeChart() {
    const ctx = document.getElementById('summaryChart');
    if (ctx) {
        Chart.defaults.color = '#aaa';
        Chart.defaults.borderColor = '#333';

        chartInstance = new Chart(ctx, {
            type: 'bar',
            data: {
                labels: [], // Initially empty
                datasets: [{
                    label: 'Event Count',
                    data: [], // Initially empty
                    backgroundColor: 'rgba(245, 11, 11, 0.6)',
                    borderColor: 'rgba(245, 11, 11, 1)',
                    borderWidth: 1
                }]
            },
            options: {
                indexAxis: 'y',
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { display: false }, title: { display: false } },
                scales: {
                    y: { beginAtZero: true, ticks: { color: '#aaa' }, grid: { color: '#333' } },
                    x: { ticks: { color: '#aaa' }, grid: { color: 'transparent' } }
                }
            }
        });
    }
}

function initializeDateSlider(minYear, maxYear) {
    const sliderElement = document.getElementById('date-range-slider');
    const dateLabel = document.getElementById('date-range-label');

    if (sliderElement.noUiSlider) {
        sliderElement.noUiSlider.destroy();
    }

    dateSlider = noUiSlider.create(sliderElement, {
        start: [minYear, maxYear],
        connect: true,
        range: {
            'min': minYear,
            'max': maxYear
        },
        step: 1,
        format: {
            to: value => Math.round(value),
            from: value => Number(value)
        }
    });

    dateSlider.on('update', (values) => {
        dateLabel.textContent = `${values[0]} - ${values[1]}`;
    });

    dateSlider.on('set', () => { 
        console.log("Slider 'set' event fired. Triggering dashboard update.");
        updateDashboard();
    });
}

// --- MAIN LOGIC ---
function updateDashboard() {
    if (!dateSlider) {
        console.log("updateDashboard called but slider not ready. Bailing.");
        return;
    }

    const country = selectedCountry;
    const disasterType = document.getElementById('disaster-type').value;
    const [startYear, endYear] = dateSlider.get();
    
    console.log(`Updating dashboard for ${country}, years: ${startYear} - ${endYear}`);

    document.querySelector('#timeline-panel .panel-header').textContent = `EVENT TIMELINE: ${country}`;

    // Filter disaster data
    let filteredDisasters = disasterData.filter(d =>
        d.Country === country &&
        d['Start Year'] >= startYear &&
        d['Start Year'] <= endYear
    );

    if (disasterType !== 'All Types') {
        filteredDisasters = filteredDisasters.filter(d => d['Disaster Type'] === disasterType);
    }
    
    // Filter litigation data
    const filteredCases = caseData.filter(c => 
        c.Jurisdictions && c.Jurisdictions.includes(country) &&
        c['Filing Year'] >= startYear &&
        c['Filing Year'] <= endYear
    );
    
    console.log(`Found ${filteredDisasters.length} disasters and ${filteredCases.length} cases.`);

    // Update counts in the timeline headers
    document.getElementById('disaster-count-display').textContent = filteredDisasters.length;
    document.getElementById('cases-count-display').textContent = filteredCases.length;

    // Create a scale for disaster dot sizes
    const maxAffected = d3.max(filteredDisasters, d => d['Total Affected']);
    const sizeScale = d3.scaleSqrt().domain([0, maxAffected]).range([8, 25]); // min 4px, max 20px

    // Format for timelines
    const disasterEvents = filteredDisasters.map(d => ({
        year: d['Start Year'],
        type: 'disaster',
        title: d['Event Name'] || d['Disaster Type'],
        subtitle: d['Disaster Subtype'],
        description: `A ${d['Disaster Type']} event affecting ${d['Total Affected'] ? d['Total Affected'].toLocaleString() : 'N/A'} people. Reported deaths: ${d['Total Deaths'] || 'N/A'}.`,
        dotSize: sizeScale(d['Total Affected'])
    })).sort((a, b) => b.year - a.year);

    const caseEvents = filteredCases.map(c => ({
        year: c['Filing Year'],
        type: 'litigation',
        title: c['Case Name'],
        status: c['Status'],
        subtitle: c['Extracted Climate Issue'],
        description: c.Description
    })).sort((a, b) => b.year - a.year);

    renderTimeline(disasterEvents, 'disaster-timeline');
    renderTimeline(caseEvents, 'cases-timeline');
    updateChart(filteredDisasters);
    renderCountryMap(country, filteredDisasters);
}

function renderAutocomplete(countries) {
    const autocompleteContainer = document.getElementById('autocomplete-results');
    autocompleteContainer.innerHTML = '';
    countries.forEach(country => {
        const item = document.createElement('div');
        item.className = 'autocomplete-item';
        item.textContent = country;
        item.addEventListener('click', () => {
            selectedCountry = country;
            document.getElementById('country-search').value = country;
            autocompleteContainer.innerHTML = '';
            updateDashboard();
        });
        autocompleteContainer.appendChild(item);
    });
}

function addEventListeners() {
    const searchInput = document.getElementById('country-search');

    document.getElementById('disaster-type').addEventListener('change', updateDashboard);

    searchInput.addEventListener('input', () => {
        const searchTerm = searchInput.value.toLowerCase();
        if (searchTerm.length > 0) {
            const matchedCountries = allCountries.filter(c => c.toLowerCase().startsWith(searchTerm));
            renderAutocomplete(matchedCountries);
        } else {
            document.getElementById('autocomplete-results').innerHTML = '';
        }
    });

    document.addEventListener('click', (e) => {
        if (!e.target.closest('.search-container')) {
            document.getElementById('autocomplete-results').innerHTML = '';
        }
    });
}

// --- APP START ---
loadData().then(() => {
    // Populate country list from data
    const disasterCountries = [...new Set(disasterData.map(d => d.Country))];
    const caseCountries = [...new Set(caseData.map(c => c.Jurisdictions).filter(Boolean))];
    allCountries = [...new Set([...disasterCountries, ...caseCountries])].sort();
    
    document.getElementById('country-search').value = selectedCountry;

    const disasterYears = disasterData.map(d => d['Start Year']);
    const caseYears = caseData.map(c => c['Filing Year']);
    const allYears = [...disasterYears, ...caseYears].filter(y => y);
    
    if (allYears.length === 0) {
        console.error("No valid year data found to initialize slider.");
        // Handle case with no data, e.g., show a message and disable slider
        document.getElementById('date-range-label').textContent = "No Data";
        document.getElementById('date-range-slider').setAttribute('disabled', true);
        return;
    }

    const minYear = Math.min(...allYears);
    const maxYear = Math.max(...allYears);

    initializeChart();
    initializeDateSlider(minYear, maxYear);
    addEventListeners();
    updateDashboard(); 
}).catch(error => {
    console.error("Error loading or parsing CSV data:", error);
    const timelinePanel = document.getElementById('timeline-panel');
    if (timelinePanel) {
         timelinePanel.innerHTML = `<p style="color: #ff6b6b; padding: 1rem;"><strong>Error:</strong> Could not load data files. Please ensure the CSV files are present in the correct folder and are not empty.</p>`;
    }
});

