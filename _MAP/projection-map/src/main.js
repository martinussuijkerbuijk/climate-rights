import * as d3 from 'https://cdn.skypack.dev/d3@7';
import * as topojson from 'https://cdn.skypack.dev/topojson-client@3';
import 'https://cdn.skypack.dev/d3-geo-projection@4';
import { WindAnimator } from './wind.js'; // <-- IMPORT YOUR NEW MODULE

// --- Map Configuration ---
let keyboard = false;
const width = 2010;
const height = 1280;
const worldJsonUrl = 'https://unpkg.com/world-atlas@2/countries-110m.json';
const caseDataUrl = 'CASES_COMBINED_status.csv'; 
const climateContoursUrl = 'sea_level_contours_qgis.topojson'; 
const baseScale = 200; 
const windDataUrl = 'current-wind-surface-level-gfs-1.0.json'


// --- Add new state variables ---
let windAnimator = null;
let isWindLayerVisible = false;
let windDataCache = null;


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
    }
};
let activeRasterLayerId = null; 
let climateCanvas = null;
let climateCanvasContext = null;

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
            if (value === null || value === undefined || isNaN(value) || (activeRasterLayerId !== 'temperature' && value <= 0) ) continue;
            const lon = xllcorner + col * cellsize;
            const lat = yllcorner + ((nrows - row - 0.5) * cellsize);
            const projected = projection([lon, lat]);
            if (!projected) continue;
            const [x, y] = projected;
            if (x < bounds.left || x > bounds.right || y < bounds.top || y > bounds.bottom) continue;
            climateCanvasContext.fillStyle = colorScale(value);
            climateCanvasContext.fillRect(
                Math.round(x - cellSizePixels / 2), 
                Math.round(y - cellSizePixels / 2), 
                Math.max(1, Math.round(cellSizePixels * skipFactor)), 
                Math.max(1, Math.round(cellSizePixels * skipFactor))
            );
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
    const dataUrl = `emission/NO2_${year}-06-01.json`;

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
    const layer = rasterLayers.emission;
    
    if (!layer.isVisible) {
        if (rasterLayers.burn.isVisible) toggleBurnLayer();
        if (rasterLayers.temperature.isVisible) toggleTempLayer();
    }

    layer.isVisible = !layer.isVisible;
    d3.select('#toggle-climate-raster-btn').classed('active', layer.isVisible);

    if (layer.isVisible) {
        activeRasterLayerId = 'emission';
        d3.select('#filter-cat2').property('checked', true);
        activeCategoryFilters.add('Emission');
        if (isCasesLayerVisible) updateMap();
        
        const yearRange = { min: 2015, max: 2025, default: 2019 };
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
    const layer = rasterLayers.temperature;
    
    if (!layer.isVisible) {
        if (rasterLayers.burn.isVisible) toggleBurnLayer();
        if (rasterLayers.emission.isVisible) toggleEmissionLayer();
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
    const layer = rasterLayers.burn;

    if (!layer.isVisible) {
        if (rasterLayers.temperature.isVisible) toggleTempLayer();
        if (rasterLayers.emission.isVisible) toggleEmissionLayer();
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
const g = svg.append('g');
const projection = d3.geoAzimuthalEquidistant().scale(baseScale).translate([width / 2, height / 2]).clipAngle(180 - 1e-3);

// --- INITIALIZE THE WIND ANIMATOR ---
// It's good practice to do this after the page is loaded
d3.select(window).on('load', () => {
    windAnimator = new WindAnimator(projection, width, height);
});

const pathGenerator = d3.geoPath(projection);
g.append('path').datum({ type: 'Sphere' }).attr('class', 'sphere').attr('d', pathGenerator);
g.append('path').datum(d3.geoGraticule10()).attr('class', 'graticule').attr('d', pathGenerator);
const countryPaths = g.append('g').attr('class', 'country-paths');
const climateLayer = g.append('g').attr('class', 'climate-layer').style('visibility', 'hidden');

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

function hideInfoBox() { 
    activeCountryName = null; 
    infoBox.classed('opacity-100', false)
           .classed('opacity-0', true)
           .classed('invisible', true)
           .style('pointer-events', 'none'); 
}
function hideTooltip() { tooltip.classed('opacity-100', false).classed('opacity-0', true).classed('invisible', true); }
function clearLegend() { legendItems.selectAll('*').remove(); }

// --- CREATE THE TOGGLE FUNCTION ---
function toggleWindLayer() {
    isWindLayerVisible = !isWindLayerVisible;
    d3.select('#toggle-wind-btn').classed('active', isWindLayerVisible);

    if (isWindLayerVisible) {
        // Hide other layers for clarity
        if (rasterLayers.temperature.isVisible) toggleTempLayer();
        if (rasterLayers.emission.isVisible) toggleEmissionLayer();
        if (rasterLayers.burn.isVisible) toggleBurnLayer();
        
        sliderContainer.style('visibility', 'hidden');

        if (windDataCache) {
            windAnimator.start(windDataCache);
        } else {
            legendItems.html(`<div class="text-white text-sm">Loading wind data...</div>`);
            d3.json(windDataUrl).then(data => {
                // Simply store the raw data. The wind.js module will handle the rest.
                windDataCache = data; 
                
                windAnimator.start(windDataCache);
                createAndUpdateLegends(); // Clear the loading message
            }).catch(error => {
                console.error("Error loading wind data:", error);
                legendItems.html(`<div class="text-white text-sm">Could not load wind data.</div>`);
            });
        }
    } else {
        windAnimator.stop();
    }
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

            row.on('mouseover', function(event) {
                tooltip.html(caseData.Description || 'No description available.')
                    .classed('invisible', false)
                    .classed('opacity-0', false)
                    .classed('opacity-100', true)
                    .style('z-index', 1001);
            })
            .on('mousemove', function(event) {
                const [x, y] = d3.pointer(event, mapContainer.node());
                tooltip.style('left', `${x + 15}px`).style('top', `${y}px`);
            })
            .on('mouseout', function() {
                hideTooltip();
            });
            
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
    applyCaseStyles();
    renderInfoBoxContent(); 
}
function applyCaseStyles() {
    countryPaths.selectAll('path')
        .attr('class', d => d.properties.caseCount > 0 ? 'land interactive' : 'land non-interactive')
        .style('fill', d => {
            if (d.properties.caseCount > 0) return caseColorScale(d.properties.caseCount);
            return '#1b1b1b2c';
        })
        .on('click', (event, d) => {
            if (d.properties.caseCount === 0) { 
                event.stopPropagation(); 
                return; 
            }
            event.stopPropagation();
            hideTooltip();
            flyTo(d.properties.name);
        })
        .on('mouseover', (event, d) => {
            if (!d.properties.caseCount || d.properties.caseCount === 0) return;
            tooltip.html(`<strong>${d.properties.name}</strong><br/>${d.properties.caseCount} cases`)
                .classed('invisible', false).classed('opacity-0', false).classed('opacity-100', true).style('z-index', 1000);
        })
        .on('mousemove', (event) => {
            const [x, y] = d3.pointer(event, mapContainer.node());
            tooltip.style('left', `${x + 15}px`).style('top', `${y}px`);
        })
        .on('mouseout', hideTooltip);
}
function resetCountryStyles() {
    countryPaths.selectAll('path')
        .attr('class', 'land non-interactive')
        .style('fill', '#1b1b1b2c')
        .on('click', null)
        .on('mouseover', null)
        .on('mousemove', null)
        .on('mouseout', null);
    hideTooltip();
}
function toggleCasesLayer() {
    d3.select('#toggle-cases-btn').classed('no-animation', true);
    isCasesLayerVisible = !isCasesLayerVisible;
    d3.select('#toggle-cases-btn').classed('active', isCasesLayerVisible);

    if (isCasesLayerVisible) {
        sliderContainer.style('visibility', 'visible');
        if (areCasesLoaded) {
            if (activeRasterLayerId !== 'burn' && activeRasterLayerId !== 'temperature' && activeRasterLayerId !== 'emission') {
                const years = allCasesData.map(d => +d['Filing Year']);
                yearSlider.attr('min', d3.min(years)).attr('max', d3.max(years));
            }
            updateMap();
        } else {
            legendItems.html('<div class="text-white text-sm">Loading case data...</div>');
            d3.csv(caseDataUrl).then(data => {
                allCasesData = data;
                areCasesLoaded = true;
                const maxCases = d3.max(d3.rollup(allCasesData, v => v.length, d => d.Jurisdictions).values());
                caseColorScale = d3.scaleLog().domain([1, maxCases]).range(['#ff7c7c8c', '#eb0000c7']);
                
                if (activeRasterLayerId !== 'burn' && activeRasterLayerId !== 'temperature' && activeRasterLayerId !== 'emission') {
                    const years = allCasesData.map(d => +d['Filing Year']);
                    const minYear = d3.min(years);
                    const maxYear = d3.max(years);
                    yearSlider.attr('min', minYear).attr('max', maxYear).attr('value', maxYear);
                }
                updateMap();
            }).catch(error => {
                console.error("Error loading case data:", error);
                isCasesLayerVisible = false;
            });
        }
    } else {
        resetCountryStyles();
        if (!activeRasterLayerId) {
            sliderContainer.style('visibility', 'hidden');
        } else {
            const layer = rasterLayers[activeRasterLayerId];
             if(layer.dataCache) {
                const yearRange = { min: 2015, max: 2025 };
                yearSlider.attr('min', yearRange.min).attr('max', yearRange.max);
                yearLabel.text(yearSlider.property('value'));
             }
        }
    }
    createAndUpdateLegends();
}

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
        hideInfoBox(); 
        hideTooltip();
        destroyClimateLayer();
        if (climateCanvas && activeRasterLayerId) climateCanvas.style('opacity', '0.3');
        if (isWindLayerVisible) windAnimator.stop(); // Stop animation during drag
    })
    .on('drag', (event) => {
        const currentRotation = projection.rotate();
        const sensitivity = 0.25;
        const newRotation = [ currentRotation[0] + event.dx * sensitivity, currentRotation[1] - event.dy * sensitivity ];
        projection.rotate(newRotation);
        redraw();
    })
    .on('end', () => {
        if (climateCanvas && activeRasterLayerId) climateCanvas.style('opacity', '1');
        if (isWindLayerVisible && windDataCache) {
             windAnimator.updateProjection(projection); // Update with new projection
             windAnimator.start(windDataCache);      // Restart animation
        }
    });

const zoomStartHandler = () => {
    hideInfoBox();
    hideTooltip();
    destroyClimateLayer();
};

const zoom = d3.zoom()
    .scaleExtent([0.75, 15])
    .on('start', () => {
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
    // If cases aren't visible, turn them on first.
    if (!isCasesLayerVisible) {
        d3.select('#toggle-cases-btn').dispatch('click');
        // Use a short delay to allow the data loading to begin and the state to update.
        setTimeout(() => flyTo(countryName), 100);
        return;
    }

    activeCountryName = countryName; 
    const targetCountry = countries.find(c => c.properties.name === countryName);
    
    if (!targetCountry) {
        console.error(`Could not find target country: ${countryName}`);
        return;
    }

    // The key check: only reset colors if the scale is ready.
    if (typeof caseColorScale === 'function') {
        countryPaths.selectAll('.active-country')
          .classed('active-country', false)
          .style('fill', d => caseColorScale(d.properties.caseCount));
    } else {
        countryPaths.selectAll('.active-country').classed('active-country', false);
    }

    countryPaths.selectAll('path')
      .filter(d => d.properties.name === countryName)
      .classed('active-country', true)
      .style('fill', null);

    const centroid = d3.geoCentroid(targetCountry);
    const targetRotation = [-centroid[0], -centroid[1]];
    const targetScale = 800;

    zoom.on('start', null);

    svg.transition()
        .duration(1250)
        .tween('zoomAndRotate', () => {
            const r = d3.interpolate(projection.rotate(), targetRotation);
            const s = d3.interpolate(projection.scale(), baseScale * 1.5);
            return function(t) { projection.rotate(r(t)).scale(s(t)); redraw(); };
        })
        .transition()
        .duration(1000)
        .tween('zoomIn', () => {
            const s = d3.interpolate(projection.scale(), targetScale);
            return function(t) { projection.scale(s(t)); redraw(); };
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

yearSlider.on('input', () => {
    const selectedYear = yearSlider.property('value');
    yearLabel.text(selectedYear);

    if (isCasesLayerVisible) {
        updateMap();
    } 
    if (activeRasterLayerId === 'burn') { 
        loadAndRenderBurnData(selectedYear);
    } else if (activeRasterLayerId === 'temperature') {
        loadAndRenderTemperatureData(selectedYear);
    } else if (activeRasterLayerId === 'emission') {
        loadAndRenderEmissionData(selectedYear);
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


// The search button's main function remains the same
countrySearchBtn.on('click', searchAndFly);

d3.selectAll('.filter-group-header').on('click', function() {
    const header = d3.select(this);
    const content = d3.select(this.nextElementSibling);
    const isExpanded = header.classed('expanded');
    
    header.classed('expanded', !isExpanded);
    content.style('display', isExpanded ? 'none' : 'block');
});
d3.selectAll('input[name="status"]').on('change', function() {
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

d3.selectAll('input[name="category"]').on('change', function() {
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

// Near the end of main.js with other listeners
d3.select('#toggle-wind-btn').on('click', toggleWindLayer);

// Expose a function to the global window object to control the mode from the console
window.setKeyboardMode = function(hasKeyboard) {
    keyboard = !!hasKeyboard; // Ensure it's a true/false value
    console.log(`Keyboard mode has been set to: ${keyboard}`);
    setupSearchInteractions(); // Re-apply the correct event listeners
    // You might want to clear the search results when switching modes
    autocompleteResults.html('');
    countrySearchInput.property('value', '');
};

// Initial setup when the script loads for the first time
setupSearchInteractions();

