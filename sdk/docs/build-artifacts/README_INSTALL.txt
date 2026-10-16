QUICK INSTALLATION GUIDE
========================

Install from GitHub:

    pip install "git+https://github.com/idaholab/prometheus_core.git#subdirectory=sdk"

Or clone and install in development mode:

    git clone https://github.com/idaholab/prometheus_core.git
    cd prometheus_core/sdk
    pip install -e .

Setup credentials:

    cp .env.example .env
    vim .env  # Add your DeepLynx credentials

Verify installation:

    python test_connection.py

See INSTALL.md for detailed installation options.
