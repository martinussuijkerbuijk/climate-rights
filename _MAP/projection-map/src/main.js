import './style.css';
import * as d3 from 'd3';
import 'd3-geo-projection';
import * as topojson from 'topojson-client';

// --- Map Configuration ---
const width = 1250 ;
const height = 700;
const worldJsonUrl = '/world-110m.json';
const climateDataUrl = '/climate_contours.geojson'; // Path to climate data
const baseScale = 120;

// --- DOM Selections ---
const infoBox = d3.select('#info-box');
// const infoCountryName = d3.select('#info-country-name');
// const infoTitle = d3.select('#info-title');
// const infoText = d3.select('#info-text');

// --- Create SVG Container ---
const svg = d3.create('svg')
    .attr('width', width)
    .attr('height', height)
    .attr('class', 'globe');

const g = svg.append('g');

// --- Define the Projection ---
const projection = d3.geoAzimuthalEquidistant()
    .scale(baseScale)
    .translate([width / 2, height / 2])
    .clipAngle(180 - 1e-3);

// const projection = d3.geoStereographic()
//     .scale(baseScale)
//     .translate([width / 2, height / 2])
//     .clipAngle(180 - 1e-3);

// const projection = d3.geoNaturalEarth1()
//     .scale(baseScale)
//     .translate([width / 2, height / 2])
//     .clipAngle(180 - 1e-3);


const pathGenerator = d3.geoPath(projection);

// --- Draw Initial Graticule and Sphere Outline ---
g.append('path')
    .datum(d3.geoGraticule10())
    .attr('class', 'graticule')
    .attr('d', pathGenerator);

g.append('path')
    .datum({ type: 'Sphere' })
    .attr('class', 'sphere')
    .attr('d', pathGenerator);

    // Create a group for the climate layer, initially empty
const climatePaths = g.append('g').attr('class', 'climate-layer');

//=======================================//
// --- Add a color scale for your climate data ---
// This example uses a color scale for temperature from blue (cold) to red (hot)
const colorScale = d3.scaleSequential(d3.interpolateRdYlBu)
    .domain([30, -10]); // Example: Domain from 30°C to -10°C. Adjust to your data.

// --- Load and Draw the Climate Data ---
// const climatePaths = g.append('g');

// d3.json('/climate_contours.geojson').then(climateData => {
//     climatePaths.selectAll('path')
//         .data(climateData.features)
//         .join('path')
//         // Apply a fill color based on the data value from the 'temp' attribute we created
//         .attr('fill', d => colorScale(d.properties.temp))
//         .attr('fill-opacity', 0.5) // Use opacity to see the landmasses underneath
//         .attr('d', pathGenerator);
// });

//======================================//

function redraw() {
    g.selectAll('path').attr('d', pathGenerator);
}

// --- Helper Function to Hide Info Box ---
function hideInfoBox() {
    infoBox.classed('opacity-100', false)
           .classed('opacity-0', true)
           .classed('invisible', true);
}

// --- Interaction (Drag/Zoom) ---
const drag = d3.drag()
    .on('start', hideInfoBox) // Hide box on drag start
    .on('drag', (event) => {
        const currentRotation = projection.rotate();
        const sensitivity = 0.25;
        const newRotation = [
            currentRotation[0] + event.dx * sensitivity,
            currentRotation[1] - event.dy * sensitivity,
            currentRotation[2]
        ];
        projection.rotate(newRotation);
        redraw();
    });

const zoom = d3.zoom()
    .scaleExtent([0.5, 15])
    .on('start', hideInfoBox) // Hide box on zoom start
    .on('zoom', (event) => {
        projection.scale(baseScale * event.transform.k);
        redraw();
    });

svg.call(drag).call(zoom);

// --- Data Loading and Animation Logic ---
let countries = [];
let climateData = null; // To cache the loaded climate data
let isClimateLayerVisible = false;
const countryPaths = g.append('g');

d3.json(worldJsonUrl).then(topology => {
    countries = topojson.feature(topology, topology.objects.countries).features;
    
    countryPaths.selectAll('path')
        .data(countries)
        .join('path')
        .attr('class', 'land')
        .attr('d', pathGenerator);

    d3.select('#country-select').property('disabled', false);
});

// --- Color Scale for Climate Data ---
const colorScaling = d3.scaleSequential(d3.interpolateRdYlBu).domain([30, -10]);


// --- Function to Toggle the Climate Layer ---
function toggleClimateLayer() {
    // If data is already loaded, just toggle visibility
    if (climateData) {
        isClimateLayerVisible = !isClimateLayerVisible;
        climatePaths.style('visibility', isClimateLayerVisible ? 'visible' : 'hidden');
        return;
    }

    // If data is not loaded, fetch it for the first time
    d3.json(climateDataUrl).then(data => {
        // Cache the data so we don't fetch it again
        climateData = data;
        isClimateLayerVisible = true;

        // Draw the climate paths
        climatePaths.selectAll('path')
            .data(climateData.features)
            .join('path')
            .attr('fill', d => colorScaling(d.properties.temp))
            .attr('fill-opacity', 0.5)
            .attr('d', pathGenerator);
    });
}

// Animation function
function flyTo(countryName) {
    // Hide the box before starting the transition
    hideInfoBox();

    const targetCountry = countries.find(c => c.properties.name === countryName);
    if (!targetCountry) return;
    
    countryPaths.selectAll('path')
        .attr('class', 'land')
        .filter(d => d.properties.name === countryName)
        .attr('class', 'active-country');

    const centroid = d3.geoCentroid(targetCountry);
    const targetRotation = [-centroid[0], -centroid[1]];
    const targetScale = 600;

    svg.transition()
        .duration(1000)
        .tween('zoomAndRotate', () => {
            const r = d3.interpolate(projection.rotate(), targetRotation);
            const s = d3.interpolate(projection.scale(), baseScale);
            return function(t) { projection.rotate(r(t)).scale(s(t)); redraw(); };
        })
        .transition()
        .duration(1000)
        .tween('zoomAndRotate', () => {
            const s = d3.interpolate(projection.scale(), targetScale);
            return function(t) { projection.scale(s(t)); redraw(); };
        })
        .on('end', () => {
            // Update the zoom behavior state
            const finalTransform = d3.zoomIdentity.scale(projection.scale() / baseScale);
            svg.call(zoom.transform, finalTransform);

            // Populate and show the info box
            infoCountryName.text(countryName);
            infoTitle.text("Placeholder Title");
            infoText.text("Lorem ipsum dolor sit amet, consectetur adipiscing elit. Sed do eiusmod tempor incididunt ut labore et dolore magna aliqua.");
            
            infoBox.classed('invisible', false)
                   .classed('opacity-0', false)
                   .classed('opacity-100', true);
        });
}

// Event listener for the dropdown
d3.select('#country-select').on('change', (event) => {
    const selectedCountry = event.currentTarget.value;
    if (selectedCountry) {
        flyTo(selectedCountry);
    }
});

// Add the click listener for our new button
d3.select('#toggle-climate-btn').on('click', toggleClimateLayer);

document.querySelector('#map-container').append(svg.node());