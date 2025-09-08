import * as d3 from 'https://cdn.skypack.dev/d3@7';
import * as topojson from 'https://cdn.skypack.dev/topojson-client@3';

// --- DOM Selections ---
const canvas = document.getElementById('map-canvas');
const startBtn = document.getElementById('start-recording-btn');
const downloadLink = document.getElementById('download-link');
const countriesInput = document.getElementById('countries-input');
const waitTimeInput = document.getElementById('wait-time-input');
const statusMessage = document.getElementById('status-message');

// --- Map & Animation Configuration (from main.js) ---
const width = 2010;
const height = 1280;
const baseScale = 200;
canvas.width = width;
canvas.height = height;
const context = canvas.getContext('2d');

const projection = d3.geoAzimuthalEquidistant()
    .scale(baseScale)
    .translate([width / 2, height / 2])
    .clipAngle(180 - 1e-3);

const path = d3.geoPath(projection, context);
const worldJsonUrl = 'https://unpkg.com/world-atlas@2/countries-110m.json';
const caseDataUrl = 'CASES_COMBINED_status.csv';

let countries = [];
let world = null;
let currentAnimationTimer = null;
let allCasesData = [];
let caseColorScale = null;
let caseCountsMap = null;


// --- Media Recorder State ---
let mediaRecorder;
let recordedChunks = [];

// --- Main Drawing Function (with styles from style.css) ---
function redraw() {
    context.clearRect(0, 0, width, height);

    // Draw Sphere (Ocean) - Matches map-container background
    context.beginPath();
    path({ type: 'Sphere' });
    context.fillStyle = '#000000';
    context.fill();

    // Draw Graticule (grid lines)
    context.beginPath();
    path(d3.geoGraticule10());
    context.strokeStyle = 'rgba(255, 255, 255, 0.5)';
    context.lineWidth = 0.5;
    context.stroke();

    // Draw countries individually with case colors
    if (countries && countries.features) {
        countries.features.forEach(feature => {
            const countryName = feature.properties.name;
            const caseCount = caseCountsMap ? caseCountsMap.get(countryName) : 0;

            context.beginPath();
            path(feature);
            
            if (caseCount > 0 && caseColorScale) {
                context.fillStyle = caseColorScale(caseCount);
            } else {
                context.fillStyle = '#1b1b1b'; // Default land color
            }
            context.fill();
        });
    }

    // Draw Land Borders over the colored countries
    context.beginPath();
    path(countries);
    context.strokeStyle = '#ffffffb6';
    context.lineWidth = 0.5;
    context.stroke();
}

// --- Fly-to Animation Logic (Adapted from your function for Canvas) ---
function flyTo(countryName) {
    return new Promise((resolve) => {
        const targetCountry = world.features.find(c => c.properties.name === countryName);
        if (!targetCountry) {
            console.warn(`Country not found: ${countryName}`);
            return resolve();
        }

        const centroid = d3.geoCentroid(targetCountry);
        const initialRotate = projection.rotate();
        const targetRotate = [-centroid[0], -centroid[1]];
        const initialScale = projection.scale();
        const targetScale = 800; // Target zoom level from your function

        // Stop any previous animation
        if (currentAnimationTimer) {
            currentAnimationTimer.stop();
        }

        // Combined duration of your two-part transition
        const duration = 4000; 

        currentAnimationTimer = d3.timer(elapsed => {
            const t = Math.min(1, elapsed / duration);
            // Use an easing function to create a smooth start and finish
            const easedT = d3.easeCubicInOut(t);

            const currentRotate = d3.interpolate(initialRotate, targetRotate)(easedT);
            const currentScale = d3.interpolate(initialScale, targetScale)(easedT);

            projection.rotate(currentRotate);
            projection.scale(currentScale);
            redraw();

            if (t >= 1) {
                currentAnimationTimer.stop();
                resolve();
            }
        });
    });
}

// --- Reset Globe View Logic ---
function resetGlobe() {
     return new Promise((resolve) => {
        const initialRotate = projection.rotate();
        const targetRotate = [0, 0];
        const initialScale = projection.scale();
        
        if (currentAnimationTimer) {
            currentAnimationTimer.stop();
        }

        currentAnimationTimer = d3.timer(elapsed => {
            const duration = 2000;
            const t = Math.min(1, elapsed / duration);
            const easedT = d3.easeCubicInOut(t);

            const currentRotate = d3.interpolate(initialRotate, targetRotate)(easedT);
            const currentScale = d3.interpolate(initialScale, baseScale)(easedT);

            projection.rotate(currentRotate);
            projection.scale(currentScale);
            redraw();

            if (t >= 1) {
                currentAnimationTimer.stop();
                resolve();
            }
        });
    });
}


// --- Animation Sequence Runner ---
async function runAnimationSequence() {
    const countryNames = countriesInput.value.split('\n').map(c => c.trim()).filter(Boolean);
    const waitTime = parseInt(waitTimeInput.value, 10) * 1000;

    if (countryNames.length === 0) {
        setStatus('Please enter at least one country.', true);
        mediaRecorder.stop();
        return;
    }
    
    // Start with a global view
    setStatus('Recording... Starting with globe view.');
    await resetGlobe();
    await new Promise(resolve => setTimeout(resolve, 1000));

    for (let i = 0; i < countryNames.length; i++) {
        const countryName = countryNames[i];

        setStatus(`Recording... Flying to ${countryName}.`);
        await flyTo(countryName);
        
        setStatus(`Recording... Pausing at ${countryName}.`);
        await new Promise(resolve => setTimeout(resolve, waitTime));
    }
    
    // Return to globe view at the end of the sequence
    setStatus('Recording... Returning to globe view.');
    await resetGlobe();
    await new Promise(resolve => setTimeout(resolve, 1000)); // Wait a moment at global view
    
    // Stop recording
    if (mediaRecorder && mediaRecorder.state !== 'inactive') {
        mediaRecorder.stop();
    }
}


// --- Event Handlers & Setup ---
function setStatus(message, isError = false) {
    statusMessage.textContent = message;
    statusMessage.style.color = isError ? '#f87171' : '#9ca3af'; // red-400 or gray-400
}

function setupMediaRecorder() {
    const stream = canvas.captureStream(30); // 30 fps
    mediaRecorder = new MediaRecorder(stream, {
        mimeType: 'video/webm; codecs=vp9',
        videoBitsPerSecond: 5000000 // 5 Mbps
    });

    mediaRecorder.ondataavailable = (event) => {
        if (event.data.size > 0) {
            recordedChunks.push(event.data);
        }
    };

    mediaRecorder.onstart = () => {
        setStatus('Recording...');
        startBtn.disabled = true;
        downloadLink.classList.add('hidden');
        countriesInput.disabled = true;
        waitTimeInput.disabled = true;
    };

    mediaRecorder.onstop = () => {
        setStatus('Processing video...');
        const blob = new Blob(recordedChunks, { type: 'video/webm' });
        const url = URL.createObjectURL(blob);
        
        downloadLink.href = url;
        downloadLink.download = `map-animation-${Date.now()}.webm`;
        downloadLink.classList.remove('hidden');
        
        setStatus('Recording complete. Ready to download.');
        startBtn.disabled = false;
        countriesInput.disabled = false;
        waitTimeInput.disabled = false;
    };

    mediaRecorder.onerror = (event) => {
        setStatus(`Recording error: ${event.error.message}`, true);
        startBtn.disabled = false;
         countriesInput.disabled = false;
        waitTimeInput.disabled = false;
    };
}


startBtn.addEventListener('click', () => {
    recordedChunks = [];
    setupMediaRecorder();
    mediaRecorder.start();
    runAnimationSequence();
});


// --- Initial Load ---
async function initialize() {
    setStatus('Loading map and case data...');
    try {
        // Load both datasets in parallel for efficiency
        const [topology, caseData] = await Promise.all([
            d3.json(worldJsonUrl),
            d3.csv(caseDataUrl)
        ]);

        // Process geography
        world = topojson.feature(topology, topology.objects.countries);
        countries = world;

        // Process case data and set up color scale
        allCasesData = caseData;
        caseCountsMap = d3.rollup(allCasesData, v => v.length, d => d.Jurisdictions);
        const maxCases = d3.max(caseCountsMap.values());
        
        caseColorScale = d3.scaleLog()
            .domain([1, maxCases])
            .range(['#ff7c7c8c', '#eb0000c7']);

        redraw();
        setStatus('Ready to record.');
        startBtn.disabled = false;

    } catch (error) {
        console.error("Error loading initial data:", error);
        setStatus('Failed to load map/case data. Please refresh.', true);
    }
}

// Initialize the application
startBtn.disabled = true;
initialize();


