#!/usr/bin/env python3
"""
Accordion Bass MIDI Controller

USB-Keyboard to MIDI-Controller for Accordion Bass Simulation
"""

import sys
import argparse
import logging
from pathlib import Path
from typing import List

import evdev
import rtmidi
from evdev import InputDevice, categorize, ecodes
import yaml

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def note_to_midi(note_str: str) -> int:
    """Convert note string (e.g. 'C1', 'F#2', 'Bb3') to MIDI note number."""
    # Note name mapping
    note_map = {'C': 0, 'C#': 1, 'Db': 1, 'D': 2, 'D#': 3, 'Eb': 3, 'E': 4, 
                'F': 5, 'F#': 6, 'Gb': 6, 'G': 7, 'G#': 8, 'Ab': 8, 'A': 9, 
                'A#': 10, 'Bb': 10, 'B': 11}
    
    # Parse note string
    if len(note_str) < 2:
        raise ValueError(f"Invalid note format: {note_str}")
    
    # Extract octave (last character)
    octave = int(note_str[-1])
    
    # Extract note name (everything except last character)
    note_name = note_str[:-1]
    
    if note_name not in note_map:
        raise ValueError(f"Unknown note: {note_name}")
    
    # Calculate MIDI note: C1 should be 36 (bass range)
    # Standard MIDI: C4 = 60, so C1 = 36 (60 - 3*12)
    # Formula: (octave + 2) * 12 + note_offset
    midi_note = (octave + 2) * 12 + note_map[note_name]
    
    return midi_note


def notes_to_midi(notes) -> List[int]:
    """Convert list of note strings to MIDI numbers."""
    if isinstance(notes, str):
        return [note_to_midi(notes)]
    elif isinstance(notes, list):
        return [note_to_midi(note) for note in notes]
    elif isinstance(notes, int):
        return [notes]  # Already MIDI number
    elif isinstance(notes, list) and all(isinstance(n, int) for n in notes):
        return notes  # Already MIDI numbers
    else:
        raise ValueError(f"Invalid notes format: {notes}")


class AccordionBassMIDI:
    """Main class for Accordion Bass MIDI Controller."""
    
    def __init__(self, device_path: str, config_file: str = None, debug: bool = False):
        self.device_path = device_path
        self.device = None
        self.midiout = None
        self.active_notes = set()
        self.debug = debug
        self.grab_mode = False  # CapsLock toggle to grab/prevent OS key events
        
        # Load configuration
        config_path = config_file or Path(__file__).parent / "config" / "stradella_layout.yml"
        self.load_config(config_path)
        
        # Initialize MIDI
        self.setup_midi()
        
        # Initialize keyboard device
        self.setup_keyboard()
    
    def load_config(self, config_path: Path):
        """Loads the bass layout configuration."""
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                self.config = yaml.safe_load(f)
                logger.info(f"Configuration loaded from {config_path}")
                
                # Validate required fields
                if not self.config.get('bass_mapping'):
                    raise ValueError("Configuration missing 'bass_mapping' section")
                
                # Process bass mapping: convert note strings to MIDI and apply channel mapping
                self.process_bass_mapping()
                    
                # Log layout info if available
                if 'layout_info' in self.config:
                    info = self.config['layout_info']
                    logger.info(f"Layout: {info.get('name', 'Unknown')}")
                    logger.info(f"Keyboard: {info.get('keyboard_layout', 'QWERTY')}")
                    
        except FileNotFoundError:
            logger.error(f"Configuration file not found: {config_path}")
            sys.exit(1)
        except yaml.YAMLError as e:
            logger.error(f"Error parsing YAML configuration: {e}")
            sys.exit(1)
        except ValueError as e:
            logger.error(f"Invalid configuration: {e}")
            sys.exit(1)
    
    def process_bass_mapping(self):
        """Process bass mapping: convert notes to MIDI and apply channel mapping."""
        channel_mapping = self.config.get('channel_mapping', {})
        
        for key, mapping in self.config['bass_mapping'].items():
            # Convert note strings to MIDI numbers
            mapping['notes'] = notes_to_midi(mapping['notes'])
            
            # Apply channel mapping if not explicitly set
            if 'channel' not in mapping and 'type' in mapping:
                mapping_type = mapping['type']
                if mapping_type in channel_mapping:
                    mapping['channel'] = channel_mapping[mapping_type]
        
        # Process auxiliary keys if present
        if 'auxiliary_keys' in self.config:
            self.process_auxiliary_keys()
    
    def process_auxiliary_keys(self):
        """Process auxiliary keys: handle both MIDI notes and CC messages."""
        channel_mapping = self.config.get('channel_mapping', {})
        
        for key, mapping in self.config['auxiliary_keys'].items():
            # Handle MIDI notes (convert note strings to MIDI numbers)
            if 'notes' in mapping:
                mapping['notes'] = notes_to_midi(mapping['notes'])
            
            # Handle CC messages (keep as is, but validate)
            if 'cc' in mapping:
                if not isinstance(mapping['cc'], list):
                    mapping['cc'] = [mapping['cc']]
                # Validate CC numbers (0-127)
                for cc_num in mapping['cc']:
                    if not 0 <= cc_num <= 127:
                        logger.warning(f"Invalid CC number {cc_num} in {key}, should be 0-127")
                
                # Validate CC value (0-127)
                if 'value' in mapping:
                    if not 0 <= mapping['value'] <= 127:
                        logger.warning(f"Invalid CC value {mapping['value']} in {key}, should be 0-127")
                else:
                    mapping['value'] = 127  # Default CC value
            
            # Apply channel mapping if not explicitly set
            if 'channel' not in mapping and 'type' in mapping:
                mapping_type = mapping['type']
                if mapping_type in channel_mapping:
                    mapping['channel'] = channel_mapping[mapping_type]
    
    def setup_midi(self):
        """Initialize MIDI port."""
        try:
            self.midiout = rtmidi.MidiOut()
            self.midiout.open_virtual_port("Accordion Bass")
            logger.info("Virtual MIDI port 'Accordion Bass' created")
        except Exception as e:
            logger.error(f"MIDI setup failed: {e}")
            sys.exit(1)
    
    def setup_keyboard(self):
        """Initialize keyboard device."""
        try:
            self.device = InputDevice(self.device_path)
            logger.info(f"Keyboard device connected: {self.device.name} ({self.device.path})")
        except Exception as e:
            logger.error(f"Keyboard setup failed: {e}")
            sys.exit(1)
    
    def send_midi_notes(self, notes: List[int], velocity: int, channel: int = None, note_on: bool = True):
        """Send MIDI notes on specified channel."""
        status = 0x90 if note_on else 0x80  # Note On/Off
        # Use provided channel or fall back to default
        midi_channel = (channel or self.config.get("midi_channel", 1)) - 1  # MIDI channel (0-15)
        
        for note in notes:
            message = [status | midi_channel, note, velocity if note_on else 0]
            self.midiout.send_message(message)
            
            if note_on:
                self.active_notes.add((note, midi_channel))
            else:
                self.active_notes.discard((note, midi_channel))
    
    def send_midi_cc(self, cc_numbers: List[int], value: int, channel: int = None):
        """Send MIDI Control Change messages on specified channel."""
        # Use provided channel or fall back to default
        midi_channel = (channel or self.config.get("midi_channel", 1)) - 1  # MIDI channel (0-15)
        
        for cc_num in cc_numbers:
            # CC message: 0xB0 + channel, CC number, value
            message = [0xB0 | midi_channel, cc_num, value]
            self.midiout.send_message(message)
            logger.debug(f"Sent CC {cc_num} = {value} on channel {channel}")
    
    def send_midi_cc_toggle(self, cc_numbers: List[int], channel: int = None, key_name: str = ""):
        """Toggle MIDI Control Change messages (0/127) on specified channel."""
        # Track CC state per key (initialize if not exists)
        if not hasattr(self, 'cc_states'):
            self.cc_states = {}
        
        if key_name not in self.cc_states:
            self.cc_states[key_name] = False
        
        # Toggle state
        self.cc_states[key_name] = not self.cc_states[key_name]
        value = 127 if self.cc_states[key_name] else 0
        
        # Send CC messages
        self.send_midi_cc(cc_numbers, value, channel)
        logger.info(f"Toggled {key_name} CC {cc_numbers} = {value} on channel {channel}")
    
    def handle_key_event(self, event):
        """Process keyboard event."""
        if event.type != ecodes.EV_KEY:
            return
            
        key_name = ecodes.KEY[event.code]
        key_event = categorize(event)
        
        # Debug output - print all key events when debug mode is enabled
        if self.debug:
            key_state = "PRESS" if key_event.keystate == key_event.key_down else \
                       "RELEASE" if key_event.keystate == key_event.key_up else \
                       "HOLD" if key_event.keystate == key_event.key_hold else "UNKNOWN"
            print(f"🔧 DEBUG: {key_name} ({event.code}) -> {key_state}")
        
        # Handle CapsLock toggle for grab mode
        if key_name == "KEY_CAPSLOCK" and key_event.keystate == key_event.key_down:
            self.grab_mode = not self.grab_mode
            try:
                if self.grab_mode:
                    self.device.grab()
                    logger.info(f"� Grab mode ENABLED - Keys captured (no OS typing)")
                else:
                    self.device.ungrab()
                    logger.info(f"🔓 Grab mode DISABLED - Keys pass to OS (normal typing)")
            except Exception as e:
                logger.error(f"Failed to toggle grab mode: {e}")
            return
        
        # Check bass mapping first
        bass_config = self.config["bass_mapping"].get(key_name)
        if bass_config:
            self.handle_bass_key(key_name, bass_config, key_event)
            return
        
        # Check auxiliary keys
        if 'auxiliary_keys' in self.config:
            aux_config = self.config["auxiliary_keys"].get(key_name)
            if aux_config:
                self.handle_auxiliary_key(key_name, aux_config, key_event)
                return
        
        # Debug output for unmapped keys
        if self.debug and key_event.keystate == key_event.key_down:
            print(f"🔧 DEBUG: {key_name} is not mapped in configuration")
    
    def handle_bass_key(self, key_name: str, bass_config: dict, key_event):
        """Handle bass/chord key events."""
        notes = bass_config["notes"]
        velocity = self.config.get("velocity", 100)
        channel = bass_config.get("channel")
        
        if key_event.keystate == key_event.key_down:
            logger.info(f"Key pressed: {bass_config['name']} ({key_name}) on channel {channel}")
            self.send_midi_notes(notes, velocity, channel, note_on=True)
            
        elif key_event.keystate == key_event.key_up:
            logger.info(f"Key released: {bass_config['name']} ({key_name}) on channel {channel}")
            self.send_midi_notes(notes, 0, channel, note_on=False)
    
    def handle_auxiliary_key(self, key_name: str, aux_config: dict, key_event):
        """Handle auxiliary key events (MIDI notes, CC messages, toggles)."""
        channel = aux_config.get("channel")
        velocity = self.config.get("velocity", 100)
        
        # Handle key press
        if key_event.keystate == key_event.key_down:
            logger.info(f"Auxiliary key pressed: {aux_config.get('name', key_name)} ({key_name})")
            
            # Handle MIDI notes
            if 'notes' in aux_config:
                notes = aux_config["notes"]
                self.send_midi_notes(notes, velocity, channel, note_on=True)
            
            # Handle CC messages
            if 'cc' in aux_config:
                cc_numbers = aux_config['cc']
                
                # Check if it's a toggle type
                if aux_config.get('behavior') == 'toggle':
                    self.send_midi_cc_toggle(cc_numbers, channel, key_name)
                else:
                    # Send fixed value (default behavior)
                    value = aux_config.get('value', 127)
                    self.send_midi_cc(cc_numbers, value, channel)
        
        # Handle key release
        elif key_event.keystate == key_event.key_up:
            logger.info(f"Auxiliary key released: {aux_config.get('name', key_name)} ({key_name})")
            
            # Handle MIDI notes (send note off)
            if 'notes' in aux_config:
                notes = aux_config["notes"]
                self.send_midi_notes(notes, 0, channel, note_on=False)
            
            # Handle CC messages (only if not toggle behavior)
            if 'cc' in aux_config and aux_config.get('behavior') != 'toggle':
                cc_numbers = aux_config['cc']
                # Send 0 value on key release for momentary behavior
                self.send_midi_cc(cc_numbers, 0, channel)
    
    def run(self):
        """Execute main loop."""
        logger.info("Accordion Bass Controller started. Press Ctrl+C to exit.")
        logger.info(f"Monitoring: {self.device.name}")
        
        try:
            for event in self.device.read_loop():
                self.handle_key_event(event)
                
        except KeyboardInterrupt:
            logger.info("Stopping Accordion Bass Controller...")
            self.cleanup()
        except Exception as e:
            logger.error(f"Error in main loop: {e}")
            self.cleanup()
    
    def cleanup(self):
        """Clean up on exit."""
        # Stop all active notes
        for note_channel in list(self.active_notes):
            if isinstance(note_channel, tuple):
                note, channel = note_channel
                self.midiout.send_message([0x80 | (channel - 1), note, 0])
            else:
                # Fallback for old format
                self.midiout.send_message([0x80, note_channel, 0])
        
        # Release keyboard grab if active
        if self.device and self.grab_mode:
            try:
                self.device.ungrab()
                logger.info("🔓 Released keyboard grab")
            except Exception as e:
                logger.warning(f"Failed to ungrab device: {e}")
        
        if self.midiout:
            self.midiout.close_port()
        
        logger.info("Controller stopped.")


def find_keyboards():
    """Find all available keyboard devices with detailed info."""
    keyboards = []
    devices = [evdev.InputDevice(path) for path in evdev.list_devices()]
    
    for device in devices:
        try:
            capabilities = device.capabilities()
            if ecodes.EV_KEY in capabilities:
                key_codes = capabilities[ecodes.EV_KEY]
                if ecodes.KEY_A in key_codes:
                    keyboards.append({
                        'path': device.path,
                        'name': device.name,
                        'phys': device.phys or 'N/A',
                        'device': device
                    })
        except (OSError, PermissionError):
            # Skip inaccessible devices
            continue
    
    return keyboards


def list_keyboards_detailed(keyboards):
    """Display detailed keyboard listing with status checks."""
    if keyboards:
        print("Available keyboards:")
        print("-" * 40)
        for i, kb in enumerate(keyboards, 1):
            print(f"\n#{i}. {kb['name']}")
            print(f"   Device: {kb['path']}")
            print(f"   Physical: {kb['phys']}")
            
            # Test accessibility
            try:
                device = kb['device']
                device.capabilities()  # Test if readable
                print(f"   Status: ✅ Ready")
            except (OSError, PermissionError):
                print(f"   Status: ❌ Permission denied")
    else:
        print("❌ No keyboards found!")


def select_keyboard_interactive(keyboards):
    """Interactive keyboard selection."""
    if keyboards:
        print("Available keyboards:")
        for i, kb in enumerate(keyboards, 1):
            print(f"  {i}. {kb['name']} ({kb['path']})")
        
        try:
            choice = int(input("\nSelect a keyboard (number): ")) - 1
            return keyboards[choice]['path']
        except (ValueError, IndexError):
            print("Invalid selection.")
            return None
    else:
        print("❌ No keyboards found!")
        return None


def find_device_by_name(device_name, keyboards=None):
    """Find keyboard device by name (partial match, case-insensitive)."""
    if keyboards is None:
        keyboards = find_keyboards()
    
    if not device_name:
        return None
    
    for kb in keyboards:
        if device_name.lower() in kb['name'].lower():
            logger.info(f"Found matching device: '{kb['name']}' for '{device_name}'")
            return kb['path']
    
    logger.warning(f"No device found matching: '{device_name}'")
    return None


def load_config_arguments():
    """Load arguments section from config.yml."""
    config_path = Path(__file__).parent / "config.yml"
    if not config_path.exists():
        return {}
    
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
            return config.get('arguments', {})
    except Exception as e:
        logger.warning(f"Failed to load config.yml: {e}")
        return {}


def main():
    # list all files in config directory with *_layout.yml
    config_dir = Path(__file__).parent / "config"
    layout_files = list(config_dir.glob("*_layout.yml"))
    layout_files = [f.stem.replace('_layout', '') for f in layout_files]

    """Main function."""
    parser = argparse.ArgumentParser(description="Accordion Bass MIDI Controller")
    parser.add_argument(
        "--device", "-d",
        help="Path to keyboard device (e.g. /dev/input/event3)"
    )
    parser.add_argument(
        "--device-by-name",
        help="Find device by name (partial match, case-insensitive)"
    )
    parser.add_argument(
        "--list", "-l",
        action="store_true",
        help="List all available keyboards with detailed info"
    )
    parser.add_argument(
        "--layout",
        choices=layout_files,
        help=f"Layout type to use (default is 'stradella')"
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Print any pressed key events for debugging purposes"
    )
    
    args = parser.parse_args()
    
    # Load config arguments and apply them as defaults (only if not manually specified)
    config_args = load_config_arguments()
    for arg_name, arg_value in config_args.items():
        # Convert hyphenated argument names to underscored attribute names
        attr_name = arg_name.replace('-', '_')
        
        if hasattr(args, attr_name):
            current_value = getattr(args, attr_name)
            
            # For boolean flags (like --debug), only set if False and config is True
            if isinstance(current_value, bool):
                if not current_value and arg_value:
                    setattr(args, attr_name, arg_value)
                    logger.info(f"Using {arg_name} from config.yml: {arg_value}")
            # For other arguments, only set if None (not provided)
            elif current_value is None:
                setattr(args, attr_name, arg_value)
                logger.info(f"Using {arg_name} from config.yml: '{arg_value}'")
    
    # Determine configuration file
    config_file = None
    if args.layout:
        config_file = Path(__file__).parent / "config" / f"{args.layout}_layout.yml"
        if not config_file.exists():
            logger.error(f"Configuration file for layout '{args.layout}' not found: {config_file}")
            sys.exit(1)
        logger.info(f"Using layout: {args.layout} -> {config_file}")
    
    if args.list:
        keyboards = find_keyboards()
        list_keyboards_detailed(keyboards)
        return
    
    # Device selection logic
    keyboards = find_keyboards()
    device_path = None
    
    if args.device:
        device_path = args.device
    elif getattr(args, 'device_by_name', None):
        device_path = find_device_by_name(args.device_by_name, keyboards)
        if not device_path:
            print(f"❌ No device found matching '{args.device_by_name}'")
            print("🔍 Falling back to interactive selection...")
            device_path = select_keyboard_interactive(keyboards)
    else:
        device_path = select_keyboard_interactive(keyboards)
    
    if not device_path:
        return
    
    # Start controller
    try:
        controller = AccordionBassMIDI(device_path, config_file, args.debug)
        if args.debug:
            print("🔧 DEBUG MODE ENABLED - All key events will be printed")
        controller.run()
    except KeyboardInterrupt:
        logger.info("Controller stopped by user")
    except Exception as e:
        logger.error(f"Controller failed: {e}")
        print(f"❌ Error: {e}")
        print("💡 Try: python3 accordion_bass.py --debug -d {device_path} to see key events")


if __name__ == "__main__":
    main()