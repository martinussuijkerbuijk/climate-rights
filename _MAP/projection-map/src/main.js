import * as d3 from 'https://cdn.skypack.dev/d3@7';
import * as topojson from 'https://cdn.skypack.dev/topojson-client@3';
import 'https://cdn.skypack.dev/d3-geo-projection@4';

// --- Map Configuration ---
const width = 2010;
const height = 1275;
const worldJsonUrl = 'https://unpkg.com/world-atlas@2/countries-110m.json';
// IMPORTANT: Update this path to your CSV that includes the 'Status' column
const caseDataUrl = 'CASES_COMBINED_status.csv'; 
const climateContoursUrl = 'sea_level_contours_qgis.topojson'; 
const baseScale = 200; 

// --- DOM Selections ---
const mapContainer = d3.select('#map-container');
const infoBox = d3.select('#info-box');
const infoCountryName = d3.select('#info-country-name');
const infoTitle = d3.select('#info-title');
const infoText = d3.select('#info-text');
const tooltip = d3.select('#tooltip');
const legendItems = d3.select('#legend-items');
const sliderContainer = d3.select('#slider-container');
const yearSlider = d3.select('#year-slider');
const yearLabel = d3.select('#year-label');
const countrySearchInput = d3.select('#country-search-input');
const countrySearchBtn = d3.select('#country-search-btn');
const autocompleteResults = d3.select('#autocomplete-results');


// --- RASTER LAYER HANDLING (Unchanged) ---
// ... (code for raster layers is unchanged)
const rasterLayers = {
    emission: {
        id: 'emission',
        url: 'climate_data.json',
        title: 'Emission Data',
        domain: [0.00, 0.21, 0.41, 0.62, 0.82, 1.03, 1.24, 1.44, 1.65, 1.85, 2.06],
        colors: [
            '#f7fbff', '#deebf7', '#c6dbef', '#9ecae1', '#6baed6',
            '#4292c6', '#2171b5', '#08519c', '#08306b', '#a50f15', '#67000d'
        ],
        data: null,
        isVisible: false,
    },
    temperature: {
        id: 'temperature',
        url: 'surface_temp_20190701.json',
        title: 'Temperature Anomaly',
        domain: [205.0, 220., 240., 260., 280., 300., 320.],
        colors: ['#34258fff', '#681a72ff', '#9d9e48ff', '#ccb21fff', '#f0520eff', '#eb1f00ff', '#ff0000ff'],
        data: null,
        isVisible: false,
    }
};
let activeRasterLayerId = null; 
let climateCanvas = null;
let climateCanvasContext = null;
function loadClimateRasterData(layerId) {
    const layer = rasterLayers[layerId];
    if (!layer || !layer.url) {
        console.error("Invalid layer ID or URL for raster data:", layerId);
        return;
    }
    return d3.json(layer.url).then(data => {
        layer.data = data;
        if (!climateCanvas) {
            createClimateCanvas();
        }
    }).catch(error => {
        console.error(`Error loading ${layer.title} raster data:`, error);
    });
}
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
    climateCanvasContext.imageSmoothingEnabled = true;
}
function renderClimateRasterCanvas() {
    if (!activeRasterLayerId || !rasterLayers[activeRasterLayerId].data || !climateCanvasContext) return;
    const layer = rasterLayers[activeRasterLayerId];
    const { ncols, nrows, xllcorner, yllcorner, cellsize, data: rawData } = layer.data;
    let dataArray = rawData || layer.data.values;
    if (!Array.isArray(dataArray)) return;
    const colorScale = d3.scaleLinear().domain(layer.domain).range(layer.colors);
    climateCanvasContext.clearRect(0, 0, width, height);
    const cellSizePixels = Math.max(1, Math.ceil(projection.scale() / 200));
    for (let row = 0; row < nrows; row++) {
        for (let col = 0; col < ncols; col++) {
            const index = row * ncols + col;
            const value = dataArray[index];
            if (value === null || value === undefined || isNaN(value) || value === -9999) continue;
            const lon = xllcorner + col * cellsize;
            const lat = yllcorner + ((nrows - row - 0.5) * cellsize);
            const projected = projection([lon, lat]);
            if (!projected) continue;
            const [x, y] = projected;
            if (x < -cellSizePixels || x > width + cellSizePixels || y < -cellSizePixels || y > height + cellSizePixels) continue;
            climateCanvasContext.fillStyle = colorScale(value);
            climateCanvasContext.globalAlpha = 0.7;
            climateCanvasContext.fillRect(x - cellSizePixels / 2, y - cellSizePixels / 2, cellSizePixels, cellSizePixels);
        }
    }
    createClimateRasterLegend(layer, colorScale);
}
function createClimateRasterLegend(layer, colorScale) {
    clearLegend();
    legendItems.append('div').attr('class', 'text-sm font-semibold mb-2 text-white').text(layer.title);
    const legendData = colorScale.domain();
    const legendItemsElements = legendItems.selectAll('.climate-legend-item').data(legendData).join('div').attr('class', 'climate-legend-item flex items-center mb-1');
    legendItemsElements.append('div').attr('class', 'w-4 h-4 mr-2').style('background-color', d => colorScale(d));
    legendItemsElements.append('span').attr('class', 'text-white text-xs').text(d => d.toFixed(2));
}
function toggleRasterLayer(layerId) {
    const layer = rasterLayers[layerId];
    if (!layer) return;
    if (activeRasterLayerId === layerId) {
        layer.isVisible = false;
        activeRasterLayerId = null;
        climateCanvas.style('visibility', 'hidden');
        clearLegend();
        return;
    }
    if (activeRasterLayerId && rasterLayers[activeRasterLayerId]) {
        rasterLayers[activeRasterLayerId].isVisible = false;
    }
    activeRasterLayerId = layerId;
    layer.isVisible = true;
    if (!layer.data) {
        loadClimateRasterData(layerId).then(() => {
            climateCanvas.style('visibility', 'visible');
            renderClimateRasterCanvas();
        });
    } else {
        climateCanvas.style('visibility', 'visible');
        renderClimateRasterCanvas();
    }
}


// --- GENERAL MAP SETUP (Unchanged) ---
let elevationLevels = [];
let seaLevelColorScale = null;
const svg = mapContainer.append('svg').attr('width', '100%').attr('height', '100%').attr('viewBox', `0 0 ${width} ${height}`).attr('class', 'globe');
const g = svg.append('g');
const projection = d3.geoAzimuthalEquidistant().scale(baseScale).translate([width / 2, height / 2]).clipAngle(180 - 1e-3);
const pathGenerator = d3.geoPath(projection);
g.append('path').datum({ type: 'Sphere' }).attr('class', 'sphere').attr('d', pathGenerator);
g.append('path').datum(d3.geoGraticule10()).attr('class', 'graticule').attr('d', pathGenerator);
const countryPaths = g.append('g').attr('class', 'country-paths');
const climateLayer = g.append('g').attr('class', 'climate-layer').style('visibility', 'hidden');

// --- STATE VARIABLES ---
let countries = [];
let caseColorScale; 
let climateContourData = null;
let isClimateLayerVisible = false;
let areCasesLoaded = false;
let isCasesLayerVisible = false;
let allCasesData = [];
// NEW: A Set to store the active status filters
let activeStatusFilters = new Set();


// --- HELPER FUNCTIONS (Unchanged) ---
function hideInfoBox() { infoBox.classed('opacity-100', false).classed('opacity-0', true).classed('invisible', true); }
function hideTooltip() { tooltip.classed('opacity-100', false).classed('opacity-0', true).classed('invisible', true); }
function clearLegend() { legendItems.selectAll('*').remove(); }


// --- CASES LAYER & FILTERING LOGIC ---

// MODIFIED: This function is now the central point for all filtering.
function updateMap() {
    if (!areCasesLoaded) return;

    const selectedYear = yearSlider.property('value');
    yearLabel.text(selectedYear);

    // 1. Filter by Year
    let filteredCases = allCasesData.filter(d => d['Filing Year'] <= selectedYear);

    // 2. Filter by Status (if any statuses are selected)
    if (activeStatusFilters.size > 0) {
        filteredCases = filteredCases.filter(d => activeStatusFilters.has(d.Status));
    }

    // 3. Recalculate counts per country based on the final filtered list
    const caseCountsMap = d3.rollup(
        filteredCases,
        v => v.length,
        d => d.Jurisdictions
    );

    // Update the caseCount property for each country
    countries.forEach(country => {
        const count = caseCountsMap.get(country.properties.name) || 0;
        country.properties.caseCount = count;
    });

    // Re-style the countries on the map
    applyCaseStyles();
}


// applyCaseStyles and resetCountryStyles remain unchanged
function applyCaseStyles() {
    countryPaths.selectAll('path')
        .attr('class', d => d.properties.caseCount > 0 ? 'land interactive' : 'land non-interactive')
        .style('fill', d => {
            if (d.properties.caseCount > 0) return caseColorScale(d.properties.caseCount);
            return '#1b1b1bff';
        })
        .on('click', (event, d) => {
            if (d.properties.caseCount === 0) { event.stopPropagation(); return; }
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
        .style('fill', '#1b1b1b21')
        .on('click', null)
        .on('mouseover', null)
        .on('mousemove', null)
        .on('mouseout', null);
    hideTooltip();
}

// toggleCasesLayer now calls the main updateMap function
function toggleCasesLayer() {
    isCasesLayerVisible = !isCasesLayerVisible;
    if (!isCasesLayerVisible) {
        resetCountryStyles();
        clearLegend();
        sliderContainer.style('visibility', 'hidden'); 
        return;
    }
    sliderContainer.style('visibility', 'visible');
    if (areCasesLoaded) {
        updateMap();
        createClimateCasesLegend();
        return;
    }
    d3.csv(caseDataUrl).then(data => {
        allCasesData = data;
        const years = allCasesData.map(d => +d['Filing Year']);
        const minYear = d3.min(years);
        const maxYear = d3.max(years);
        yearSlider.attr('min', minYear).attr('max', maxYear).attr('value', maxYear);
        yearLabel.text(maxYear);
        const maxCases = d3.max(d3.rollup(allCasesData, v => v.length, d => d.Jurisdictions).values());
        caseColorScale = d3.scaleLog().domain([1, maxCases]).range(['#ff7c7c8c', '#eb0000c7']);
        areCasesLoaded = true;
        updateMap(); 
        createClimateCasesLegend();
    }).catch(error => {
        console.error("Error loading case data:", error);
        isCasesLayerVisible = false; 
    });
}


// --- INTERACTION & LEGENDS (Unchanged) ---
// ... (code for drag, zoom, legends, etc. is unchanged)
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
        if (climateCanvas) climateCanvas.style('visibility', 'hidden');
    })
    .on('drag', (event) => {
        const currentRotation = projection.rotate();
        const sensitivity = 0.25;
        const newRotation = [
            currentRotation[0] + event.dx * sensitivity,
            currentRotation[1] - event.dy * sensitivity,
        ];
        projection.rotate(newRotation);
        redraw();
    });
const zoom = d3.zoom()
    .scaleExtent([0.75, 15])
    .on('start', () => { 
        hideInfoBox(); 
        hideTooltip();
        destroyClimateLayer();
    })
    .on('zoom', (event) => {
        projection.scale(baseScale * event.transform.k);
        redraw();
    });
svg.call(drag).call(zoom);
svg.on('click', () => {
    hideInfoBox();
    autocompleteResults.html(''); // Also hide autocomplete on globe click
});
const createClimateCasesLegend = () => {
    clearLegend();
    legendItems.append('div').attr('class', 'text-sm font-semibold mb-2 text-white').text('Climate Cases');
    const legendData = [1, 10, 100, 1000];
    const legendItemsElements = legendItems.selectAll('.legend-item').data(legendData).join('div').attr('class', 'legend-item flex items-center mb-1');
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
        renderClimateRasterCanvas();
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
    hideInfoBox();
    const targetCountry = countries.find(c => c.properties.name === countryName);
    if (!targetCountry) return;
    countryPaths.selectAll('.active-country').classed('active-country', false).style('fill', d => caseColorScale(d.properties.caseCount));
    countryPaths.selectAll('path').filter(d => d.properties.name === countryName).classed('active-country', true).style('fill', null);
    const centroid = d3.geoCentroid(targetCountry);
    const targetRotation = [-centroid[0], -centroid[1]];
    const targetScale = 800;
    svg.transition().duration(1250).tween('zoomAndRotate', () => {
        const r = d3.interpolate(projection.rotate(), targetRotation);
        const s = d3.interpolate(projection.scale(), baseScale * 1.5);
        return function(t) { projection.rotate(r(t)).scale(s(t)); redraw(); };
    }).transition().duration(1000).tween('zoomIn', () => {
        const s = d3.interpolate(projection.scale(), targetScale);
        return function(t) { projection.scale(s(t)); redraw(); };
    }).on('end', () => {
        const finalTransform = d3.zoomIdentity.scale(projection.scale() / baseScale);
        svg.call(zoom.transform, finalTransform);
        infoCountryName.text(targetCountry.properties.name);
        infoTitle.text("Climate Case Information");
        infoText.text(`A total of ${targetCountry.properties.caseCount || 0} cases have been filed.`);
        const centerX = mapContainer.node().clientWidth / 2;
        const centerY = mapContainer.node().clientHeight / 2;
        infoBox.style('right', null).style('left', `${centerX + 100}px`).style('top', `${centerY}px`).style('transform', 'translateY(-50%)').style('z-index', 1000).classed('invisible', false).classed('opacity-0', false).classed('opacity-100', true);
    });
}


// --- INITIAL MAP DRAWING (Unchanged) ---
d3.json(worldJsonUrl).then(topology => {
    countries = topojson.feature(topology, topology.objects.countries).features;
    countryPaths.selectAll('path').data(countries).join('path').attr('d', pathGenerator).attr('class', 'land non-interactive').style('fill', '#1b1b1b2c');
}).catch(error => {
    console.error("Error loading world geography:", error);
});


// --- EVENT LISTENERS ---

d3.select('#toggle-climate-raster-btn').on('click', () => toggleRasterLayer('emission'));
d3.select('#toggle-climate-btn').on('click', () => toggleRasterLayer('temperature'));
d3.select('#toggle-cases-btn').on('click', toggleCasesLayer);

// MODIFIED: yearSlider now calls the main updateMap function
yearSlider.on('input', () => {
    updateMap();
});


// --- SEARCH AND AUTOCOMPLETE FUNCTIONALITY (Unchanged) ---
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
countrySearchInput.on('input', (event) => {
    const inputText = event.target.value.toLowerCase();
    autocompleteResults.html('');
    if (inputText.length > 0) {
        const matched = countries.filter(c => c.properties.name.toLowerCase().startsWith(inputText));
        matched.forEach(country => {
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
});
countrySearchBtn.on('click', searchAndFly);
countrySearchInput.on('keydown', (event) => {
    if (event.key === 'Enter') {
        event.preventDefault();
        searchAndFly();
    }
});

// --- NEW: FILTER PANEL FUNCTIONALITY ---

// Add click listeners to all filter group headers to toggle visibility
d3.selectAll('.filter-group-header').on('click', function() {
    // 'this' refers to the clicked header element
    const header = d3.select(this);
    header.classed('expanded', !header.classed('expanded'));
});

// Add change listeners to all status filter checkboxes
d3.selectAll('input[name="status"]').on('change', function() {
    // 'this' refers to the changed checkbox element
    const checkbox = d3.select(this);
    const status = checkbox.property('value');
    const isChecked = checkbox.property('checked');

    if (isChecked) {
        activeStatusFilters.add(status); // Add the status to our set
    } else {
        activeStatusFilters.delete(status); // Remove it
    }

    updateMap(); // Redraw the map with the new filters
});
