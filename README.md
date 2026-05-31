# 1. Install dependencies
pip install pandas numpy yfinance requests

# 2. Create directories
mkdir -p /var/qxnet/{data,archive}

# 3. Set FRED API key in qxpull.py
# FRED_API_KEY = "your_key_here"

# 4. Test run
python qxpull.py

# 5. Schedule with cron (Linux/Mac)
# 0 6 * * * /usr/bin/python3 /opt/qxnet/qxpull.py
