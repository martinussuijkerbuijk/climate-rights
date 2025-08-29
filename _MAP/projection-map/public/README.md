## What to do

1. You render data to a GeoTiff
1.1 gdalinfo <filename> to see the info 
2. Convert GeoTiff to .asc file: 
'
gdal_translate -b 3 -of AAIGrid subset_no3_level.tif climate_data.asc
'
3. Then convert .asc with convertASC_to_JSON.py in the scripts folder.
4. The JSON data is converted in the main.js script