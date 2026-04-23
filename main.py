"""
streamdeb - Stream Deck controller for Debian Linux
"""

import sys
from StreamDeck.DeviceManager import DeviceManager


def main():
    manager = DeviceManager()
    decks = manager.enumerate()

    if not decks:
        print("No Stream Deck devices found.")
        print("Make sure the udev rules are installed and the device is connected.")
        sys.exit(1)

    print(f"Found {len(decks)} Stream Deck device(s):")
    for i, deck in enumerate(decks):
        deck.open()
        deck.reset()
        info = deck.deck_type()
        keys = deck.key_count()
        print(f"  [{i}] {info} — {keys} keys")
        deck.close()


if __name__ == "__main__":
    main()
