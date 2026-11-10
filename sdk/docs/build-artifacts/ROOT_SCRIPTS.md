# Root Directory Scripts

These are utility scripts in the project root for users and developers.

## User Utilities

### test_connection.py ⭐
Quick connection test - verifies your .env credentials work.

**Usage:**
```bash
python test_connection.py
```

**What it does:**
- Loads credentials from .env
- Connects to DeepLynx
- Creates a test item
- Retrieves it
- Deletes it

**When to use:** First thing after setting up .env file.

### verify_installation.py
Verifies the storage client package is installed correctly.

**Usage:**
```bash
python verify_installation.py
```

**What it does:**
- Tests all imports
- Validates configuration
- Tests model creation
- Tests exceptions

**When to use:** After pip installing the package.

### list_datasources.py
Lists available data sources for your project.

**Usage:**
```bash
python list_datasources.py
```

**What it does:**
- Connects to DeepLynx
- Lists all data sources
- Shows which one to add to .env

**When to use:** If you need to find your data source ID.

### test_pip_install.sh
Tests that the package can be pip installed.

**Usage:**
```bash
./test_pip_install.sh
```

**What it does:**
- Creates temp virtualenv
- Installs package
- Tests imports
- Cleans up

**When to use:** Before pushing to verify pip install works.

## Test Suite

The actual test suite is in `tests/`:

```bash
pytest tests/                    # All tests
pytest tests/unit/test_integration.py # Integration tests
./run_integration_tests.sh      # Run with nice output
```

## Quick Reference

```bash
# First time setup
cp .env.example .env
vim .env
python test_connection.py          # Verify it works

# Run tests
pytest tests/ -v                   # All tests
./run_integration_tests.sh         # Integration only

# Check installation
python verify_installation.py

# Find data source
python list_datasources.py
```
