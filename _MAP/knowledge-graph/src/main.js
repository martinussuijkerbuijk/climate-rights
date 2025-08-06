// --- Import Dependencies ---
import './style.css'; // Add this line
import * as d3 from 'd3';



// --- 1. Setup ---
const container = document.getElementById('graph-container');
const width = container.clientWidth;
const height = container.clientHeight;
const tooltip = d3.select("#tooltip");

// UI Control Elements
const searchInput = d3.select("#search-input");
const yearSlider = d3.select("#year-slider");
const yearLabel = d3.select("#year-label");
const labelToggleCheckbox = d3.select("#label-toggle-checkbox");

const svg = d3.select(container).append("svg")
    .attr("viewBox", [-width / 2, -height / 2, width, height]);

const g = svg.append("g");

// --- 2. Load Data and Create Graph ---
d3.json("/graph_data.json").then(function(graph) {
    
    const allNodes = graph.nodes;
    const allLinks = graph.links;

    // --- Data Pre-processing for Slider ---
    const years = allNodes.filter(d => d.type === 'case').map(d => d.year);
    const minYear = d3.min(years);
    const maxYear = d3.max(years);
    yearSlider.attr("min", minYear).attr("max", maxYear).attr("value", maxYear);
    yearLabel.text(maxYear);

    // --- 3. Scales ---
    const maxNodeCount = d3.max(allNodes, d => d.count);
    const radiusScale = d3.scaleSqrt().domain([1, maxNodeCount]).range([5, 40]);
    const colorScale = d3.scaleOrdinal(d3.schemeTableau10);

    // --- 4. Force Simulation ---
    const simulation = d3.forceSimulation(allNodes)
        .force("link", d3.forceLink(allLinks).id(d => d.id).distance(() => 120 + Math.random() * 80))
        .force("charge", d3.forceManyBody().strength(-150))
        .force("center", d3.forceCenter(0, 0));

    // --- 5. Draw Elements ---
    const linkGroup = g.append("g").attr("class", "links");
    const nodeGroup = g.append("g").attr("class", "nodes");
    const labelGroup = g.append("g").attr("class", "labels");
    
    // --- 6. Main Update Function ---
    function updateGraph(filteredNodes, filteredLinks) {
        
        let link = linkGroup.selectAll("line").data(filteredLinks, d => `${d.source.id}-${d.target.id}`);
        link.exit().remove();
        link = link.enter().append("line").attr("stroke-width", d => Math.sqrt(d.weight)).merge(link);

        let node = nodeGroup.selectAll("circle").data(filteredNodes, d => d.id);
        node.exit().remove();
        node = node.enter().append("circle")
            .attr("r", d => radiusScale(d.count))
            .attr("fill", d => d.type === 'topic' ? colorScale(d.id) : '#ccc')
            .call(drag(simulation))
            .merge(node);

        let label = labelGroup.selectAll("text").data(filteredNodes, d => d.id);
        label.exit().remove();
        label = label.enter().append("text")
            .text(d => d.id)
            .style("font-size", d => d.type === 'topic' ? '12px' : '9px')
            .style("fill", "#fff")
            // .style("stroke", "white")
            // .style("stroke-width", "3px")
            // .style("paint-order", "stroke")
            .merge(label);

        node.on("mouseover", handleMouseOver).on("mouseout", handleMouseOut).on("click", (event, d) => handleClick(event, d, node, link));

        simulation.nodes(filteredNodes);
        simulation.force("link").links(filteredLinks);
        simulation.alpha(1).restart();

        simulation.on("tick", () => {
            link.attr("x1", d => d.source.x).attr("y1", d => d.source.y).attr("x2", d => d.target.x).attr("y2", d => d.target.y);
            node.attr("cx", d => d.x).attr("cy", d => d.y);
            label.each(function(d) {
                const textLabel = d3.select(this);
                if (d.type === 'topic') {
                    textLabel.attr("x", d.x).attr("y", d.y).attr("text-anchor", "middle");
                    return;
                }
                if (d.type === 'case') {
                    const parentLink = filteredLinks.find(l => l.source.id === d.id);
                    if (parentLink) {
                        const parentNode = parentLink.target;
                        const isLeft = d.x < parentNode.x;
                        const radius = radiusScale(d.count);
                        const margin = 5;
                        textLabel.attr("x", d.x + (isLeft ? -(radius + margin) : (radius + margin)));
                        textLabel.attr("y", d.y);
                        textLabel.attr("text-anchor", isLeft ? "end" : "start");
                    }
                }
            });
        });
    }

    // --- 7. Event Handlers ---
    function handleMouseOver(event, d) {
        let tooltipContent = '';
        if (d.type === 'topic') {
            tooltipContent = `<strong>Topic:</strong> ${d.id}<br/><strong>Cases:</strong> ${d.count}`;
        } else if (d.type === 'case') {
            tooltipContent = `<div style="max-width: 300px;"><strong>${d.id}</strong><hr style="margin: 4px 0; border-color: #555;"><p style="margin: 0;"><strong>Year:</strong> ${d.year} | <strong>Status:</strong> ${d.status}</p><p style="margin-top: 8px; font-style: italic;">${d.summary}</p></div>`;
        }
        tooltip.style("opacity", 1).html(tooltipContent).style("left", (event.pageX + 10) + "px").style("top", (event.pageY - 15) + "px");
    }

    function handleMouseOut() {
        tooltip.style("opacity", 0);
    }

    function handleClick(event, d, nodeSelection, linkSelection) {
        nodeSelection.classed("faded", false);
        linkSelection.classed("faded", false);

        const connected = new Set();
        connected.add(d.id);
        allLinks.forEach(l => {
            if (l.source.id === d.id) connected.add(l.target.id);
            if (l.target.id === d.id) connected.add(l.source.id);
        });

        nodeSelection.filter(n => !connected.has(n.id)).classed("faded", true);
        linkSelection.filter(l => !(l.source.id === d.id || l.target.id === d.id)).classed("faded", true);
        
        event.stopPropagation();
    }
    
    svg.on("dblclick", () => {
        nodeGroup.selectAll("circle").classed("faded", false);
        linkGroup.selectAll("line").classed("faded", false);
    });

    searchInput.on("input", (event) => {
        const searchTerm = event.target.value.toLowerCase();

        if (!searchTerm) {
            nodeGroup.selectAll("circle").classed("faded", false);
            linkGroup.selectAll("line").classed("faded", false);
            return;
        }

        const matchingNodes = allNodes.filter(n => n.id.toLowerCase().includes(searchTerm));
        const visibleNodes = new Set(matchingNodes.map(n => n.id));

        allLinks.forEach(l => {
            if (matchingNodes.some(n => n.id === l.source.id || n.id === l.target.id)) {
                visibleNodes.add(l.source.id);
                visibleNodes.add(l.target.id);
            }
        });

        nodeGroup.selectAll("circle").classed("faded", d => !visibleNodes.has(d.id));
        linkGroup.selectAll("line").classed("faded", d => !visibleNodes.has(d.source.id) || !visibleNodes.has(d.target.id));
    });

    yearSlider.on("input", (event) => {
        const selectedYear = +event.target.value;
        yearLabel.text(selectedYear);
        
        const topicNodes = allNodes.filter(n => n.type === 'topic');
        const caseNodes = allNodes.filter(n => n.type === 'case' && n.year <= selectedYear);
        const filteredNodes = [...topicNodes, ...caseNodes];
        const filteredNodeIds = new Set(filteredNodes.map(n => n.id));
        const filteredLinks = allLinks.filter(l => filteredNodeIds.has(l.source.id) && filteredNodeIds.has(l.target.id));

        updateGraph(filteredNodes, filteredLinks);
    });

    labelToggleCheckbox.on("change", (event) => {
        const isChecked = event.target.checked;
        labelGroup.selectAll("text").filter(d => d.type === 'case').style("display", isChecked ? "block" : "none");
    });
    
    // --- Initial Draw ---
    updateGraph(allNodes, allLinks);

    // --- 8. Zoom Functionality ---
    // Create a scale to map zoom level to font size for topics
    const topicFontSizeScale = d3.scaleLinear()
        .domain([0.1, 1, 8]) // Input domain (zoom levels)
        .range([50, 12, 4]); // Output range (font sizes)

    function zoomed(event) {
        const { transform } = event;
        g.attr("transform", transform);
        
        // Update the font size of ONLY topic labels based on the current zoom level
        labelGroup.selectAll("text")
            .filter(d => d.type === 'topic')
            .style("font-size", `${topicFontSizeScale(transform.k)}px`);
    }

    const zoom = d3.zoom().scaleExtent([0.1, 8]).on("zoom", zoomed);
    svg.call(zoom);


}).catch(function(error) {
    console.error("Error loading the graph data:", error);
    container.innerHTML = `<p style="text-align:center;color:red;">Error: Could not load graph_data.json. Make sure the file exists.</p>`;
});

// --- 9. Drag functionality ---
function drag(simulation) {
    function dragstarted(event, d) {
        if (!event.active) simulation.alphaTarget(0.3).restart();
        d.fx = d.x; d.fy = d.y;
    }
    function dragged(event, d) {
        d.fx = event.x; d.fy = event.y;
    }
    function dragended(event, d) {
        if (!event.active) simulation.alphaTarget(0);
        d.fx = null; d.fy = null;
    }
    return d3.drag().on("start", dragstarted).on("drag", dragged).on("end", dragended);
}
