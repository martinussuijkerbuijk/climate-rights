import json
import argparse

def convert_asc_to_json(asc_filepath, json_filepath):
    """
    Reads an ESRI ASCII Grid (.asc) file and converts it into a JSON format.

    The JSON output contains the header metadata and a single flat list
    of all the grid cell values. NaN values will be replaced with 0.
    """
    header = {}
    values = []

    try:
        # Note: Using a raw string r'' for the path is good practice
        with open(asc_filepath, 'r') as asc_file:
            # 1. Read the 6 header lines
            for _ in range(6):
                line = asc_file.readline().strip().split()
                key = line[0].lower()
                value = line[1]

                # Convert numbers to int or float using a robust approach
                try:
                    header[key] = int(value)
                except ValueError:
                    header[key] = float(value)

            # Get the nodata value from the header
            nodata_value = header.get('nodata_value')

            # 2. Read the remaining lines for the raster data
            for line in asc_file:
                row_values = [
                    0 if float(val) == nodata_value else float(val)
                    for val in line.strip().split()
                ]
                values.extend(row_values)

        # Combine header and values into one dictionary
        output_data = header
        output_data['values'] = values

        # 3. Write the dictionary to a JSON file
        with open(json_filepath, 'w') as json_file:
            json.dump(output_data, json_file, indent=2)

        print(f"✅ Successfully converted '{asc_filepath}' to '{json_filepath}'")

    except FileNotFoundError:
        print(f"❌ Error: The file '{asc_filepath}' was not found.")
    except Exception as e:
        print(f"An error occurred: {e}")

# This block runs when the script is executed from the command line
if __name__ == "__main__":
    # 1. Set up the argument parser
    parser = argparse.ArgumentParser(
        description="Converts an ESRI ASCII Grid (.asc) file to a JSON file."
    )
    
    # 2. Define the command-line arguments
    parser.add_argument("input_file", help="The path to the input .asc file.")
    parser.add_argument("output_file", help="The path for the output .json file.")

    # 3. Parse the arguments provided by the user
    args = parser.parse_args()

    # 4. Call the main function with the provided file paths
    convert_asc_to_json(args.input_file, args.output_file)
