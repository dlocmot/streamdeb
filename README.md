# streamdeb

Python implementation to activate and use the Elgato Stream Deck on Debian Linux.

## Overview

`streamdeb` provides a setup and runtime environment for the Stream Deck on Debian-based systems, handling USB permissions, system dependencies, and a Python-based control layer.

## Requirements

- Debian 11 (Bullseye) or later
- Python 3.10+
- Elgato Stream Deck (any model)

## Features

- Automated udev rules setup for USB access without root
- Stream Deck device detection and initialization
- Key mapping and custom action binding
- Plugin support for common applications

## Installation

```bash
# Clone the repository
git clone https://github.com/dlocmot/streamdeb.git
cd streamdeb

# Install system dependencies
sudo apt install python3-pip python3-venv libhidapi-hidraw0 libhidapi-libusb0

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install Python dependencies
pip install -r requirements.txt

# Install udev rules (required for USB access)
sudo cp udev/50-streamdeck.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules
sudo udevadm trigger
```

After installing the udev rules, unplug and reconnect your Stream Deck.

## Usage

```bash
python main.py
```

## Project Structure

```
streamdeb/
├── main.py          # Entry point
├── deck/            # Core Stream Deck control logic
├── plugins/         # Action plugins
├── udev/            # udev rules for USB permissions
└── requirements.txt
```

## License

MIT
