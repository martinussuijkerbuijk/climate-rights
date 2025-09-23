import * as d3 from 'd3';
import * as topojson from 'topojson-client';
import { WindAnimator } from './wind.js'; // <-- IMPORT YOUR NEW MODULE

// --- Map Configuration ---
let keyboard = false;
const width = 2010;
const height = 1280;
const worldJsonUrl = 'https://unpkg.com/world-atlas@2/countries-110m.json';
const caseDataUrl = 'CASES_COMBINED_status.csv';
// NEW: Add the URL for your new disaster data CSV
const disasterDataUrl = 'public_emdat_custom_request_Natural.cvs';
const climateContoursUrl = 'sea_level_contours_qgis.topojson';
const baseScale = 200;
const windDataUrl = 'current-wind-surface-level-gfs-1.0.json'

// --- For chat WIndow ---
const chatWidget = document.getElementById('chatWidget');
// --- CHAT FUNCTIONALITY SCRIPT ---
const chatMessages = document.getElementById('chatMessages');
const promptInput = document.getElementById('promptInput');
const sendButton = document.getElementById('sendButton');
const closeChatButton = document.getElementById('chatCloseBtn');
const toggleChatButton = document.getElementById('chatToggleBtn');
const ChatFormButton = document.getElementById('chatForm');

const originalButtonContent = sendButton.innerHTML;

// Generate a unique session ID for this visit
const sessionId = crypto.randomUUID(); // <-- NEW


// --- Add new state variables ---
let windAnimator = null;
let isWindLayerVisible = false;
let windDataCache = null;

// NEW: State variables for the disaster layer
let allDisasterData = [];
let isDisasterLayerVisible = false;
let areDisastersLoaded = false;
let disasterColorScale;
let disasterCountColorScale;


// NEW: State for attractor loop
let userHasInteracted = false;
let rotationTimer = null;


// --- DOM Selections ---
const mapContainer = d3.select('#map-container');
const infoBox = d3.select('#info-box');
const infoCountryName = d3.select('#info-country-name');
const tooltip = d3.select('#tooltip');
const legendItems = d3.select('#legend-items');
const sliderContainer = d3.select('#slider-container');
const yearSlider = d3.select('#year-slider');
const yearLabel = d3.select('#year-label');
const countrySearchInput = d3.select('#country-search-input');
const countrySearchBtn = d3.select('#country-search-btn');
const autocompleteResults = d3.select('#autocomplete-results');

// NEW: DOM Selections for Timeline
const timelineContainer = d3.select('#timeline-container');
const timelineSvg = d3.select('#timeline-svg');
const timelineDetailPanel = d3.select('#timeline-detail-panel');
const timelineDetailContent = d3.select('#timeline-detail-content');
const timelineDetailClose = d3.select('#timeline-detail-close');
const attractorScreen = d3.select('#attractor-screen'); // NEW

// Related to country selection
let countries = [];
let caseColorScale;
let climateContourData = null;
let isClimateLayerVisible = false;
let areCasesLoaded = false;
let isCasesLayerVisible = false;
let allCasesData = [];
let activeStatusFilters = new Set();
let activeCategoryFilters = new Set();
let activeCountryName = null;

// Add these variables at the top with other state variables
let renderTimeout = null;
let isRendering = false;
let lastRenderTime = 0;
const RENDER_DEBOUNCE_MS = 150;
const MIN_RENDER_INTERVAL = 100;


// --- RASTER LAYER HANDLING ---
const rasterLayers = {
    emission: {
        id: 'emission',
        title: 'Emission Data',
        domain: [0.00, 0.21, 0.41, 0.62, 0.82, 1.03, 1.24, 1.44, 1.65, 1.85, 2.06],
        colors: ['black', '#1f1f1fff', '#696969ff', '#72838bff', '#6baed6', '#4292c6', '#2171b5', '#08519c', '#08306b', '#a50f6bff', '#d4009fff'],
        data: null,
        isVisible: false,
        dataCache: {} // Now a time-series layer
    },
    temperature: {
        id: 'temperature',
        title: 'Temperature Anomaly',
        domain: [-75., -52.5, -29.8, -7.2, 15.4, 38., 61.],
        colors: ['#34258fff', '#681a72ff', '#9d9e48ff', '#ccb21fff', '#e09524ff', '#eb1f00ff', '#570000ff'],
        data: null,
        isVisible: false,
        dataCache: {}
    },
    burn: {
        id: 'burn',
        title: 'Burned Area',
        domain: [1, 30, 60, 91, 122, 152, 183, 214, 244, 275, 305, 335, 365],
        colors: ['#ffffd4', '#fee391', '#fec44f', '#fe9929', '#ec7014', '#cc4c02', '#993404', '#662506'],
        data: null,
        isVisible: false,
        dataCache: {}
    },
    seaLevel: {
        id: 'seaLevel',
        title: 'Sea Level Anomaly',
        domain: [-1.5, - 1.25, -1.0, -0.75, -0.5, -0.25, 0.0, 0.25, 0.5, 0.75, 1., 1.25],
        colors: ['#053061', '#2166ac', '#4393c3', '#c197f8ff', '#d650ffff', '#e2abd6ff', '#9b9b9bff', '#f4a582', '#d3887cff', '#d15353ff','#f14e61ff', '#ff001eff'],
        data: null,
        isVisible: false,
        dataCache: {}
    }
};
let activeRasterLayerId = null;
let climateCanvas = null;
let climateCanvasContext = null;

// --- Chat Functions --- BEGIN
// --- CHAT WIDGET VISIBILITY ---
function toggleChat() {
    chatWidget.classList.toggle('open');
}

// Attach event listeners for opening and closing the chat
if (toggleChatButton) {
    toggleChatButton.addEventListener('click', toggleChat);
}
if (closeChatButton) {
    closeChatButton.addEventListener('click', toggleChat);
}

async function sendPrompt(event) {
    event.preventDefault(); // Prevents the form from reloading the page

    const promptText = promptInput.value.trim();
    if (!promptText) return;

    // --- Add User's Message to Chat ---
    addMessage(promptText, 'user-message');
    promptInput.value = ''; // Clear the input field

    // --- Show Loader and Disable Button ---
    sendButton.innerHTML = '<div class="loader"></div>';
    sendButton.disabled = true;

    // --- Prepare and Send Request ---
    const n8nWebhookUrl = 'https://martinus-suijkerbuijk.app.n8n.cloud/webhook/climate-cases'; // <-- ### YOUR N8N URL ###

    // Construct the data object to send, now including the sessionId
    const dataToSend = {
        prompt: promptText,
        sessionId: sessionId // <-- MODIFIED
    };

    // If activeCountryName has a value (is not null), add it to the data payload.
    if (activeCountryName) {
        dataToSend.country = activeCountryName;
    }

    else {
        activeCountryName = "United States of America"
    }

    try {
        const response = await fetch(n8nWebhookUrl, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(dataToSend),
        });

        if (!response.ok) {
            const errorText = await response.text();
            throw new Error(`Error: ${response.status} - ${errorText}`);
        }

        const data = await response.json();

        // --- ADD THIS LINE FOR DEBUGGING ---
        console.log('Received data from webhook:', data);

        // --- Add AI's Response to Chat ---
        if (Array.isArray(data) && data.length > 0 && data[0].data !== undefined) {
            addMessage(data[0].data, 'ai-message');
        } else {
            addMessage('Received an unexpected response format.', 'ai-message');
        }

    } catch (error) {
        console.error('Error sending prompt or processing response:', error);
        addMessage(`An error occurred: ${error.message}`, 'ai-message');
    } finally {
        // --- Restore Button ---
        sendButton.innerHTML = originalButtonContent;
        sendButton.disabled = false;
    }
}

// Attach event listener for form submission
if (ChatFormButton) {
    ChatFormButton.addEventListener('submit', sendPrompt);
}

function addMessage(content, className) {
    const messageDiv = document.createElement('div');
    messageDiv.classList.add('message', className);
    messageDiv.innerHTML = content; // Using innerHTML to render any HTML from the response
    chatMessages.appendChild(messageDiv);

    // Scroll to the latest message
    chatMessages.scrollTop = chatMessages.scrollHeight;
}

// --- Chat Functions --- END


function createClimateCanvas() {
    climateCanvas = d3.select('#map-container')
        .append('canvas')
        .attr('class', 'climate-canvas')
        .attr('width', width)
        .attr('height', height)
        .style('position', 'absolute')
        .style('top', 0)
        .style('left', 0)
        .style('width', '100%')
        .style('height', '100%')
        .style('pointer-events', 'none')
        .style('visibility', 'hidden')
        .style('z-index', -1);
    climateCanvasContext = climateCanvas.node().getContext('2d');
    climateCanvasContext.imageSmoothingEnabled = false;
    climateCanvasContext.globalCompositeOperation = 'source-over';
}

function debouncedRenderClimateRaster() {
    if (renderTimeout) {
        clearTimeout(renderTimeout);
    }
    const now = Date.now();
    const timeSinceLastRender = now - lastRenderTime;
    if (timeSinceLastRender < MIN_RENDER_INTERVAL) {
        renderTimeout = setTimeout(() => {
            renderClimateRasterCanvas();
        }, MIN_RENDER_INTERVAL - timeSinceLastRender);
    } else {
        renderTimeout = setTimeout(() => {
            renderClimateRasterCanvas();
        }, RENDER_DEBOUNCE_MS);
    }
}

function renderClimateRasterCanvas() {
    if (isRendering || !activeRasterLayerId || !rasterLayers[activeRasterLayerId].data || !climateCanvasContext) {
        return;
    }
    isRendering = true;
    lastRenderTime = Date.now();
    const layer = rasterLayers[activeRasterLayerId];
    const { ncols, nrows, xllcorner, yllcorner, cellsize, data: rawData } = layer.data;
    let dataArray = rawData || layer.data.values;
    if (!Array.isArray(dataArray)) {
        isRendering = false;
        return;
    }
    const colorScale = d3.scaleQuantize().domain(d3.extent(layer.domain)).range(layer.colors);
    climateCanvasContext.clearRect(0, 0, width, height);
    const scale = projection.scale();
    const cellSizePixels = Math.max(0.5, Math.min(8, scale / 100));
    const bounds = { left: -cellSizePixels, right: width + cellSizePixels, top: -cellSizePixels, bottom: height + cellSizePixels };
    const skipFactor = scale < 300 ? Math.max(1, Math.floor(500 / scale)) : 1;
    climateCanvasContext.globalAlpha = 0.7;
    for (let row = 0; row < nrows; row += skipFactor) {
        for (let col = 0; col < ncols; col += skipFactor) {
            const index = row * ncols + col;
            const value = dataArray[index];
            if (value === null || value === undefined || isNaN(value) || (activeRasterLayerId !== 'temperature' && activeRasterLayerId !== 'seaLevel' && value <= 0)) continue;
            const lon = xllcorner + col * cellsize;
            const lat = yllcorner + ((nrows - row - 0.5) * cellsize);
            const projected = projection([lon, lat]);
            if (!projected) continue;
            const [x, y] = projected;
            if (x < bounds.left || x > bounds.right || y < bounds.top || y > bounds.bottom) continue;

            climateCanvasContext.fillStyle = colorScale(value);

            if (activeRasterLayerId === 'burn') {
                climateCanvasContext.beginPath();
                const radius = Math.max(1, (cellSizePixels / 2) * skipFactor);
                climateCanvasContext.arc(Math.round(x), Math.round(y), radius, 0, 2 * Math.PI);
                climateCanvasContext.fill();
            } else {
                climateCanvasContext.fillRect(
                    Math.round(x - cellSizePixels / 2),
                    Math.round(y - cellSizePixels / 2),
                    Math.max(1, Math.round(cellSizePixels * skipFactor)),
                    Math.max(1, Math.round(cellSizePixels * skipFactor))
                );
            }
        }
    }
    isRendering = false;
    createAndUpdateLegends();
}


function createClimateRasterLegend(layer, colorScale) {
    const group = legendItems.append('div').attr('id', 'raster-legend-group');
    group.append('div').attr('class', 'text-sm font-semibold mb-2 text-white').text(layer.title);

    if (layer.id === 'burn') {
        const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
        const dayToMonth = (day) => {
            if (day <= 1) return months[0];
            const monthIndex = Math.floor((day - 1) / 30.4);
            return months[Math.min(monthIndex, 11)];
        };
        const legendData = layer.colors.map(color => {
            const extent = colorScale.invertExtent(color);
            const startMonth = dayToMonth(extent[0]);
            const endMonth = dayToMonth(extent[1]);
            let label = startMonth === endMonth ? startMonth : `${startMonth} - ${endMonth}`;
            if (extent[1] >= 365) label = `${startMonth} - Dec`;
            return { label, color };
        }).filter((d, i, self) => i === self.findIndex(t => t.label === d.label));
        const legendItemsElements = group.selectAll('.climate-legend-item').data(legendData).join('div').attr('class', 'climate-legend-item flex items-center mb-1');
        legendItemsElements.append('div').attr('class', 'w-4 h-4 mr-2').style('background-color', d => d.color);
        legendItemsElements.append('span').attr('class', 'text-white text-xs').text(d => d.label);
    } else {
        const legendData = layer.domain;
        const legendItemsElements = group.selectAll('.climate-legend-item').data(legendData).join('div').attr('class', 'climate-legend-item flex items-center mb-1');
        legendItemsElements.append('div').attr('class', 'w-4 h-4 mr-2').style('background-color', d => colorScale(d));
        legendItemsElements.append('span').attr('class', 'text-white text-xs').text(d => d.toFixed(2));
    }
}

function loadAndRenderEmissionData(year) {
    const layer = rasterLayers.emission;
    const cachedData = layer.dataCache[year];

    if (cachedData) {
        layer.data = cachedData;
        renderClimateRasterCanvas();
        return;
    }

    legendItems.html(`<div class="text-white text-sm">Loading emission data for ${year}...</div>`);
    const dataUrl = `emission/tropospheric_NO2_${year}-06-01.json`;

    d3.text(dataUrl).then(text => {
        const cleanedText = text.replace(/NaN/g, 'null');
        const data = JSON.parse(cleanedText);
        layer.dataCache[year] = data;
        layer.data = data;
        renderClimateRasterCanvas();
    }).catch(error => {
        console.error(`Error loading or parsing emission data for ${year}:`, error);
        legendItems.html(`<div class="text-white text-sm">Data not available for ${year}.</div>`);
        if (climateCanvasContext) climateCanvasContext.clearRect(0, 0, width, height);
    });
}

function toggleEmissionLayer() {
    stopAttractorLoop();
    const layer = rasterLayers.emission;

    if (!layer.isVisible) {
        if (rasterLayers.burn.isVisible) toggleBurnLayer();
        if (rasterLayers.temperature.isVisible) toggleTempLayer();
        if (rasterLayers.seaLevel.isVisible) toggleSeaLevelLayer();
    }

    layer.isVisible = !layer.isVisible;
    d3.select('#toggle-climate-raster-btn').classed('active', layer.isVisible);

    if (layer.isVisible) {
        activeRasterLayerId = 'emission';
        d3.select('#filter-cat2').property('checked', true);
        activeCategoryFilters.add('Emission');
        if (isCasesLayerVisible) updateMap();

        const yearRange = { min: 2018, max: 2025, default: 2019 };
        yearSlider.attr('min', yearRange.min).attr('max', yearRange.max).attr('value', yearRange.default);
        yearLabel.text(yearRange.default);
        sliderContainer.style('visibility', 'visible');
        if (!climateCanvas) createClimateCanvas();
        climateCanvas.style('visibility', 'visible');
        loadAndRenderEmissionData(yearRange.default);
    } else {
        activeRasterLayerId = null;
        d3.select('#filter-cat2').property('checked', false);
        activeCategoryFilters.delete('Emission');
        if (isCasesLayerVisible) updateMap();

        if (climateCanvas) climateCanvas.style('visibility', 'hidden');
        if (isCasesLayerVisible) {
            const years = allCasesData.map(d => +d['Filing Year']);
            yearSlider.attr('min', d3.min(years)).attr('max', d3.max(years));
            yearLabel.text(yearSlider.property('value'));
        } else {
            sliderContainer.style('visibility', 'hidden');
        }
        createAndUpdateLegends();
    }
    updateLegendVisibility();
}


function loadAndRenderTemperatureData(year) {
    const layer = rasterLayers.temperature;
    const cachedData = layer.dataCache[year];

    if (cachedData) {
        layer.data = cachedData;
        renderClimateRasterCanvas();
        return;
    }

    legendItems.html(`<div class="text-white text-sm">Loading temperature data for ${year}...</div>`);
    const dataUrl = `temp/surface_temp_${year}-06-01.json`;

    d3.text(dataUrl).then(text => {
        const cleanedText = text.replace(/NaN/g, 'null');
        const data = JSON.parse(cleanedText);
        layer.dataCache[year] = data;
        layer.data = data;
        renderClimateRasterCanvas();
    }).catch(error => {
        console.error(`Error loading or parsing temperature data for ${year}:`, error);
        legendItems.html(`<div class="text-white text-sm">Data not available for ${year}.</div>`);
        if (climateCanvasContext) climateCanvasContext.clearRect(0, 0, width, height);
    });
}

function toggleTempLayer() {
    stopAttractorLoop();
    const layer = rasterLayers.temperature;

    if (!layer.isVisible) {
        if (rasterLayers.burn.isVisible) toggleBurnLayer();
        if (rasterLayers.emission.isVisible) toggleEmissionLayer();
        if (rasterLayers.seaLevel.isVisible) toggleSeaLevelLayer();
    }

    layer.isVisible = !layer.isVisible;
    d3.select('#toggle-climate-btn').classed('active', layer.isVisible);

    if (layer.isVisible) {
        activeRasterLayerId = 'temperature';
        // d3.select('#filter-cat2').property('checked', true);
        // activeCategoryFilters.add('Emission');
        if (isCasesLayerVisible) updateMap();

        const yearRange = { min: 2015, max: 2025, default: 2025 };
        yearSlider.attr('min', yearRange.min).attr('max', yearRange.max).attr('value', yearRange.default);
        yearLabel.text(yearRange.default);
        sliderContainer.style('visibility', 'visible');
        if (!climateCanvas) createClimateCanvas();
        climateCanvas.style('visibility', 'visible');
        loadAndRenderTemperatureData(yearRange.default);
    } else {
        activeRasterLayerId = null;
        d3.select('#filter-cat2').property('checked', false);
        activeCategoryFilters.delete('Emission');
        if (isCasesLayerVisible) updateMap();

        if (climateCanvas) climateCanvas.style('visibility', 'hidden');
        if (isCasesLayerVisible) {
            const years = allCasesData.map(d => +d['Filing Year']);
            yearSlider.attr('min', d3.min(years)).attr('max', d3.max(years));
            yearLabel.text(yearSlider.property('value'));
        } else {
            sliderContainer.style('visibility', 'hidden');
        }
        createAndUpdateLegends();
    }
    updateLegendVisibility();
}


function loadAndRenderBurnData(year) {
    const layer = rasterLayers.burn;
    const cachedData = layer.dataCache[year];

    if (cachedData) {
        layer.data = cachedData;
        renderClimateRasterCanvas();
        return;
    }

    legendItems.html(`<div class="text-white text-sm">Loading burn data for ${year}...</div>`);
    const dataUrl = `burns/burned_area_${year}-01-01.json`;

    d3.text(dataUrl).then(text => {
        const cleanedText = text.replace(/NaN/g, 'null');
        const data = JSON.parse(cleanedText);

        layer.dataCache[year] = data;
        layer.data = data;
        renderClimateRasterCanvas();
    }).catch(error => {
        console.error(`Error loading or parsing burn data for ${year}:`, error);
        legendItems.html(`<div class="text-white text-sm">Data not available for ${year}.</div>`);
        if (climateCanvasContext) {
            climateCanvasContext.clearRect(0, 0, width, height);
        }
    });
}

function toggleBurnLayer() {
    stopAttractorLoop();
    const layer = rasterLayers.burn;

    if (!layer.isVisible) {
        if (rasterLayers.temperature.isVisible) toggleTempLayer();
        if (rasterLayers.emission.isVisible) toggleEmissionLayer();
        if (rasterLayers.seaLevel.isVisible) toggleSeaLevelLayer();
    }

    layer.isVisible = !layer.isVisible;
    d3.select('#toggle-burn-btn').classed('active', layer.isVisible);

    if (layer.isVisible) {
        activeRasterLayerId = 'burn';
        d3.select('#filter-cat1').property('checked', true);
        activeCategoryFilters.add('Fire');
        if (isCasesLayerVisible) updateMap();

        const yearRange = { min: 2015, max: 2025, default: 2025 };
        yearSlider.attr('min', yearRange.min).attr('max', yearRange.max).attr('value', yearRange.default);
        yearLabel.text(yearRange.default);
        sliderContainer.style('visibility', 'visible');
        if (!climateCanvas) createClimateCanvas();
        climateCanvas.style('visibility', 'visible');
        loadAndRenderBurnData(yearRange.default);
    } else {
        activeRasterLayerId = null;
        d3.select('#filter-cat1').property('checked', false);
        activeCategoryFilters.delete('Fire');
        if (isCasesLayerVisible) updateMap();

        if (climateCanvas) climateCanvas.style('visibility', 'hidden');
        if (isCasesLayerVisible) {
            const years = allCasesData.map(d => +d['Filing Year']);
            yearSlider.attr('min', d3.min(years)).attr('max', d3.max(years));
            yearLabel.text(yearSlider.property('value'));
        } else {
            sliderContainer.style('visibility', 'hidden');
        }
        createAndUpdateLegends();
    }
    updateLegendVisibility();
}

function loadAndRenderSeaLevelData(year) {
    const layer = rasterLayers.seaLevel;
    const cachedData = layer.dataCache[year];

    if (cachedData) {
        layer.data = cachedData;
        renderClimateRasterCanvas();
        return;
    }

    legendItems.html(`<div class="text-white text-sm">Loading sea level data for ${year}...</div>`);
    // NOTE: This URL is a placeholder based on the structure of other data URLs.
    // You may need to replace `sea_level/sea_level_anomaly_${year}-01-01.json` with the correct path.
    const dataUrl = `seaLevel/sea_level_anomaly_${year}-07-15.json`;

    d3.text(dataUrl).then(text => {
        const cleanedText = text.replace(/NaN/g, 'null');
        const data = JSON.parse(cleanedText);

        layer.dataCache[year] = data;
        layer.data = data;
        renderClimateRasterCanvas();
    }).catch(error => {
        console.error(`Error loading or parsing sea level data for ${year}:`, error);
        legendItems.html(`<div class="text-white text-sm">Data not available for ${year}.</div>`);
        if (climateCanvasContext) {
            climateCanvasContext.clearRect(0, 0, width, height);
        }
    });
}

function toggleSeaLevelLayer() {
    stopAttractorLoop();
    const layer = rasterLayers.seaLevel;

    // Deactivate other layers if this one is being activated
    if (!layer.isVisible) {
        if (rasterLayers.temperature.isVisible) toggleTempLayer();
        if (rasterLayers.emission.isVisible) toggleEmissionLayer();
        if (rasterLayers.burn.isVisible) toggleBurnLayer();
    }

    layer.isVisible = !layer.isVisible;
    d3.select('#toggle-sea-level-btn').classed('active', layer.isVisible);

    if (layer.isVisible) {
        activeRasterLayerId = 'seaLevel';
        if (isCasesLayerVisible) updateMap();

        const yearRange = { min: 2015, max: 2023, default: 2023 };
        yearSlider.attr('min', yearRange.min).attr('max', yearRange.max).attr('value', yearRange.default);
        yearLabel.text(yearRange.default);
        sliderContainer.style('visibility', 'visible');
        if (!climateCanvas) createClimateCanvas();
        climateCanvas.style('visibility', 'visible');
        loadAndRenderSeaLevelData(yearRange.default);
    } else {
        activeRasterLayerId = null;
        if (isCasesLayerVisible) updateMap();

        if (climateCanvas) climateCanvas.style('visibility', 'hidden');
        if (isCasesLayerVisible) {
            const years = allCasesData.map(d => +d['Filing Year']);
            yearSlider.attr('min', d3.min(years)).attr('max', d3.max(years));
            yearLabel.text(yearSlider.property('value'));
        } else {
            sliderContainer.style('visibility', 'hidden');
        }
        createAndUpdateLegends();
    }
    updateLegendVisibility();
}


function cleanupRasterResources() {
    if (renderTimeout) {
        clearTimeout(renderTimeout);
        renderTimeout = null;
    }
    isRendering = false;

    if (climateCanvasContext) {
        climateCanvasContext.clearRect(0, 0, width, height);
    }
}

window.addEventListener('beforeunload', cleanupRasterResources);

let elevationLevels = [];
let seaLevelColorScale = null;
const svg = mapContainer.append('svg').attr('width', '100%').attr('height', '100%').attr('viewBox', `0 0 ${width} ${height}`).attr('class', 'globe');
const defs = svg.append('defs');
const g = svg.append('g');
const projection = d3.geoAzimuthalEquidistant().scale(baseScale).translate([width / 2, height / 2]).clipAngle(180 - 1e-3);

d3.select(window).on('load', () => {
    windAnimator = new WindAnimator(projection, width, height);
});

const pathGenerator = d3.geoPath(projection);
g.append('path').datum({ type: 'Sphere' }).attr('class', 'sphere').attr('d', pathGenerator);
g.append('path').datum(d3.geoGraticule10()).attr('class', 'graticule').attr('d', pathGenerator);
const countryPaths = g.append('g').attr('class', 'country-paths');
const climateLayer = g.append('g').attr('class', 'climate-layer').style('visibility', 'hidden');
// NEW: Add an SVG group for the disaster dots
const disasterLayer = g.append('g').attr('class', 'disaster-layer').style('visibility', 'hidden');



function hideInfoBox() {
    activeCountryName = null;
    infoBox.classed('opacity-100', false)
        .classed('opacity-0', true)
        .classed('invisible', true)
        .style('pointer-events', 'none');
    if (isCasesLayerVisible) {
        updateTimeline(allCasesData);
    }
}
function hideTooltip() { tooltip.classed('opacity-100', false).classed('opacity-0', true).classed('invisible', true); }
function clearLegend() { legendItems.selectAll('*').remove(); }

function updateLegendVisibility() {
    const legend = d3.select('#legend');
    const isAnyLayerVisible = isCasesLayerVisible || activeRasterLayerId || isWindLayerVisible || isDisasterLayerVisible;
    legend.style('visibility', isAnyLayerVisible ? 'visible' : 'hidden');
}

function toggleWindLayer() {
    stopAttractorLoop();
    isWindLayerVisible = !isWindLayerVisible;
    d3.select('#toggle-wind-btn').classed('active', isWindLayerVisible);

    if (isWindLayerVisible) {
        // if (rasterLayers.temperature.isVisible) toggleTempLayer();
        // if (rasterLayers.emission.isVisible) toggleEmissionLayer();
        // if (rasterLayers.burn.isVisible) toggleBurnLayer();
        // if (rasterLayers.seaLevel.isVisible) toggleSeaLevelLayer();

        sliderContainer.style('visibility', 'hidden');

        if (windDataCache) {
            windAnimator.start(windDataCache);
        } else {
            legendItems.html(`<div class="text-white text-sm">Loading wind data...</div>`);
            d3.json(windDataUrl).then(data => {
                windDataCache = data;
                windAnimator.start(windDataCache);
            }).catch(error => {
                console.error("Error loading wind data:", error);
                legendItems.html(`<div class="text-white text-sm">Could not load wind data.</div>`);
            });
        }
    } else {
        windAnimator.stop();
    }
    updateLegendVisibility();
}

function updateTimeline(caseData) {
    timelineSvg.selectAll('*').remove();
    const timelineHeight = 160;
    const timelineWidth = timelineContainer.node().getBoundingClientRect().width;
    const margin = { top: 20, right: 40, bottom: 30, left: 40 };
    const width = timelineWidth - margin.left - margin.right;
    const height = timelineHeight - margin.top - margin.bottom;

    const svg = timelineSvg
        .append('g')
        .attr('transform', `translate(${margin.left}, ${margin.top})`);
    
    const x = d3.scaleLinear()
        .domain([1986, 2025])
        .range([0, width]);

    const xAxis = d3.axisBottom(x).ticks(10).tickFormat(d3.format("d"));

    svg.append('g')
        .attr('class', 'axis')
        .attr('transform', `translate(0, ${height})`)
        .call(xAxis);

    // --- NEW: Calculate cumulative cases over the years ---
    const countsByYear = d3.rollup(caseData, v => v.length, d => +d['Filing Year']);
    const sortedYears = Array.from(countsByYear.keys()).sort(d3.ascending);

    let cumulativeCount = 0;
    const cumulativeData = sortedYears
        .filter(year => year >= 1986 && year <= 2025) // Ensure data is within the domain
        .map(year => {
            cumulativeCount += countsByYear.get(year);
            return { year: year, count: cumulativeCount };
        });

    // --- NEW: Create a Y scale for the cumulative count ---
    const y = d3.scaleLinear()
        .domain([0, d3.max(cumulativeData, d => d.count)])
        .range([height, 0]);

    // --- NEW: Define and draw the area graph ---
    const area = d3.area()
        .x(d => x(d.year))
        .y0(height)
        .y1(d => y(d.count))
        .curve(d3.curveMonotoneX); // Smooths the line

    svg.append("path")
        .datum(cumulativeData)
        .attr("fill", "rgba(255, 38, 38, 0.18)") // A semi-transparent red
        // .attr("stroke", "rgba(255, 124, 124, 0.5)")
        .attr("stroke-width", 1.5)
        .attr("d", area);
    // --- End of new code ---

    svg.selectAll('.timeline-dot')
        .data(caseData.filter(d => d['Filing Year'] >= 1986 && d['Filing Year'] <= 2025))
        .join('circle')
        .attr('class', 'timeline-dot')
        .attr('cx', d => x(+d['Filing Year']) + (Math.random() * 50 - 20)) // Reduced random scatter
        .attr('cy', height / 2 + (Math.random() * 40 - 20))
        .attr('r', 3)
        .on('click', (event, d) => {
            d3.select('main').classed('detail-panel-visible', true);
            timelineDetailPanel.classed('visible', true);
            timelineDetailContent.html(`
                <h4>${d['Case Name']}</h4>
                <p><strong>ID:</strong> ${d.ID}</p>
                <p><strong>Jurisdiction:</strong> ${d.Jurisdictions}</p>
                <p><strong>Status:</strong> ${d.Status}</p>
                <div class="description">
                    <p>${d.Description || 'Not available.'}</p>
                </div>
            `);
        });
}


function renderInfoBoxContent() {
    if (!activeCountryName) {
        return;
    }

    const contentDiv = d3.select('#info-box-content');
    contentDiv.html('');

    const selectedYear = yearSlider.property('value');
    let countryCases = allCasesData.filter(d =>
        d.Jurisdictions === activeCountryName &&
        d['Filing Year'] <= selectedYear
    );

    if (activeStatusFilters.size > 0) {
        countryCases = countryCases.filter(d => activeStatusFilters.has(d.Status));
    }

    if (activeCategoryFilters.size > 0) {
        countryCases = countryCases.filter(d => {
            const issueText = d['Extracted Climate Issue']?.toLowerCase() || '';
            return Array.from(activeCategoryFilters).some(keyword => issueText.includes(keyword.toLowerCase()));
        });
    }

    if (countryCases.length > 0) {
        const table = contentDiv.append('table');
        const thead = table.append('thead').append('tr');
        const columnsToShow = ['Case Name', 'Filing Year', 'Status', 'Extracted Climate Issue'];

        columnsToShow.forEach(col => thead.append('th').text(col));

        const tbody = table.append('tbody');
        countryCases.forEach(caseData => {
            const row = tbody.append('tr');

            // row.on('mouseover', function(event) {
            //     tooltip.html(caseData.Description || 'No description available.')
            //         .classed('invisible', false)
            //         .classed('opacity-0', false)
            //         .classed('opacity-100', true)
            //         .style('z-index', 1001);
            // })
            // .on('mousemove', function(event) {
            //     const [x, y] = d3.pointer(event, mapContainer.node());
            //     tooltip.style('left', `${x + 15}px`).style('top', `${y}px`);
            // })
            // .on('mouseout', function() {
            //     hideTooltip();
            // });

            columnsToShow.forEach(col => {
                row.append('td').text(caseData[col] || 'N/A');
            });
        });
    } else {
        contentDiv.append('p').text('No case data available for this country based on current filters.');
    }
}


function updateMap() {
    if (!areCasesLoaded) {
        return;
    }
    const selectedYear = yearSlider.property('value');
    yearLabel.text(selectedYear);
    let filteredCases = allCasesData.filter(d => d['Filing Year'] <= selectedYear);

    if (activeStatusFilters.size > 0) {
        filteredCases = filteredCases.filter(d => activeStatusFilters.has(d.Status));
    }

    if (activeCategoryFilters.size > 0) {
        filteredCases = filteredCases.filter(d => {
            const issueText = d['Extracted Climate Issue']?.toLowerCase() || '';
            if (!issueText) return false;
            return Array.from(activeCategoryFilters).some(keyword => issueText.includes(keyword.toLowerCase()));
        });
    }

    const caseCountsMap = d3.rollup(filteredCases, v => v.length, d => d.Jurisdictions);
    countries.forEach(country => {
        const count = caseCountsMap.get(country.properties.name) || 0;
        country.properties.caseCount = count;
    });
    updateCountryStyles();
    renderInfoBoxContent();
}

function updateCountryStyles() {
    // Clear existing gradients from previous renders
    defs.selectAll('linearGradient').remove();

    countryPaths.selectAll('path')
        .each(function(d) {
            const countryPath = d3.select(this);
            const caseCount = d.properties.caseCount || 0;
            const disasterCount = d.properties.disasterCount || 0;
            
            let fillStyle = '#1b1b1b2c'; // Default grey fill

            if (isCasesLayerVisible && isDisasterLayerVisible) {
                if (caseCount > 0 && disasterCount > 0) {
                    const gradientId = `grad-${d.id}`;
                    const gradient = defs.append('linearGradient')
                        .attr('id', gradientId)
                        .attr('x1', '0%').attr('y1', '0%')
                        .attr('x2', '100%').attr('y2', '100%'); // Diagonal gradient

                    gradient.append('stop')
                        .attr('offset', '50%')
                        .attr('stop-color', caseColorScale(caseCount));
                    
                    gradient.append('stop')
                        .attr('offset', '50%')
                        .attr('stop-color', disasterCountColorScale(disasterCount));
                    
                    fillStyle = `url(#${gradientId})`;

                } else if (caseCount > 0) {
                    fillStyle = caseColorScale(caseCount);
                } else if (disasterCount > 0) {
                    fillStyle = disasterCountColorScale(disasterCount);
                }
            } else if (isCasesLayerVisible) {
                if (caseCount > 0) {
                    fillStyle = caseColorScale(caseCount);
                }
            } else if (isDisasterLayerVisible) {
                if (disasterCount > 0) {
                    fillStyle = disasterCountColorScale(disasterCount);
                }
            }

            countryPath.style('fill', fillStyle);
        });

    // Update common attributes and event handlers for all paths
    countryPaths.selectAll('path')
        .attr('class', d => (d.properties.caseCount > 0 && isCasesLayerVisible) || (d.properties.disasterCount > 0 && isDisasterLayerVisible) ? 'land interactive' : 'land non-interactive')
        .on('click', (event, d) => {
            const hasData = (d.properties.caseCount > 0 && isCasesLayerVisible) || (d.properties.disasterCount > 0 && isDisasterLayerVisible);
            if (!hasData) {
                event.stopPropagation();
                return;
            }
            event.stopPropagation();
            hideTooltip();
            flyTo(d.properties.name);
        })
        .on('mouseover', (event, d) => {
            const hasCases = d.properties.caseCount > 0 && isCasesLayerVisible;
            const hasDisasters = d.properties.disasterCount > 0 && isDisasterLayerVisible;
            if (!hasCases && !hasDisasters) return;

            let tooltipHtml = `<strong>${d.properties.name}</strong>`;
            if (hasCases) {
                tooltipHtml += `<br/>${d.properties.caseCount} cases`;
            }
            if (hasDisasters) {
                tooltipHtml += `<br/>${d.properties.disasterCount} disasters`;
            }
            tooltip.html(tooltipHtml)
                .classed('invisible', false).classed('opacity-0', false).classed('opacity-100', true).style('z-index', 1000);
        })
        .on('mousemove', (event) => {
            const [x, y] = d3.pointer(event, mapContainer.node());
            tooltip.style('left', `${x + 15}px`).style('top', `${y}px`);
        })
        .on('mouseout', hideTooltip);
}

function toggleCasesLayer() {
    stopAttractorLoop();
    d3.select('#toggle-cases-btn').classed('no-animation', true);
    isCasesLayerVisible = !isCasesLayerVisible;
    d3.select('#toggle-cases-btn').classed('active', isCasesLayerVisible);

    if (isCasesLayerVisible) {
        sliderContainer.style('visibility', 'visible');
        timelineContainer.style('visibility', 'visible');
        if (areCasesLoaded) {
            if (activeRasterLayerId !== 'burn' && activeRasterLayerId !== 'temperature' && activeRasterLayerId !== 'emission' && activeRasterLayerId !== 'seaLevel') {
                const years = allCasesData.map(d => +d['Filing Year']);
                yearSlider.attr('min', d3.min(years)).attr('max', d3.max(years));
            }
            updateMap();
            createAndUpdateLegends();
        } else {
            legendItems.html('<div class="text-white text-sm">Loading case data...</div>');
            d3.csv(caseDataUrl).then(data => {
                allCasesData = data;
                areCasesLoaded = true;
                const maxCases = d3.max(d3.rollup(allCasesData, v => v.length, d => d.Jurisdictions).values());
                caseColorScale = d3.scaleLog().domain([1, maxCases]).range(['#ff7c7c8c', '#eb0000c7']);

                if (activeRasterLayerId !== 'burn' && activeRasterLayerId !== 'temperature' && activeRasterLayerId !== 'emission' && activeRasterLayerId !== 'seaLevel') {
                    const years = allCasesData.map(d => +d['Filing Year']);
                    const minYear = d3.min(years);
                    const maxYear = d3.max(years);
                    yearSlider.attr('min', minYear).attr('max', maxYear).attr('value', maxYear);
                }
                updateMap();
                updateTimeline(allCasesData);
                createAndUpdateLegends();
            }).catch(error => {
                console.error("Error loading case data:", error);
                isCasesLayerVisible = false;
            });
        }
    } else {
        countries.forEach(c => c.properties.caseCount = 0); // Reset case count data
        updateCountryStyles();
        timelineContainer.style('visibility', 'hidden');
        timelineDetailPanel.classed('visible', false);
        if (!activeRasterLayerId && !isDisasterLayerVisible) {
            sliderContainer.style('visibility', 'hidden');
        } else if (activeRasterLayerId) {
            const layer = rasterLayers[activeRasterLayerId];
            if (layer.dataCache) {
                const yearRange = { min: 2015, max: 2025 };
                yearSlider.attr('min', yearRange.min).attr('max', yearRange.max);
                yearLabel.text(yearSlider.property('value'));
            }
        }
        createAndUpdateLegends();
    }
    updateLegendVisibility();
}


// --- NEW DISASTER LAYER FUNCTIONS ---

// This helper function updates the position of disaster dots during zoom/drag events.
function updateDisasterDotsPosition() {
    disasterLayer.selectAll('circle')
        .attr('transform', d => {
            const p = projection([d.Longitude, d.Latitude]);
            if (p) {
                // Hides dots that are on the far side of the globe
                const [x, y] = p;
                const [cx, cy] = projection.translate();
                const distance = d3.geoDistance([d.Longitude, d.Latitude], projection.invert([cx, cy]));
                if (distance > Math.PI / 2) {
                    return 'translate(-100,-100)'; // Effectively hide it
                }
                return `translate(${x}, ${y})`;
            }
            return 'translate(-100,-100)'; // Hide if not projectable
        });
}

// This function processes and renders the disaster data as dots on the map.
function renderDisasterDots(filteredDisasters) {
    if (!isDisasterLayerVisible || !areDisastersLoaded) return;

    // Define the color scale for disaster types
    const disasterTypes = ['Drought', 'Flood', 'Extreme temperature', 'Storm', 'Wildfire', 'Mass movement (wet)', 'Mass movement (dry)', 'Glacial lake outburst flood'];
    // Colorblind-friendly palette
    const colors = ['#e69f00', '#56b4e9', '#d55e00', '#009e73', '#cc79a7', '#0072b2', '#f0e442', '#999999'];
    disasterColorScale = d3.scaleOrdinal().domain(disasterTypes).range(colors);

    // Since we plot each disaster individually, we can use a fixed radius.
    const radius = 4;

    // Bind data and draw circles
    disasterLayer.selectAll('circle')
        .data(filteredDisasters, d => d['Dis No']) // Use filtered data and a unique ID
        .join('circle')
        .attr('r', radius)
        .attr('fill', d => disasterColorScale(d['Disaster Type']))
        .attr('fill-opacity', 0.7)
        .attr('stroke', 'rgba(255, 255, 255, 0.8)')
        .attr('stroke-width', 0.5)
        .style('cursor', 'pointer')
        .on('mouseover', (event, d) => {
            tooltip.html(`<strong>${d['Disaster Type']}</strong><br/>${d.Location || d.Country}<br/>Year: ${d['Start Year']}`)
                .classed('invisible', false).classed('opacity-0', false).classed('opacity-100', true);
        })
        .on('mousemove', (event) => {
            const [x, y] = d3.pointer(event, mapContainer.node());
            tooltip.style('left', `${x + 15}px`).style('top', `${y}px`);
        })
        .on('mouseout', hideTooltip);

    updateDisasterDotsPosition(); // Set the initial position of the dots
}

function updateDisasterVisualization() {
    if (!isDisasterLayerVisible || !areDisastersLoaded) return;

    const selectedYear = +yearSlider.property('value');
    yearLabel.text(selectedYear); // Keep slider label in sync

    const filteredDisasters = allDisasterData.filter(d => +d['Start Year'] <= selectedYear);

    // Update disaster counts on country properties
    const disasterCountsMap = d3.rollup(filteredDisasters, v => v.length, d => d.Country);
    countries.forEach(country => {
        country.properties.disasterCount = disasterCountsMap.get(country.properties.name) || 0;
    });

    renderDisasterDots(filteredDisasters);
    updateCountryStyles();
}

// This is the main function to toggle the disaster layer visibility.
function toggleDisasterLayer() {
    stopAttractorLoop();
    isDisasterLayerVisible = !isDisasterLayerVisible;
    d3.select('#toggle-disasters-btn').classed('active', isDisasterLayerVisible);

    if (isDisasterLayerVisible) {
        sliderContainer.style('visibility', 'visible');
        disasterLayer.style('visibility', 'visible');

        if (areDisastersLoaded) {
            if (!isCasesLayerVisible && !activeRasterLayerId) {
                yearSlider.attr('min', 2000).attr('max', 2025);
                yearLabel.text(yearSlider.property('value'));
            }
            updateDisasterVisualization();
            createAndUpdateLegends();
        } else {
            // First time loading the data
            d3.csv(disasterDataUrl).then(data => {
                const allowedDisasterTypes = new Set(['Drought', 'Flood', 'Extreme temperature', 'Storm', 'Wildfire', 'Mass movement (wet)', 'Mass movement (dry)', 'Glacial lake outburst flood']);

                // Filter for allowed types and entries with valid coordinates
                allDisasterData = data.filter(d =>
                    // d.Latitude && d.Longitude && allowedDisasterTypes.has(d['Disaster Type'])
                    allowedDisasterTypes.has(d['Disaster Type'])
                );
                
                areDisastersLoaded = true;
                
                // Create color scale for disaster counts
                const disasterCountsByCountry = d3.rollup(allDisasterData, v => v.length, d => d.Country);
                const maxDisasters = d3.max(disasterCountsByCountry.values());
                disasterCountColorScale = d3.scaleLog().domain([1, maxDisasters]).range(['#d0d1e6', '#ff5e00ff']);

                if (!isCasesLayerVisible && !activeRasterLayerId) {
                    yearSlider.attr('min', 2000).attr('max', 2025).attr('value', 2025);
                    yearLabel.text(2025);
                }

                updateDisasterVisualization();
                createAndUpdateLegends();

            }).catch(error => {
                console.error("Error loading disaster data:", error);
                isDisasterLayerVisible = false; // Revert state on error
                disasterLayer.style('visibility', 'hidden');
                d3.select('#toggle-disasters-btn').classed('active', false);
            });
        }
    } else {
        disasterLayer.style('visibility', 'hidden');
        countries.forEach(c => c.properties.disasterCount = 0); // Reset disaster count data
        updateCountryStyles();
        
        if (!isCasesLayerVisible && !activeRasterLayerId) {
            sliderContainer.style('visibility', 'hidden');
        }
        createAndUpdateLegends();
    }
    updateLegendVisibility();
}

// NEW: Function to create the disaster legend
function createDisasterLegend() {
    if (!disasterColorScale) return;

    const group = legendItems.append('div').attr('id', 'disaster-legend-group');
    group.append('div').attr('class', 'text-sm font-semibold mb-2 text-white mt-2').text('Disaster Types');

    const legendData = disasterColorScale.domain();
    const legendItemsElements = group.selectAll('.legend-item')
        .data(legendData)
        .join('div')
        .attr('class', 'legend-item flex items-center mb-1');

    legendItemsElements.append('div')
        .attr('class', 'w-4 h-4 mr-2 rounded-full') // Circle to match dots
        .style('background-color', d => disasterColorScale(d));

    legendItemsElements.append('span')
        .attr('class', 'text-white text-xs')
        .text(d => d);
}

function createDisasterCountLegend() {
    if (!disasterCountColorScale) return;

    const group = legendItems.append('div').attr('id', 'disaster-count-legend-group');
    group.append('div').attr('class', 'text-sm font-semibold mb-2 text-white mt-2').text('Disaster Count');
    const legendData = [1, 10, 50, 200]; // Example values, can be adjusted
    const legendItemsElements = group.selectAll('.legend-item').data(legendData).join('div').attr('class', 'legend-item flex items-center mb-1');
    legendItemsElements.append('div').attr('class', 'w-4 h-4 mr-2').style('background-color', d => disasterCountColorScale(d));
    legendItemsElements.append('span').attr('class', 'text-white text-xs').text(d => `${d}${d === 200 ? '+' : ''}`);
};

function createAndUpdateLegends() {
    clearLegend();
    if (activeRasterLayerId) {
        const layer = rasterLayers[activeRasterLayerId];
        const colorScale = d3.scaleQuantize().domain(d3.extent(layer.domain)).range(layer.colors);
        createClimateRasterLegend(layer, colorScale);
    }
    if (isCasesLayerVisible) {
        if (caseColorScale) {
            createClimateCasesLegend();
        }
    }
    // ADDED: Show disaster legend if layer is active
    if (isDisasterLayerVisible) {
        createDisasterLegend();
        createDisasterCountLegend();
    }
}


function destroyClimateLayer() {
    if (climateContourData) {
        climateLayer.selectAll('path').remove();
        climateContourData = null;
        isClimateLayerVisible = false;
        climateLayer.style('visibility', 'hidden');
        clearLegend();
    }
}
const drag = d3.drag()
    .on('start', () => {
        stopAttractorLoop();
        hideInfoBox();
        hideTooltip();
        destroyClimateLayer();
        if (climateCanvas && activeRasterLayerId) climateCanvas.style('opacity', '0.3');
        if (isWindLayerVisible) windAnimator.stop();
    })
    .on('drag', (event) => {
        const currentRotation = projection.rotate();
        const sensitivity = 0.25;
        const newRotation = [currentRotation[0] + event.dx * sensitivity, currentRotation[1] - event.dy * sensitivity];
        projection.rotate(newRotation);
        redraw();
    })
    .on('end', () => {
        if (climateCanvas && activeRasterLayerId) climateCanvas.style('opacity', '1');
        if (isWindLayerVisible && windDataCache) {
            windAnimator.updateProjection(projection);
            windAnimator.start(windDataCache);
        }
    });

const zoomStartHandler = () => {
    stopAttractorLoop();
    hideInfoBox();
    hideTooltip();
    destroyClimateLayer();
};

const zoom = d3.zoom()
    .scaleExtent([0.75, 15])
    .on('start', () => {
        stopAttractorLoop();
        hideInfoBox();
        hideTooltip();
        destroyClimateLayer();
        if (climateCanvas && activeRasterLayerId) climateCanvas.style('opacity', '0.3');
        if (isWindLayerVisible) windAnimator.stop();
    })
    .on('zoom', (event) => {
        projection.scale(baseScale * event.transform.k);
        redraw();
    })
    .on('end', () => {
        if (climateCanvas && activeRasterLayerId) {
            climateCanvas.style('opacity', '1');
            setTimeout(() => {
                if (activeRasterLayerId && rasterLayers[activeRasterLayerId].isVisible) {
                    renderClimateRasterCanvas();
                }
            }, 100);
        }
        if (isWindLayerVisible && windDataCache) {
            windAnimator.updateProjection(projection);
            windAnimator.start(windDataCache);
        }
    });

svg.call(drag).call(zoom);
svg.on('click', () => {
    hideInfoBox();
    autocompleteResults.html('');
});
const createClimateCasesLegend = () => {
    const group = legendItems.append('div').attr('id', 'cases-legend-group');
    group.append('div').attr('class', 'text-sm font-semibold mb-2 text-white mt-2').text('Climate Cases');
    const legendData = [1, 10, 100, 1000];
    const legendItemsElements = group.selectAll('.legend-item').data(legendData).join('div').attr('class', 'legend-item flex items-center mb-1');
    legendItemsElements.append('div').attr('class', 'w-4 h-4 mr-2').style('background-color', d => caseColorScale(d));
    legendItemsElements.append('span').attr('class', 'text-white text-xs').text(d => `${d}${d === 1000 ? '+' : ''}`);
};
function createElevationLegend() {
    clearLegend();
    legendItems.append('div').attr('class', 'text-sm font-semibold mb-2 text-white').text('Sea Level Rise (meters)');
    const displayLevels = elevationLevels.filter((_, index) => index % 2 === 0).reverse();
    const legendItemsElements = legendItems.selectAll('.elevation-legend-item').data(displayLevels).join('div').attr('class', 'elevation-legend-item flex items-center mb-1 text-xs');
    legendItemsElements.append('div').attr('class', 'w-4 h-4 mr-2 border border-gray-400').style('background-color', d => seaLevelColorScale(d.avg));
    legendItemsElements.append('span').attr('class', 'text-white').text(d => `${d.min.toFixed(2)}-${d.max.toFixed(2)}m`);
}

function redraw() {
    countryPaths.selectAll('path').attr('d', pathGenerator);

    if (isClimateLayerVisible && climateContourData) {
        climateLayer.selectAll('path').attr('d', pathGenerator);
    }

    // UPDATE: Redraw disaster dots on pan/zoom
    if (isDisasterLayerVisible && areDisastersLoaded) {
        updateDisasterDotsPosition();
    }

    g.selectAll('.sphere, .graticule').attr('d', pathGenerator);

    if (activeRasterLayerId && rasterLayers[activeRasterLayerId].isVisible) {
        debouncedRenderClimateRaster();
    }
}


function toggleClimateLayer() {
    isClimateLayerVisible = !isClimateLayerVisible;
    if (climateContourData) {
        climateLayer.style('visibility', isClimateLayerVisible ? 'visible' : 'hidden');
        if (isClimateLayerVisible) createElevationLegend();
        else clearLegend();
        return;
    }
    if (isClimateLayerVisible) {
        d3.json(climateContoursUrl).then(topojsonData => {
            climateContourData = topojson.feature(topojsonData, topojsonData.objects.contours);
            elevationLevels = climateContourData.features.map(d => ({ avg: (+d.properties.ELEV_MIN + +d.properties.ELEV_MAX) / 2, min: +d.properties.ELEV_MIN, max: +d.properties.ELEV_MAX, id: d.properties.ID })).sort((a, b) => a.avg - b.avg);
            seaLevelColorScale = d3.scaleQuantize().domain([elevationLevels[0].avg, elevationLevels[elevationLevels.length - 1].avg]).range(d3.quantize(d3.interpolateViridis, 20));
            const filteredFeatures = climateContourData.features.filter(d => ((+d.properties.ELEV_MIN + +d.properties.ELEV_MAX) / 2) >= 0.1);
            const sortedFeatures = filteredFeatures.sort((a, b) => (((+b.properties.ELEV_MIN + +b.properties.ELEV_MAX) / 2) - ((+a.properties.ELEV_MIN + +a.properties.ELEV_MAX) / 2)));
            climateLayer.selectAll('path').data(sortedFeatures).join('path').attr('class', 'climate-contour').attr('d', pathGenerator).style('fill', d => seaLevelColorScale((+d.properties.ELEV_MIN + +d.properties.ELEV_MAX) / 2)).style('fill-opacity', 0.7).style('stroke', 'none').style('pointer-events', 'none');
            climateLayer.style('visibility', 'visible');
            createElevationLegend();
        }).catch(error => {
            console.error("Error loading climate data:", error);
            isClimateLayerVisible = false;
        });
    } else {
        clearLegend();
    }
}


function flyTo(countryName) {
    if (!areCasesLoaded && isCasesLayerVisible) { // Ensure data is loaded before flying
        setTimeout(() => flyTo(countryName), 100);
        return;
    }

    activeCountryName = countryName;
    const targetCountry = countries.find(c => c.properties.name === countryName);

    if (!targetCountry) {
        console.error(`Could not find target country: ${countryName}`);
        return;
    }
    
    // Deselect any previously active country
    countryPaths.selectAll('.active-country').classed('active-country', false);
    // Select the new one
    countryPaths.selectAll('path')
      .filter(d => d.properties.name === countryName)
      .classed('active-country', true);

    if (isCasesLayerVisible) {
        const countryCases = allCasesData.filter(d => d.Jurisdictions === countryName);
        updateTimeline(countryCases);
    }


    const centroid = d3.geoCentroid(targetCountry);
    const targetRotation = [-centroid[0], -centroid[1]];
    const targetScale = 800;

    zoom.on('start', null);

    svg.transition()
        .duration(1250)
        .tween('zoomAndRotate', () => {
            const r = d3.interpolate(projection.rotate(), targetRotation);
            const s = d3.interpolate(projection.scale(), baseScale * 1.5);
            return function (t) { projection.rotate(r(t)).scale(s(t)); redraw(); };
        })
        .transition()
        .duration(1000)
        .tween('zoomIn', () => {
            const s = d3.interpolate(projection.scale(), targetScale);
            return function (t) { projection.scale(s(t)); redraw(); };
        })
        .on('end', () => {
            infoCountryName.text(targetCountry.properties.name);
            renderInfoBoxContent();

            infoBox.classed('invisible', false)
                .classed('opacity-0', false)
                .classed('opacity-100', true)
                .style('pointer-events', 'auto');

            const finalTransform = d3.zoomIdentity.scale(projection.scale() / baseScale);
            svg.call(zoom.transform, finalTransform);

            setTimeout(() => {
                zoom.on('start', zoomStartHandler);
            }, 100);
        });
}


d3.json(worldJsonUrl).then(topology => {
    countries = topojson.feature(topology, topology.objects.countries).features;
    countryPaths.selectAll('path').data(countries).join('path').attr('d', pathGenerator).attr('class', 'land non-interactive').style('fill', '#1b1b1b2c');
    startAttractorLoop(); // Start the animation
}).catch(error => {
    console.error("Error loading world geography:", error);
});

async function downloadSVG() {
    try {
        const response = await fetch('/src/style.css');
        const cssText = await response.text();
        const svgNode = svg.node();
        let svgString = new XMLSerializer().serializeToString(svgNode);
        const styleElement = `<style type="text/css"><![CDATA[${cssText}]]></style>`;
        svgString = svgString.replace('</svg>', `${styleElement}</svg>`);
        const fullSvg = `<?xml version="1.0" standalone="no"?>\r\n<!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1.1//EN" "http://www.w3.org/Graphics/SVG/1.1/DTD/svg11.dtd">\r\n${svgString}`;
        const blob = new Blob([fullSvg], { type: 'image/svg+xml;charset=utf-8' });
        const url = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = url;
        link.download = 'climate_rights_map.svg';
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        URL.revokeObjectURL(url);
    } catch (error) {
        console.error('Error downloading SVG:', error);
        alert('Could not download the map. See console for details.');
    }
}


d3.select('#toggle-climate-raster-btn').on('click', toggleEmissionLayer);
d3.select('#toggle-climate-btn').on('click', toggleTempLayer);
d3.select('#toggle-cases-btn').on('click', toggleCasesLayer);
d3.select('#toggle-burn-btn').on('click', toggleBurnLayer);
d3.select('#toggle-sea-level-btn').on('click', toggleSeaLevelLayer);
// NEW: Add event listener for the disaster button
d3.select('#toggle-disasters-btn').on('click', toggleDisasterLayer);


yearSlider.on('input', () => {
    const selectedYear = yearSlider.property('value');
    yearLabel.text(selectedYear);

    if (isCasesLayerVisible) {
        updateMap();
    }

    if (isDisasterLayerVisible) {
        updateDisasterVisualization();
    }

    if (activeRasterLayerId === 'burn') {
        loadAndRenderBurnData(selectedYear);
    } else if (activeRasterLayerId === 'temperature') {
        loadAndRenderTemperatureData(selectedYear);
    } else if (activeRasterLayerId === 'emission') {
        loadAndRenderEmissionData(selectedYear);
    } else if (activeRasterLayerId === 'seaLevel') {
        loadAndRenderSeaLevelData(selectedYear);
    }
});

d3.select('#info-box-close').on('click', hideInfoBox);
d3.select('#download-svg-btn').on('click', downloadSVG);


function searchAndFly() {
    const searchTerm = countrySearchInput.property('value').toLowerCase();
    if (!searchTerm) return;
    const matchedCountry = countries.find(c => c.properties.name.toLowerCase().startsWith(searchTerm));
    if (matchedCountry) {
        flyTo(matchedCountry.properties.name);
        countrySearchInput.property('value', '');
        autocompleteResults.html('');
    }
}
// Helper function to render the list of countries
function renderAutocompleteResults(countryList) {
    autocompleteResults.html(''); // Clear previous results

    // Sort the list alphabetically for better usability
    countryList.sort((a, b) => a.properties.name.localeCompare(b.properties.name));

    countryList.forEach(country => {
        autocompleteResults.append('div')
            .attr('class', 'autocomplete-item')
            .text(country.properties.name)
            .on('click', () => {
                flyTo(country.properties.name);
                countrySearchInput.property('value', '');
                autocompleteResults.html('');
            });
    });
}

// NEW: Attractor loop functions
function startAttractorLoop() {
    if (userHasInteracted) return;

    rotationTimer = d3.timer(elapsed => {
        const rotate = projection.rotate();
        const speed = 0.1; // Degrees per millisecond
        projection.rotate([rotate[0] + speed, rotate[1], rotate[2]]);
        redraw();
    });
}

function stopAttractorLoop() {
    if (userHasInteracted) return; // Only run once
    userHasInteracted = true;
    if (rotationTimer) rotationTimer.stop();
    attractorScreen.classed('hidden', true);
}


// The search button's main function remains the same
countrySearchBtn.on('click', searchAndFly);

d3.selectAll('.filter-group-header').on('click', function () {
    const header = d3.select(this);
    const content = d3.select(this.nextElementSibling);
    const isExpanded = header.classed('expanded');

    header.classed('expanded', !isExpanded);
    content.style('display', isExpanded ? 'none' : 'block');
});
d3.selectAll('input[name="status"]').on('change', function () {
    const checkbox = d3.select(this);
    const status = checkbox.property('value');
    const isChecked = checkbox.property('checked');
    if (isChecked) {
        activeStatusFilters.add(status);
    } else {
        activeStatusFilters.delete(status);
    }
    updateMap();
});

d3.selectAll('input[name="category"]').on('change', function () {
    const checkbox = d3.select(this);
    const keywords = checkbox.property('value').split('|');
    const isChecked = checkbox.property('checked');

    keywords.forEach(keyword => {
        if (isChecked) {
            activeCategoryFilters.add(keyword);
        } else {
            activeCategoryFilters.delete(keyword);
        }
    });

    updateMap();
});

// --- Global Control for Exhibition Mode ---

// This function contains the logic to set up search listeners based on the 'keyboard' flag.
function setupSearchInteractions() {
    // Clear any previous listeners to prevent them from stacking up
    countrySearchInput.on('input', null).on('keydown', null).on('click', null);

    if (keyboard) {
        // --- MODE 1: KEYBOARD AVAILABLE ---
        countrySearchInput.attr('readonly', null); // Ensure input is not read-only

        countrySearchInput.on('input', (event) => {
            const inputText = event.target.value.toLowerCase();
            if (inputText.length > 0) {
                const matched = countries.filter(c => c.properties.name.toLowerCase().startsWith(inputText));
                renderAutocompleteResults(matched);
            } else {
                autocompleteResults.html('');
            }
        });

        countrySearchInput.on('keydown', (event) => {
            if (event.key === 'Enter') {
                event.preventDefault();
                searchAndFly();
            }
        });

    } else {
        // --- MODE 2: NO KEYBOARD (Exhibition Mode) ---
        countrySearchInput.attr('readonly', true); // Make input read-only

        countrySearchInput.on('click', (event) => {
            event.stopPropagation();
            const isListVisible = autocompleteResults.node().hasChildNodes();
            if (isListVisible) {
                autocompleteResults.html('');
            } else {
                renderAutocompleteResults(countries);
            }
        });
    }
}

// NEW: Close timeline detail panel
timelineDetailClose.on('click', () => {
    d3.select('main').classed('detail-panel-visible', false);
    timelineDetailPanel.classed('visible', false);
});


// Near the end of main.js with other listeners
d3.select('#toggle-wind-btn').on('click', toggleWindLayer);

// Expose a function to the global window object to control the mode from the console
window.setKeyboardMode = function (hasKeyboard) {
    keyboard = !!hasKeyboard; // Ensure it's a true/false value
    console.log(`Keyboard mode has been set to: ${keyboard}`);
    setupSearchInteractions(); // Re-apply the correct event listeners
    // You might want to clear the search results when switching modes
    autocompleteResults.html('');
    countrySearchInput.property('value', '');
};

// Initial setup when the script loads for the first time
setupSearchInteractions();

