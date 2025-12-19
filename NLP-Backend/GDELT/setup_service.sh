#!/bin/bash

# 1. Update System and Install Python/Pip
echo "Installing Python and dependencies..."
sudo apt-get update
sudo apt-get install -y python3-pip python3-venv

# 2. Create a Virtual Environment
# This keeps your libraries clean and separate from the system
python3 -m venv venv
source venv/bin/activate

# 3. Install Libraries
if [ -f "requirements.txt" ]; then
    pip install -r requirements.txt
else
    echo "ERROR: requirements.txt not found! Please upload it."
    exit 1
fi

# 4. Test the Script (Optional - dry run)
echo "Testing script import..."
python3 -c "import pandas; import google.cloud.bigquery; print('Imports successful!')"

# 5. Setup Cron Job (The Automation)
# This runs the script every day at 8:00 AM Server Time
current_dir=$(pwd)
cron_job="0 8 * * * cd $current_dir && $current_dir/venv/bin/python3 $current_dir/GDELT_Watchdog.py >> $current_dir/cron_log.txt 2>&1"

# Check if job already exists to avoid duplicates
(crontab -l 2>/dev/null | grep -F "$current_dir/GDELT_Watchdog.py") && echo "Cron job already exists" || (crontab -l 2>/dev/null; echo "$cron_job") | crontab -

echo "---------------------------------------------------"
echo "SUCCESS! The Watchdog is now scheduled."
echo "It will run every day at 08:00 AM."
echo "Logs will be saved to: $current_dir/cron_log.txt"
echo "---------------------------------------------------"