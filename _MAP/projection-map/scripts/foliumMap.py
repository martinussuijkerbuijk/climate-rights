import folium
import rasterio
import numpy as np
import geopandas as gpd
from branca.colormap import linear
import os

# --- Configuration ---
RASTER_FILE = 'D:/_POSTDOC/_CR/github/climate-rights/_MAP/projection-map/subset_sea_level.tif'
GEOJSON_URL = 'https://raw.githubusercontent.com/datasets/geo-countries/master/data/countries.geojson'
OUTPUT_HTML = 'folium_map.html'

# --- Dummy Raster Creation (for demonstration if the file doesn't exist) ---
def create_dummy_raster(filepath):
    """Creates a dummy TIFF file if the specified one doesn't exist."""
    if not os.path.exists(filepath):
        print(f"'{filepath}' not found. Creating a dummy raster for demonstration.")
        # Define raster properties
        width, height = 360, 180
        transform = rasterio.transform.from_origin(-180, 90, 1.0, 1.0)
        
        # Create dummy data (a simple gradient)
        lons = np.linspace(-180, 180, width)
        lats = np.linspace(90, -90, height)
        lons_grid, lats_grid = np.meshgrid(lons, lats)
        data = np.sqrt(lons_grid**2 + lats_grid**2)
        data = (data - data.min()) / (data.max() - data.min()) * 10 # Normalize to 0-10
        
        # Write to a new GeoTIFF file
        with rasterio.open(
            filepath, 'w',
            driver='GTiff',
            height=height,
            width=width,
            count=1,
            dtype=data.dtype,
            crs='+proj=latlong',
            transform=transform,
        ) as dst:
            dst.write(data, 1)
        print("Dummy raster created successfully.")

# --- Main Script ---

# 1. Create the dummy raster if the original is not available
create_dummy_raster(RASTER_FILE)

# 2. Create a Folium Map
# We use the default Web Mercator projection (EPSG:3857) as it's the most
# compatible with web map tiles. While not the Azimuthal projection from D3,
# it provides a familiar and functional base.
# We start zoomed out to give a global view.
m = folium.Map(location=[20, 0], zoom_start=2, tiles='CartoDB dark_matter')

# 3. Load and Add the Raster Layer
try:
    with rasterio.open(RASTER_FILE) as r:
        # Get raster data and geographic bounds
        data = r.read(1, masked=True)
        bounds = [[r.bounds.bottom, r.bounds.left], [r.bounds.top, r.bounds.right]]

        # FIX 1: Convert MaskedArray to a regular numpy array with NaNs
        # This handles the JSON serialization error.
        data = data.astype('float32')
        data[data.mask] = np.nan
        
        # Create a colormap for the raster data
        # This maps the raster values to a color gradient (e.g., blue to yellow to red)
        min_val, max_val = np.nanmin(data), np.nanmax(data)
        colormap = linear.YlOrRd_09.scale(min_val, max_val)
        
        # Add the raster data as an ImageOverlay
        # The opacity is set to 0.6 to see the map tiles underneath.
        folium.raster_layers.ImageOverlay(
            image=data,
            bounds=bounds,
            opacity=0.6,
            colormap=lambda x: colormap(x),
            name='Sea Level Rise'
        ).add_to(m)
        
        print(f"Raster layer '{RASTER_FILE}' added successfully.")

except Exception as e:
    print(f"Error processing raster file: {e}")
    print("Please ensure 'subset_sea_level_norm.tif' is a valid GeoTIFF file.")


# 4. Add an Interactive Country Outline Layer (Choropleth)
try:
    # Load country boundaries from a remote GeoJSON file
    gdf = gpd.read_file(GEOJSON_URL)

    # Create a GeoJson layer to act as the interactive choropleth
    geojson_layer = folium.GeoJson(
        gdf,
        name='Country Outlines',
        style_function=lambda feature: {
            'fillColor': 'transparent', # No fill
            'color': 'white',           # White border for countries
            'weight': 1,                # Border thickness
            'fillOpacity': 0,           # Fully transparent fill
        },
        highlight_function=lambda x: {'weight': 3, 'color': '#ffcc00'}, # Highlight on hover
        tooltip=folium.features.GeoJsonTooltip(
            # FIX 2: Changed 'ADMIN' to 'name' to match the GeoJSON property
            fields=['name'],
            aliases=['Country:'],
            style=("background-color: grey; color: white; font-family: courier new; font-size: 12px; padding: 10px;")
        )
    ).add_to(m)
    
    print("Interactive country outlines added successfully.")

except Exception as e:
    print(f"Could not load GeoJSON for country outlines: {e}")


# 5. Add a Layer Control
# This allows the user to toggle the raster and country layers on and off.
folium.LayerControl().add_to(m)

# 6. Save the map to an HTML file
m.save(OUTPUT_HTML)

print(f"\nMap has been generated and saved to '{OUTPUT_HTML}'")
print("You can now open this file in your web browser.")