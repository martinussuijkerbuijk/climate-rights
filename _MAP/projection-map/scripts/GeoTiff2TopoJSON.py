import subprocess
import json
import geojson
from pytopojson import topology # Correct import
import os
import shutil

def check_gdal():
    """Checks if gdal_contour is available."""
    if shutil.which('gdal_contour') is None:
        print("Error: 'gdal_contour' not found.")
        print("Please ensure GDAL is installed and its command-line tools are in your system's PATH.")
        return False
    print("GDAL found.")
    return True

def convert_geotiff_to_geojson(input_tiff, output_geojson, contour_interval=10, attribute_name='level'):
    """
    Converts a GeoTIFF to a GeoJSON file using gdal_contour.
    """
    print(f"\nStep 1: Converting GeoTIFF to intermediate GeoJSON...")
    # Ensure we generate polygons (-p) and name the attribute 'level' (-a)
    command = [
        'gdal_contour', '-p', '-a', attribute_name, '-i', str(contour_interval),
        '-f', 'GeoJSON', input_tiff, output_geojson
    ]
    try:
        subprocess.run(command, check=True, capture_output=True, text=True)
        print(f"Successfully created intermediate GeoJSON: {output_geojson}")
        return True
    except subprocess.CalledProcessError as e:
        print(f"\nError during GeoJSON conversion: {e.stderr}")
        return False
    return False

def convert_geojson_to_topojson(input_geojson, output_topojson, quantization=1e6):
    """
    Converts and simplifies a GeoJSON file to TopoJSON using the pytopojson library.
    """
    print(f"\nStep 2: Converting GeoJSON to TopoJSON using pytopojson...")
    try:
        # Read the intermediate GeoJSON file
        print("Reading GeoJSON file into memory...")
        with open(input_geojson, 'r') as f:
            geojson_data = geojson.load(f)
        print(f"GeoJSON loaded. Found {len(geojson_data['features'])} features.")

        # Wrap the GeoJSON data in a dictionary
        input_objects = {"contours": geojson_data}

        # Create Topology object
        topology_ = topology.Topology()

        # --- CORRECTED ---
        # Use the direct functional approach which correctly preserves properties.
        print("Simplifying and quantizing topology... (This may take a while)")
        topojson_data_dict = topology_(
            input_objects, 
            quantization=quantization 
        )
        print("Topology calculation complete.")

        # Write the final TopoJSON file
        with open(output_topojson, 'w') as f:
            json.dump(topojson_data_dict, f)
        
        print(f"Successfully created optimized TopoJSON: {output_topojson}")
        return True
    except Exception as e:
        print(f"An error occurred during TopoJSON conversion: {e}")
        return False

if __name__ == '__main__':
    # --- Pre-flight Check ---
    # if not check_gdal():
    #     exit() 

    # Use an absolute path for your input file to avoid issues.
    input_file = 'subset_sea_level_norm.tif' 
    
    # An intermediate file that will be created and then can be deleted.
    intermediate_geojson = 'subset_sea_level_norm.geojson'
    
    # The final, optimized TopoJSON file for your web app.
    output_file = 'sea_level_contours.topojson'
    
    interval = 0.1 
    quantization_factor = 1e6

    # --- Run the conversion pipeline ---
    # Ensure the attribute_name is set to 'level'
    # if convert_geotiff_to_geojson(input_file, intermediate_geojson, contour_interval=interval, attribute_name='level'):
    if convert_geojson_to_topojson(intermediate_geojson, output_file, quantization=quantization_factor):
        try:
            os.remove(intermediate_geojson)
            print(f"\nCleaned up intermediate file: {intermediate_geojson}")
        except OSError as e:
            print(f"Error cleaning up intermediate file: {e}")
    
    print("\nConversion process finished.")
