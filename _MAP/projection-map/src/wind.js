import * as d3 from 'https://cdn.skypack.dev/d3@7';


// --- Configuration Constants ---
const MAX_PARTICLE_AGE = 90;
const PARTICLE_LINE_WIDTH = 1.0;
const PARTICLE_MULTIPLIER = 1 / 300;
// ✨ FIX #1: Drastically reduced scale for a calmer, more accurate look.
const VELOCITY_SCALE = 0.00015;
const NULL_WIND_VECTOR = [NaN, NaN, null];

export class WindAnimator {
    constructor(projection, width, height) {
        this.projection = projection;
        this.width = width;
        this.height = height;
        this.particles = [];
        this.field = null;
        this.animationId = null;
        this.isVisible = false;

        this.canvas = d3.select('#map-container')
            .append('canvas')
            .attr('class', 'wind-canvas')
            .attr('width', width)
            .attr('height', height)
            .style('position', 'absolute')
            .style('top', 0)
            .style('left', 0)
            .style('pointer-events', 'none')
            .style('z-index', 1)
            .style('width', '100%')
            .style('height', '100%')
            .node();
        this.context = this.canvas.getContext('2d');
        this.context.lineWidth = PARTICLE_LINE_WIDTH;
        this.context.fillStyle = 'rgba(0, 0, 0, 0.97)';
    }

    start(windData) {
        this.stop();
        this.isVisible = true;
        d3.select(this.canvas).style('visibility', 'visible');
        this.field = this.createField(windData);
        if (!this.field) {
            console.error("Failed to create wind field. Is the data valid?");
            this.stop();
            return;
        }
        this.createParticles();
        this.animate();
    }

    stop() {
        this.isVisible = false;
        d3.select(this.canvas).style('visibility', 'hidden');
        if (this.animationId) {
            cancelAnimationFrame(this.animationId);
            this.animationId = null;
        }
        this.clearCanvas();
    }
    
    updateProjection(newProjection) {
        this.projection = newProjection;
        if (this.isVisible && this.field) {
            this.field.release();
            this.field = this.createField(this.field.windData);
            this.createParticles();
        }
    }

    clearCanvas() {
        this.context.clearRect(0, 0, this.width, this.height);
    }

    distort(lon, lat, x, y, scale, wind) {
        const u = wind[0] * scale;
        const v = wind[1] * scale;
        const epsilon = 1e-6; 

        const p1 = this.projection([lon + epsilon, lat]);
        const p2 = this.projection([lon, lat + epsilon]);

        const d = [0, 0, 0, 0];
        if (p1) {
            d[0] = (p1[0] - x) / epsilon;
            d[1] = (p1[1] - y) / epsilon;
        }
        if (p2) {
            d[2] = (p2[0] - x) / epsilon;
            d[3] = (p2[1] - y) / epsilon;
        }
        
        wind[0] = d[0] * u + d[2] * v;
        wind[1] = d[1] * u + d[3] * v;
        return wind;
    }

    createField(windData) {
    // Add a more robust check for the actual data structure
    if (!windData || !windData[0] || !windData[1] || !windData[0].header || !windData[0].data || !windData[1].data) {
        return null;
    }

    // ✨ THE FIX: Correctly unpack the header and data arrays from the loaded JSON
    const header = windData[0].header;
    const uData = windData[0].data;
    const vData = windData[1].data;

    // You can keep this log for now to verify the header is correct
    console.log("Wind Data Header:", header);

    const interpolate = (lon, lat) => {
            const { nx, ny, lo1, la1, dx, dy } = header;

            let gridLon = lon;
            if (gridLon < lo1) {
                gridLon += 360;
            }
            
            const i = Math.floor((gridLon - lo1) / dx);
            const j = Math.floor((la1 - lat) / dy);

            if (i >= 0 && i < nx && j >= 0 && j < ny) {
                const index = j * nx + i;
                // Use the new uData and vData variables
                if (uData[index] !== null && vData[index] !== null) {
                    return [uData[index], vData[index]];
                }
            }
            return null;
        };

        const field = (x, y) => {
            const coords = this.projection.invert([x, y]);
            if (!coords || !Number.isFinite(coords[0])) return NULL_WIND_VECTOR;

            const [lon, lat] = coords;
            const wind = interpolate(lon, lat);
            if (!wind) return NULL_WIND_VECTOR;
            
            const velocityScale = VELOCITY_SCALE * this.projection.scale();
            const distorted = this.distort(lon, lat, x, y, velocityScale, wind);
            const mag = Math.sqrt(distorted[0] * distorted[0] + distorted[1] * distorted[1]);
            
            if (!isFinite(mag) || mag > 15) {
                return NULL_WIND_VECTOR;
            }

            return [distorted[0], distorted[1], mag];
        };
        
        field.windData = windData;
        field.release = () => {};

        return field;
    }
    
    // The rest of the file (createParticles, randomizeParticle, animate) remains the same as the previous version.
    createParticles() {
        this.particles = [];
        const particleCount = Math.round(this.width * this.height * PARTICLE_MULTIPLIER);
        for (let i = 0; i < particleCount; i++) {
            this.particles.push(this.randomizeParticle({ age: Math.floor(Math.random() * MAX_PARTICLE_AGE) }));
        }
    }

    randomizeParticle(particle) {
        let x, y;
        let safetyNet = 0;
        do {
            x = Math.random() * this.width;
            y = Math.random() * this.height;
        } while (this.projection.invert([x, y]) === null && safetyNet++ < 30);
        
        particle.x = x;
        particle.y = y;
        return particle;
    }
    
    animate() {
        const evolve = () => {
            this.particles.forEach(p => {
                // ✨ THE FIX: Reset path history at the start of each frame.
                // This prevents "ghost paths" from being drawn after regeneration.
                p.xt = null;

                if (p.age > MAX_PARTICLE_AGE) {
                    this.randomizeParticle(p);
                    p.age = 0;
                }

                const [u, v] = this.field(p.x, p.y);

                if (isNaN(u) || isNaN(v)) {
                    // Current location is invalid (off-globe), kill the particle.
                    p.age = MAX_PARTICLE_AGE;
                } else {
                    const xt = p.x + u;
                    const yt = p.y + v;

                    // Check if the destination is on the globe.
                    if (this.projection.invert([xt, yt])) {
                        // If yes, set the new path.
                        p.xt = xt;
                        p.yt = yt;
                    } else {
                        // If no, kill the particle.
                        p.age = MAX_PARTICLE_AGE;
                    }
                }
                p.age++;
            });
        };

        const draw = () => {
            this.context.globalCompositeOperation = 'destination-in';
            this.context.fillRect(0, 0, this.width, this.height);
            this.context.globalCompositeOperation = 'source-over';
            
            // No longer using beginPath() and stroke() for the whole batch,
            // as each segment needs its own color.

            this.particles.forEach(p => {
                if (p.xt && p.yt) {
                    // Determine the starting and ending color for the gradient.
                    // You can customize these colors.
                    const startColor = [255, 255, 200, 0.3]; // Very faint white at the tail
                    const endColor = [255, 255, 255, 1.];   // Brighter white at the head

                    // Number of segments to draw for each particle's trail
                    const numSegments = 5; 

                    for (let i = 0; i < numSegments; i++) {
                        const t0 = i / numSegments;      // Start point for current segment (0 to 1)
                        const t1 = (i + 1) / numSegments; // End point for current segment (0 to 1)

                        // Interpolate color
                        const r = Math.round(startColor[0] + (endColor[0] - startColor[0]) * t0);
                        const g = Math.round(startColor[1] + (endColor[1] - startColor[1]) * t0);
                        const b = Math.round(startColor[2] + (endColor[2] - startColor[2]) * t0);
                        const a = startColor[3] + (endColor[3] - startColor[3]) * t0;

                        this.context.strokeStyle = `rgba(${r}, ${g}, ${b}, ${a})`;

                        // Calculate segment coordinates
                        const segStartX = p.x + (p.xt - p.x) * t0;
                        const segStartY = p.y + (p.yt - p.y) * t0;
                        const segEndX = p.x + (p.xt - p.x) * t1;
                        const segEndY = p.y + (p.yt - p.y) * t1;

                        this.context.beginPath();
                        this.context.moveTo(segStartX, segStartY);
                        this.context.lineTo(segEndX, segEndY);
                        this.context.stroke();
                    }

                    // Update particle's position for the next frame
                    p.x = p.xt;
                    p.y = p.yt;
                }
            });
        };

        const frame = () => {
            if (!this.isVisible) return;
            evolve();
            draw();
            this.animationId = requestAnimationFrame(frame);
        };
        frame();
    }
}