#!/usr/bin/env python3

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gdk, GLib, Pango
import sys
import subprocess
import re
import os
from .Protocol import DeviceDataReader, get_transceiver_channel_count
from .QSFP_monitor import MonitorGauge
from .firmware import FirmwarePage
from .DIP_switch import DipSwitchBank

from . import __version__ as APP_VERSION


class HostAdapterInfoWindow(Gtk.Window):
    def __init__(self):
        super().__init__(title=f"Adnacom Monitor v{APP_VERSION}")
        self.set_default_size(1350, 880)
        self.set_position(Gtk.WindowPosition.CENTER)

        # Global variables
        self.update_timer_id = None
        self.updates_suspended = False
        self.device_info = {}
        self.qsfp_data = {}
        self.qsfp_count = 2

        # Create shared device combo box
        self.device_store = Gtk.ListStore(str, str)
        self.device_combo = Gtk.ComboBox.new_with_model_and_entry(self.device_store)
        self.device_combo.set_entry_text_column(1)
        self.device_combo.get_style_context().add_class("device-dropdown")

        # Populate the device store
        self.devices = list(self.list_pcie_devices(0x10B5, (0x8718, 0x8725)))
        for bdf, desc in self.devices:
            self.device_store.append([bdf, f"{bdf} - {desc}"])
        self.fit_combo_to_content(self.device_combo)

        # Connect to a unified handler that updates both sections
        self.device_combo.connect("changed", self.on_device_selected_unified)

        # Set up CSS styling
        self.setup_css()

        # Create main container
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.add(main_box)

        # Create tabs
        tabs = self.create_tabs()
        main_box.pack_start(tabs, False, False, 0)

        # Create main content area
        self.content_stack = Gtk.Stack()
        self.content_stack.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT_RIGHT)

        # Create diagnostics page
        diagnostics_content = self.create_diagnostics_content()
        self.content_stack.add_named(diagnostics_content, "diagnostics")

        # Create firmware page
        firmware_content = self.create_firmware_content()
        self.content_stack.add_named(firmware_content, "firmware")

        # Set initial page
        self.content_stack.set_visible_child_name("diagnostics")

        main_box.pack_start(self.content_stack, True, True, 0)

        # Auto-select the first device if any devices were found
        if self.devices:
            self.device_combo.set_active(0)

    def on_device_selected_unified(self, combo):
        """Unified handler that updates both diagnostics and firmware sections"""
        tree_iter = combo.get_active_iter()
        if tree_iter is not None:
            model = combo.get_model()
            bdf = model[tree_iter][0]  # Get the BDF from the first column

            # Update diagnostics sections if they exist
            if hasattr(self, "diagnostics_content_box"):
                # Update your diagnostics sections here
                self.on_device_selected(bdf)

    def fit_combo_to_content(self, combo):
        """Widen a combo-with-entry so the longest item is fully visible"""
        entry = combo.get_child()
        if not isinstance(entry, Gtk.Entry):
            return
        model = combo.get_model()
        column = combo.get_entry_text_column()
        if model is None or column < 0:
            return
        texts = [row[column] for row in model if row[column]]
        if not texts:
            return
        longest = max(texts, key=len)
        text_width = entry.create_pango_layout(longest).get_pixel_size()[0]
        # Extra room for the entry's padding and borders
        entry.set_size_request(text_width + 30, -1)

    def _find_combo_boxes(self, widget):
        if isinstance(widget, Gtk.ComboBox):
            yield widget
        elif isinstance(widget, Gtk.Container):
            for child in widget.get_children():
                yield from self._find_combo_boxes(child)

    def setup_css(self):
        css_provider = Gtk.CssProvider()
        css = """
        .error {
            color: #d9534f;
            font-size: 12px;
            margin-bottom: 10px;
        }

        .sidebar {
            background-color: #f5f5f5;
            border-right: 1px solid #e0e0e0;
            min-width: 200px;
        }

        .sidebar-item {
            padding: 12px 20px;
            border-bottom: 1px solid #e8e8e8;
            background-color: transparent;
            border-radius: 0;
            border-left: none;
            border-right: none;
            border-top: none;
        }

        .sidebar-item:hover {
            background-color: #e8e8e8;
        }

        .sidebar-item.active {
            background-color: #ffffff;
            border-left: 3px solid #0078d4;
        }

        .content-area {
            background-color: #ffffff;
            padding: 20px;
        }

        .section-title {
            font-size: 16px;
            font-weight: bold;
            margin-bottom: 10px;
        }

        .device-dropdown {
            margin-bottom: 20px;
            min-width: 300px;
        }

        .info-label {
            font-size: 11px;
            color: #666666;
            margin-bottom: 2px;
        }

        .info-value {
            font-size: 12px;
            color: #333333;
            margin-bottom: 8px;
        }

        .table-header {
            background-color: #f8f9fa;
            font-weight: bold;
            font-size: 11px;
            padding: 8px;
            border: 1px solid #dee2e6;
        }

        .table-cell {
            font-size: 11px;
            padding: 6px 8px;
            border: 1px solid #dee2e6;
        }

        .status-online {
            color: #28a745;
        }

        .status-indicator {
            background-color: #28a745;
            border-radius: 50%;
            min-width: 8px;
            min-height: 8px;
            margin-right: 5px;
        }

        .checkbox-grid {
            margin: 10px 0;
        }

        .power-section {
            background-color: #f8f9fa;
            padding: 15px;
            border-radius: 5px;
            margin: 10px 0;
        }

        .progress-section {
            margin: 15px 0;
        }
        """

        css_provider.load_from_data(css.encode())
        screen = Gdk.Screen.get_default()
        style_context = Gtk.StyleContext()
        style_context.add_provider_for_screen(
            screen, css_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

    def on_tab_switched(self, notebook, page, page_num):
        if page_num == 0:
            # Diagnostics tab selected
            self.on_diagnostics_clicked(None)
        elif page_num == 1:
            # Firmware tab selected
            self.on_firmware_clicked(None)

    def create_tabs(self):
        notebook = Gtk.Notebook()
        notebook.get_style_context().add_class("main-tabs")

        # Create Diagnostics tab
        diag_label = Gtk.Label(label="🔧 Diagnostics")
        diag_content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        diag_content.get_style_context().add_class("tab-content")
        notebook.append_page(diag_content, diag_label)

        # Create Firmware tab
        fw_label = Gtk.Label(label="📦 Firmware")
        fw_content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        fw_content.get_style_context().add_class("tab-content")
        notebook.append_page(fw_content, fw_label)

        # Set initial active tab (Diagnostics)
        notebook.set_current_page(0)

        # Connect tab switch signal
        notebook.connect("switch-page", self.on_tab_switched)

        # Store references for accessing tab contents
        self.diag_content = diag_content
        self.fw_content = fw_content
        self.notebook = notebook

        return notebook

    def on_diagnostics_clicked(self, button):
        # Resume periodic updates if they were suspended
        if self.updates_suspended:
            self.updates_suspended = False
            # Restart updates with currently selected device
            active_iter = self.device_combo.get_active_iter()
            if active_iter is not None:
                bdf = self.device_store[active_iter][0]
                self.on_device_selected(bdf)
        else:
            # If updates are already running, just refresh the current device
            active_iter = self.device_combo.get_active_iter()
            if active_iter is not None:
                bdf = self.device_store[active_iter][0]
                self.on_device_selected(bdf)

        # Remove active class from all buttons
        self.diag_content.get_style_context().remove_class("active")
        self.fw_content.get_style_context().remove_class("active")

        # Add active class to diagnostics button
        self.diag_content.get_style_context().add_class("active")

        # Switch to diagnostics page
        self.content_stack.set_visible_child_name("diagnostics")

    def on_firmware_clicked(self, button):
        # Stop periodic updates if they are running
        if self.update_timer_id is not None:
            GLib.source_remove(self.update_timer_id)
            self.update_timer_id = None
        self.updates_suspended = True

        # Remove active class from all buttons
        self.diag_content.get_style_context().remove_class("active")
        self.fw_content.get_style_context().remove_class("active")

        # Add active class to firmware button
        self.fw_content.get_style_context().add_class("active")

        # Switch to firmware page
        self.content_stack.set_visible_child_name("firmware")

    def create_diagnostics_content(self):
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scrolled.get_style_context().add_class("content-area")

        # Create main content box directly in the scrolled window
        self.diagnostics_content_box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, spacing=20
        )
        self.diagnostics_content_box.set_margin_start(20)
        self.diagnostics_content_box.set_margin_end(20)
        self.diagnostics_content_box.set_margin_top(20)
        self.diagnostics_content_box.set_margin_bottom(20)
        scrolled.add(self.diagnostics_content_box)

        # Device selection dropdown - use the shared combo box
        device_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        device_box.pack_start(self.device_combo, False, False, 0)
        self.diagnostics_content_box.pack_start(device_box, False, False, 0)

        # Top sections (Device Info, DIP Switches)
        self.top_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=20)

        # Device information section - pass None as initial BDF
        self.diagnostic_info_box = self.create_device_info_section(None)
        self.top_box.pack_start(self.diagnostic_info_box, True, True, 0)

        # DIP Switch Setting
        self.dip_sw_section = self.create_dip_switches_section()
        self.top_box.pack_start(self.dip_sw_section, True, True, 0)

        self.diagnostics_content_box.pack_start(self.top_box, False, False, 0)

        # PCIe Port0 section - pass None as initial BDF
        self.pcie_port0_section = self.create_pcie_port0_section(None)
        self.diagnostics_content_box.pack_start(
            self.pcie_port0_section, False, False, 0
        )

        # Host Cable section - pass None as initial BDF
        self.cable_section = self.create_host_cable_section(None)
        self.diagnostics_content_box.pack_start(self.cable_section, False, False, 0)

        # QSFP section - pass None as initial BDF
        self.qsfp_section = self.create_qsfp_section(None)
        self.diagnostics_content_box.pack_start(self.qsfp_section, False, False, 0)

        # QSFP Monitor section - pass None as initial BDF
        self.qsfp_monitor_section = self.create_qsfp_monitor_section(None)
        self.diagnostics_content_box.pack_start(
            self.qsfp_monitor_section, False, False, 0
        )

        # Bottom section (Card and Power Supplies combined)
        self.bottom_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=20)

        # Card status section
        self.card_section = self.create_card_and_power_section()
        self.bottom_box.pack_start(self.card_section, True, True, 0)

        self.diagnostics_content_box.pack_start(self.bottom_box, False, False, 0)

        return scrolled

    def list_pcie_devices(self, vendor_id=None, device_ids=()):
        try:
            out = subprocess.check_output(["lspci", "-D"]).decode()
            devices = []
            for line in out.splitlines():
                parts = line.split(" ", 1)
                if len(parts) == 2:
                    bdf = parts[0]
                    desc = parts[1]
                    ven, dev = self.get_pci_ids(bdf)
                    if vendor_id == ven and dev in device_ids:
                        device_path = f"/sys/bus/pci/devices/{bdf}/resource0"
                        if os.path.exists(device_path):
                            devices.append((bdf, desc))
            return devices
        except Exception as e:
            print("Error scanning PCIe devices:", e)
            return []

    def get_pci_ids(self, bdf):
        """Get vendor and device IDs for a PCI device"""
        try:
            result = subprocess.check_output(["lspci", "-n", "-s", bdf], text=True)
            match = re.search(
                r"^\w+:\w+\.\w+\s+\w+:\s*([0-9a-fA-F]{4}):([0-9a-fA-F]{4})", result
            )
            if match:
                return (int(match.group(1), 16), int(match.group(2), 16))
        except Exception:
            pass
        return (0, 0)

    def on_device_selected(self, bdf):
        self.selected_bdf = bdf

        # Remove old boxes
        self.diagnostic_info_box.destroy()
        self.pcie_port0_section.destroy()
        self.cable_section.destroy()
        self.qsfp_section.destroy()
        self.qsfp_monitor_section.destroy()
        self.card_section.destroy()
        self.dip_sw_section.destroy()

        # Create new info box
        self.diagnostic_info_box = self.create_device_info_section(bdf)
        self.pcie_port0_section = self.create_pcie_port0_section(bdf)
        self.cable_section = self.create_host_cable_section(bdf)
        self.qsfp_section = self.create_qsfp_section(bdf)
        self.qsfp_monitor_section = self.create_qsfp_monitor_section(bdf)
        self.dip_sw_section = self.create_dip_switches_section()
        self.card_section = self.create_card_and_power_section()

        # Repack top_box (device info and DIP switches)
        self.top_box.pack_start(self.diagnostic_info_box, True, True, 0)
        self.top_box.pack_start(self.dip_sw_section, True, True, 0)
        self.top_box.show_all()

        # Repack main content boxes
        self.diagnostics_content_box.pack_start(
            self.pcie_port0_section, False, False, 0
        )
        self.diagnostics_content_box.pack_start(self.cable_section, False, False, 0)
        self.diagnostics_content_box.pack_start(self.qsfp_section, False, False, 0)
        self.diagnostics_content_box.pack_start(
            self.qsfp_monitor_section, False, False, 0
        )

        # Reorder to correct positions
        self.diagnostics_content_box.reorder_child(self.pcie_port0_section, 2)
        self.diagnostics_content_box.reorder_child(self.cable_section, 3)
        self.diagnostics_content_box.reorder_child(self.qsfp_section, 4)
        self.diagnostics_content_box.reorder_child(self.qsfp_monitor_section, 5)

        # Repack bottom_box (card and power section)
        self.bottom_box.pack_start(self.card_section, True, True, 0)
        self.bottom_box.show_all()

        # Show all sections
        self.diagnostics_content_box.show_all()

        # Start periodic execution
        # Remove existing timer if any
        if self.update_timer_id is not None:
            GLib.source_remove(self.update_timer_id)
            self.update_timer_id = None

        # Only start new timer if updates are not suspended
        if not self.updates_suspended:
            # Execute immediately, then every 1 second
            self.update_timer_id = GLib.timeout_add(
                1000, lambda: self.on_device_selected(bdf)
            )

    def suspend_updates(self):
        """Suspend periodic updates"""
        self.updates_suspended = True
        if self.update_timer_id is not None:
            GLib.source_remove(self.update_timer_id)
            self.update_timer_id = None

    def resume_updates(self):
        """Resume periodic updates"""
        self.updates_suspended = False
        # Restart updates with currently selected device
        active_iter = self.device_combo.get_active_iter()
        if active_iter is not None:
            bdf = self.device_store[active_iter][0]
            self.on_device_selected(bdf)

    def disable_diagnostics_tab(self):
        """If the firmware update is in progress, disable diagnostics tab"""
        self.updates_suspended = True
        if self.update_timer_id is not None:
            GLib.source_remove(self.update_timer_id)
            self.update_timer_id = None

        # Disable the diagnostics tab
        if hasattr(self, "notebook"):
            self.notebook.set_sensitive(False)
            # Optionally, you can also change the label to indicate it's disabled
            for i in range(self.notebook.get_n_pages()):
                label = self.notebook.get_tab_label(self.notebook.get_nth_page(i))
                if label:
                    label.set_sensitive(False)

    def enable_diagnostics_tab(self):
        """Re-enable the tabs after a firmware update attempt ends"""
        # Updates stay suspended until the user switches back to the
        # diagnostics tab, which resumes them via on_diagnostics_clicked
        if hasattr(self, "notebook"):
            self.notebook.set_sensitive(True)
            for i in range(self.notebook.get_n_pages()):
                label = self.notebook.get_tab_label(self.notebook.get_nth_page(i))
                if label:
                    label.set_sensitive(True)

    def create_device_info_section(self, bdf):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)

        # Initialize default values
        self.device_info = {
            "board": "N/A",
            "mode": "-",
            "hw_rev": "-",
            "fw_rev": "-",
            "serial": "-",
            "switch": "-",
            "downstream_cnt": 0,
            "upstream_cnt": 0,
            "dip_sw_cnt": 0,
            "sw1_setting": 0,
            "sw2_setting": 0,
            "brd_state": "-",
            "cpu_temp": "-",
            "pex_temp": "-",
            "board_uptime": 0,
            "assy_rev": "-",
            "reset_len": 0,
            "enum_time": 0,
            "run_time": "N/A",
            "since_reset": "N/A",
            "reset_cnt": "N/A",
            "main_3v3": 0.0,
            "rail_12v_v": 0.0,
            "rail_3v3aux_v": 0.0,
            "cpu_1v8": 0.0,
            "pex_1v8": 0.0,
            "pex_0v9": 0.0,
            "pex_0v9analog": 0.0,
            "rail_12v_i": 0.0,
            "rail_3v3aux_i": 0.0,
        }
        error_message = None

        if bdf:
            try:
                self.device_info.update(DeviceDataReader.read_device_info(bdf))

            except subprocess.TimeoutExpired:
                error_message = (
                    "Timeout accessing device - check if device is busy or locked"
                )
            except subprocess.CalledProcessError as e:
                error_msg = e.stderr.decode().strip() if e.stderr else str(e)
                if "Cannot open" in error_msg:
                    error_message = "Permission denied - try running as root"
                else:
                    error_message = f"Device access error: {error_msg}"
            except FileNotFoundError as e:
                error_message = f"Device resource not found: {str(e)}"
            except Exception as e:
                error_message = f"Error reading device: {str(e)}"

        pattern = r"\b0+(?=\d)"
        if bdf:
            bdf_display = re.sub(pattern, "", bdf.split(":", 1)[1])
            board_display = (
                self.device_info["board"] if self.device_info["board"] != "N/A" else ""
            )
            title_text = f"{bdf_display} {board_display}".strip()
        else:
            title_text = "No device selected"

        title = Gtk.Label(label=title_text)
        title.set_markup(f"<span size='14000' weight='bold'>{title_text}</span>")
        title.set_halign(Gtk.Align.START)
        box.pack_start(title, False, False, 0)

        # Add error message if there was one
        if error_message:
            error_label = Gtk.Label(label=error_message)
            error_label.get_style_context().add_class("error")
            error_label.set_halign(Gtk.Align.START)
            box.pack_start(error_label, False, False, 0)

        grid = Gtk.Grid()
        grid.set_row_homogeneous(True)
        grid.set_column_homogeneous(False)

        headers = ["Board", "Mode", "HW Rev", "FW Rev", "Serial Number", "PCIe Switch"]

        values = [
            self.device_info["board"],
            self.device_info["mode"],
            self.device_info["hw_rev"],
            self.device_info["fw_rev"],
            self.device_info["serial"],
            self.device_info["switch"],
        ]

        # Set QSFP count based on board type according to PCIe Gen3 specification
        board_qsfp_mapping = {
            "H18": 2,
            "H14": 1,
            "H12": 2,
            "H3": 4,
            "H25": 2,
            "R34": 2,  # Default for R34 if not specified
        }

        # Get QSFP count from board type, default to 2 if unknown
        self.qsfp_count = board_qsfp_mapping.get(self.device_info["board"], 2)

        for i, header in enumerate(headers):
            frame = Gtk.Frame()
            frame.set_shadow_type(Gtk.ShadowType.ETCHED_IN)
            label = Gtk.Label(label=header)
            label.set_markup(f"<b>{header}</b>")
            label.set_halign(Gtk.Align.START)
            label.set_margin_start(10)
            label.set_margin_end(10)
            frame.add(label)
            grid.attach(frame, i, 0, 1, 1)

        for i, value in enumerate(values):
            frame = Gtk.Frame()
            frame.set_shadow_type(Gtk.ShadowType.ETCHED_IN)
            label = Gtk.Label(label=value)
            label.set_halign(Gtk.Align.START)
            label.set_margin_start(10)
            label.set_margin_end(10)
            frame.add(label)
            grid.attach(frame, i, 1, 1, 1)

        box.pack_start(grid, False, False, 0)

        return box

    def speed_to_gen(self, speed_str):
        """Convert speed string to PCIe generation"""
        speed_map = {
            "2.5GT/s": "Gen1",
            "5GT/s": "Gen2",
            "8GT/s": "Gen3",
            "16GT/s": "Gen4",
            "32GT/s": "Gen5",
        }
        return speed_map.get(speed_str, speed_str)

    def create_pcie_port0_section(self, bdf):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)

        # Title
        title = Gtk.Label(label="PCIe Slot")
        title.set_markup("<span size='14000' weight='bold'>PCIe Slot</span>")
        title.set_halign(Gtk.Align.START)
        box.pack_start(title, False, False, 0)

        # Create grid for port information
        grid = Gtk.Grid()
        grid.set_row_homogeneous(True)
        grid.set_column_homogeneous(False)

        # Port headers
        headers = ["Port", "Capability", "Link State"]

        # Add header row
        for i, header in enumerate(headers):
            frame = Gtk.Frame()
            frame.set_shadow_type(Gtk.ShadowType.ETCHED_IN)
            label = Gtk.Label(label=header)
            label.set_markup(f"<b>{header}</b>")
            label.set_halign(Gtk.Align.START)
            label.set_margin_start(10)
            label.set_margin_end(10)
            frame.add(label)
            grid.attach(frame, i, 0, 1, 1)

        # Read port data via DeviceDataReader
        display_values = ["0", "-", "-"]  # Default values
        if bdf:
            try:
                port_data = DeviceDataReader.read_pcie_port_info(bdf)

                # Ensure port number is included
                port_data["port"] = "0"  # Port 0 for this section
                display_values = [
                    port_data.get("port", "0"),
                    port_data.get("cap", "-"),
                    port_data.get("link_state", "-"),
                ]
            except subprocess.TimeoutExpired:
                display_values = ["0", "ERROR", "ERROR"]
            except Exception as e:
                display_values = ["0", f"Error: {str(e)}", "ERROR"]

        # Add data rows
        for i, value in enumerate(display_values):
            frame = Gtk.Frame()
            frame.set_shadow_type(Gtk.ShadowType.ETCHED_IN)
            label = Gtk.Label(label=value)
            label.set_halign(Gtk.Align.START)
            label.set_margin_start(10)
            label.set_margin_end(10)

            # Add visual indication for error states
            if str(value) in ["ERROR", "TIMEOUT", "PERM_ERR", "ACC_ERR"]:
                label.set_markup(f'<span foreground="red">{value}</span>')

            frame.add(label)
            grid.attach(frame, i, 1, 1, 1)

        box.pack_start(grid, False, False, 0)

        return box

    def create_host_cable_section(self, bdf):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)

        def read_port_data(port_number, bdf):
            """Read data for a specific cable port"""
            if not bdf:
                return {
                    "port": str(port_number),
                    "link_state": "-",
                    "cap": "-",
                    "training": "-",
                    "remote_up": "-",
                    "recov_cnt": "-",
                    "rx_errors": "-",
                    "bad_tlp": "-",
                    "bad_dll": "-",
                    "framing_err": "-",
                    "retrain": "-",
                    "link_down": "-",
                }

            try:
                port_data = DeviceDataReader.read_cable_info(bdf, port_number)

                # Ensure port number is included
                port_data["port"] = str(port_number)
                if port_data.get("link_state") is None:
                    port_data["link_state"] = "N/A"
                return port_data

            except Exception:  # timeout, or a read the board rejected
                return {
                    "port": str(port_number),
                    "link_state": "ERROR",
                    "cap": "ERROR",
                    "training": "ERROR",
                    "remote_up": "ERROR",
                    "recov_cnt": "ERROR",
                    "rx_errors": "ERROR",
                    "bad_tlp": "ERROR",
                    "bad_dll": "ERROR",
                    "framing_err": "ERROR",
                    "retrain": "ERROR",
                    "link_down": "ERROR",
                }

        title = Gtk.Label(label="Cable")
        title.set_markup("<span size='14000' weight='bold'>Cable</span>")
        title.set_halign(Gtk.Align.START)
        box.pack_start(title, False, False, 0)

        grid = Gtk.Grid()
        grid.set_row_homogeneous(True)
        grid.set_column_homogeneous(False)

        port_headers = [
            "Port",
            "Capability",
            "Status",
            "Training",
            "Remote Up",
            "Recovery",
            "Rx Errors",
            "Bad TCP",
            "Bad DLL",
            "Framing Error",
            "Retrain",
            "Link Down",
        ]

        port_cnt = self.device_info.get("downstream_cnt", 0)

        # Create header row
        for i, header in enumerate(port_headers):
            frame = Gtk.Frame()
            frame.set_shadow_type(Gtk.ShadowType.ETCHED_IN)
            label = Gtk.Label(label=header)
            label.set_markup(f"<b>{header}</b>")
            label.set_halign(Gtk.Align.START)
            label.set_margin_start(8)
            label.set_margin_end(8)
            frame.add(label)
            grid.attach(frame, i, 0, 1, 1)

        # Create data rows - one for each port
        for port_num in range(1, port_cnt + 1):  # Port number starts from 1
            # Read data for this specific port
            port_data = read_port_data(port_num, bdf)

            # Map the data to display values in the correct order
            display_values = [
                port_data.get("port", str(port_num)),
                port_data.get("cap", "-"),
                port_data.get("link_state", "-"),
                port_data.get("training", "-"),
                port_data.get("remote_up", "-"),
                port_data.get("recov_cnt", "-"),
                port_data.get("rx_errors", "-"),
                port_data.get("bad_tlp", "-"),
                port_data.get("bad_dll", "-"),
                port_data.get("framing_err", "-"),
                port_data.get("retrain", "-"),
                port_data.get("link_down", "-"),
            ]

            noqsfp = False
            # Create UI elements for this row
            for col, value in enumerate(display_values):
                frame = Gtk.Frame()
                frame.set_shadow_type(Gtk.ShadowType.ETCHED_IN)

                if col == 1:  # Capability
                    cap = port_data.get("cap", "-")
                    if cap == "No QSFP":
                        noqsfp = True
                    else:
                        noqsfp = False

                if col == 2:  # Link State
                    if not noqsfp:
                        hbox = Gtk.Box(
                            orientation=Gtk.Orientation.HORIZONTAL, spacing=5
                        )
                        # Create a status dot
                        status_dot = Gtk.Label(label="●")
                        isDown = (
                            port_data.get("link_state") == "Down"
                            or port_data.get("link_state") == "-"
                        )
                        if isDown:
                            status_dot.get_style_context().add_class("status-offline")
                        else:
                            status_dot.get_style_context().add_class("status-online")

                        status_dot.set_halign(Gtk.Align.START)
                        status_dot.set_margin_start(10)
                        status_dot.set_margin_end(10)

                        # Create a label for the link state
                        label = Gtk.Label(label=value)
                        label.set_halign(Gtk.Align.START)

                        # Add the status dot and label to the horizontal box
                        hbox.pack_start(status_dot, False, False, 0)
                        hbox.pack_start(label, True, True, 0)

                        # Set margins for the horizontal box
                        hbox.set_margin_start(10)
                        hbox.set_margin_end(10)

                        frame.add(hbox)
                    else:
                        label = Gtk.Label(label=value)
                        label.set_halign(Gtk.Align.START)
                        label.set_margin_start(10)
                        label.set_margin_end(10)

                        # Add visual indication for error states
                        if str(value) in ["ERROR", "TIMEOUT", "PERM_ERR", "ACC_ERR"]:
                            label.set_markup(f'<span foreground="red">{value}</span>')

                        frame.add(label)

                else:
                    label = Gtk.Label(label=value)
                    label.set_halign(Gtk.Align.START)
                    label.set_margin_start(10)
                    label.set_margin_end(10)

                    # Add visual indication for error states
                    if str(value) in ["ERROR", "TIMEOUT", "PERM_ERR", "ACC_ERR"]:
                        label.set_markup(f'<span foreground="red">{value}</span>')

                    frame.add(label)

                # port_num because row 0 is the header, so port 1 goes to row 1, etc.
                grid.attach(frame, col, port_num, 1, 1)

        box.pack_start(grid, False, False, 0)

        return box

    def get_transceiver_name(self, channel_count: int) -> str:
        """Get transceiver name based on channel count"""
        if channel_count == 4:
            return "QSFP"
        elif channel_count == 2:
            return "CSFP"
        elif channel_count == 1:
            return "SFP"
        else:
            return "QSFP"

    def create_qsfp_section(self, bdf):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)

        # Drop entries from the previously selected board so a board with
        # fewer transceivers does not show stale rows in the monitor section
        self.qsfp_data = {}

        def read_qsfp_data(qsfp_number, bdf):
            """Read data for a specific QSFP"""
            if not bdf:
                return {
                    "port": str(qsfp_number + 1),
                    "present": "No",
                    "vendor": "-",
                    "part_num": "-",
                    "serial_num": "-",
                    "technology": "-",
                    "tx_squelch": "-",
                    "rx_squelch_disable": "-",
                    "tx_squelch_disable": "-",
                    "power_supply": "-",
                    "state": "-",
                    "tx": "-",
                    "rx": "-",
                    "rx_los": "-",
                    "temp": 0,
                    "vcc": 0,
                    "rx1": 0,
                    "rx2": 0,
                    "rx3": 0,
                    "rx4": 0,
                    "tx1": "-",
                    "tx2": "-",
                    "tx3": "-",
                    "tx4": "-",
                    "startup": "-",
                    "i2c_errors": "-",
                    "temp_ha": 0,
                    "temp_la": 0,
                    "temp_hw": 0,
                    "temp_lw": 0,
                    "vcc_ha": 0,
                    "vcc_la": 0,
                    "vcc_hw": 0,
                    "vcc_lw": 0,
                    "rx_pwr_ha": 0,
                    "rx_pwr_la": 0,
                    "rx_pwr_hw": 0,
                    "rx_pwr_lw": 0,
                    "tx_bias_ha": 0,
                    "tx_bias_la": 0,
                    "tx_bias_hw": 0,
                    "tx_bias_lw": 0,
                    "rx1_onoff": 0,
                    "rx2_onoff": 0,
                    "rx3_onoff": 0,
                    "rx4_onoff": 0,
                    "tx1_onoff": 0,
                    "tx2_onoff": 0,
                    "tx3_onoff": 0,
                    "tx4_onoff": 0,
                }

            try:
                qsfp_data = DeviceDataReader.read_qsfp_info(bdf, qsfp_number)

                # Ensure QSFP number is included
                qsfp_data["port"] = str(qsfp_number + 1)
                return qsfp_data

            except Exception:  # timeout, or a read the board rejected
                return {
                    "port": str(qsfp_number + 1),
                    "present": "ERROR",
                    "vendor": "ERROR",
                    "part_num": "ERROR",
                    "serial_num": "ERROR",
                    "technology": "ERROR",
                    "tx_squelch": "ERROR",
                    "rx_squelch_disable": "ERROR",
                    "tx_squelch_disable": "ERROR",
                    "power_supply": "ERROR",
                    "state": "ERROR",
                    "rx_los": "-",
                    "temp": 0,
                    "vcc": 0,
                    "rx1": 0,
                    "rx2": 0,
                    "rx3": 0,
                    "rx4": 0,
                    "tx1": "-",
                    "tx2": "-",
                    "tx3": "-",
                    "tx4": "-",
                    "startup": "-",
                    "i2c_errors": "-",
                    "temp_ha": 0,
                    "temp_la": 0,
                    "temp_hw": 0,
                    "temp_lw": 0,
                    "vcc_ha": 0,
                    "vcc_la": 0,
                    "vcc_hw": 0,
                    "vcc_lw": 0,
                    "rx_pwr_ha": 0,
                    "rx_pwr_la": 0,
                    "rx_pwr_hw": 0,
                    "rx_pwr_lw": 0,
                    "tx_bias_ha": 0,
                    "tx_bias_la": 0,
                    "tx_bias_hw": 0,
                    "tx_bias_lw": 0,
                    "rx1_onoff": 0,
                    "rx2_onoff": 0,
                    "rx3_onoff": 0,
                    "rx4_onoff": 0,
                    "tx1_onoff": 0,
                    "tx2_onoff": 0,
                    "tx3_onoff": 0,
                    "tx4_onoff": 0,
                }

        # Determine transceiver type and get name
        transceiver_type = 0  # Default to QSFP (4 channels)
        for qsfp_num in range(0, self.qsfp_count):
            try:
                if bdf:
                    qsfp_data = DeviceDataReader.read_qsfp_info(bdf, qsfp_num)
                    transceiver_type = qsfp_data.get("transceiver_type", 0)
                    if transceiver_type != 0:
                        break
            except Exception:
                pass

        channel_count = get_transceiver_channel_count(transceiver_type)
        transceiver_name = self.get_transceiver_name(channel_count)

        title = Gtk.Label(label=transceiver_name)
        title.set_markup(f"<span size='14000' weight='bold'>{transceiver_name}</span>")
        title.set_halign(Gtk.Align.START)
        box.pack_start(title, False, False, 0)

        # First table with rearranged columns
        qsfp_grid1 = Gtk.Grid()
        qsfp_grid1.set_row_homogeneous(True)
        qsfp_grid1.set_column_homogeneous(False)

        qsfp_headers = [
            transceiver_name,
            "Present",
            "Power Supply",
            "State",
            "Rx LoS",
            "Start-up",
            "Vendor",
            "Part Number",
            "Serial Number",
            "Technology",
            "Squelch Implemented",
            "I²C Errors",
        ]

        for i, header in enumerate(qsfp_headers):
            frame = Gtk.Frame()
            frame.set_shadow_type(Gtk.ShadowType.ETCHED_IN)
            label = Gtk.Label(label=header)
            label.set_markup(f"<b>{header}</b>")
            label.set_halign(Gtk.Align.START)
            label.set_margin_start(8)
            label.set_margin_end(8)
            frame.add(label)
            qsfp_grid1.attach(frame, i, 0, 1, 1)

        # Create data rows - one for each QSFP
        for qsfp_num in range(0, self.qsfp_count):  # QSFP number starts from 0
            # Read data for this specific port
            self.qsfp_data[qsfp_num] = read_qsfp_data(qsfp_num, bdf)

            # Map the data to display values in the rearranged order
            display_values = [
                self.qsfp_data[qsfp_num].get("port", str(qsfp_num)),
                self.qsfp_data[qsfp_num].get("present", "No"),
                self.qsfp_data[qsfp_num].get("power_supply", "-"),
                self.qsfp_data[qsfp_num].get("state", "-"),
                self.qsfp_data[qsfp_num].get("rx_los", "-"),
                self.qsfp_data[qsfp_num].get("startup", "-"),
                self.qsfp_data[qsfp_num].get("vendor", "-"),
                self.qsfp_data[qsfp_num].get("part_num", "-"),
                self.qsfp_data[qsfp_num].get("serial_num", "-"),
                self.qsfp_data[qsfp_num].get("technology", "-"),
                (
                    f"{self.qsfp_data[qsfp_num].get('tx_squelch', '-')} "
                    f"{self.qsfp_data[qsfp_num].get('rx_squelch_disable', '-')} "
                    f"{self.qsfp_data[qsfp_num].get('tx_squelch_disable', '-')}"
                ),
                self.qsfp_data[qsfp_num].get("i2c_errors", "-"),
            ]

            # Create UI elements for this row
            for col, value in enumerate(display_values):
                frame = Gtk.Frame()
                frame.set_shadow_type(Gtk.ShadowType.ETCHED_IN)
                if col == 10:  # Squelch Implemented column (index 10 in new order)
                    tx_squelch = self.qsfp_data[qsfp_num].get("tx_squelch", "-")
                    rx_squelch_disable = self.qsfp_data[qsfp_num].get(
                        "rx_squelch_disable", "-"
                    )
                    tx_squelch_disable = self.qsfp_data[qsfp_num].get(
                        "tx_squelch_disable", "-"
                    )
                    label = Gtk.Label(
                        label=f"{tx_squelch} {rx_squelch_disable} {tx_squelch_disable}"
                    )
                    label.set_halign(Gtk.Align.START)

                    # Create checkbox grid
                    checkbox_grid = Gtk.Grid()
                    checkbox_grid.set_column_spacing(10)
                    checkbox_grid.set_row_spacing(5)

                    # tx_squelch checkbox
                    checkbox_tx = Gtk.CheckButton(label="Tx")
                    checkbox_tx.get_style_context().add_class("info-label")
                    checkbox_tx.set_active(tx_squelch == 1)
                    checkbox_tx.set_sensitive(False)
                    checkbox_grid.attach(checkbox_tx, 0, 0, 1, 1)
                    # rx_squelch_disable checkbox
                    checkbox_rx_disable = Gtk.CheckButton(label="Rx Disable")
                    checkbox_rx_disable.get_style_context().add_class("info-label")
                    checkbox_rx_disable.set_active(rx_squelch_disable == 1)
                    checkbox_rx_disable.set_sensitive(False)
                    checkbox_grid.attach(checkbox_rx_disable, 1, 0, 1, 1)
                    # tx_squelch_disable checkbox
                    checkbox_tx_enable = Gtk.CheckButton(label="Tx Disable")
                    checkbox_tx_enable.get_style_context().add_class("info-label")
                    checkbox_tx_enable.set_active(tx_squelch_disable == 1)
                    checkbox_tx_enable.set_sensitive(False)
                    checkbox_grid.attach(checkbox_tx_enable, 2, 0, 1, 1)
                    # Add the checkbox grid to the frame
                    frame.add(checkbox_grid)
                else:
                    # For other columns, just use the value directly
                    label = Gtk.Label(label=value)
                    label.set_halign(Gtk.Align.START)
                    label.set_margin_start(10)
                    label.set_margin_end(10)

                    # Add visual indication for error states
                    if str(value) in ["ERROR", "TIMEOUT", "PERM_ERR", "ACC_ERR"]:
                        label.set_markup(f'<span foreground="red">{value}</span>')
                    frame.add(label)

                # port_num because row 0 is the header, so port 1 goes to row 1, etc.
                qsfp_grid1.attach(frame, col, qsfp_num + 1, 1, 1)

        box.pack_start(qsfp_grid1, False, False, 0)

        return box

    def create_qsfp_monitor_section(self, bdf):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)

        # Determine transceiver type and get name
        transceiver_type = 0  # Default to QSFP (4 channels)
        for qsfp_num in range(len(self.qsfp_data)):
            transceiver_type = self.qsfp_data[qsfp_num].get("transceiver_type", 0)
            if transceiver_type != 0:
                break

        channel_count = get_transceiver_channel_count(transceiver_type)
        transceiver_name = self.get_transceiver_name(channel_count)

        title = Gtk.Label(label=f"{transceiver_name} Monitor")
        title.set_markup(
            f"<span size='14000' weight='bold'>{transceiver_name} Monitor</span>"
        )
        title.set_halign(Gtk.Align.START)
        box.pack_start(title, False, False, 0)

        qsfp_monitor_grid = Gtk.Grid()
        qsfp_monitor_grid.set_row_homogeneous(False)
        qsfp_monitor_grid.set_column_homogeneous(False)

        # Determine maximum channel count among present QSFPs
        max_channels = 1  # Minimum is 1
        present_qsfps = []
        for qsfp_num in range(len(self.qsfp_data)):
            if self.qsfp_data[qsfp_num].get("present") == "Yes":
                transceiver_type = self.qsfp_data[qsfp_num].get("transceiver_type", 0)
                channel_count = get_transceiver_channel_count(transceiver_type)
                max_channels = max(max_channels, channel_count)
                present_qsfps.append(qsfp_num)

        # Create dynamic headers based on maximum channel count
        monitor_headers = [transceiver_name, "Temp", "Vcc"]

        # Add RX headers
        for i in range(max_channels):
            monitor_headers.append(f"Rx{i+1}")

        # Add TX headers
        for i in range(max_channels):
            monitor_headers.append(f"Tx{i+1}")

        for i, header in enumerate(monitor_headers):
            frame = Gtk.Frame()
            frame.set_shadow_type(Gtk.ShadowType.ETCHED_IN)
            label = Gtk.Label(label=header)
            label.set_markup(f"<b>{header}</b>")
            label.set_halign(Gtk.Align.START)
            label.set_margin_start(8)
            label.set_margin_end(8)
            frame.add(label)
            qsfp_monitor_grid.attach(frame, i, 0, 1, 1)

        for row_idx, qsfp_num in enumerate(present_qsfps):
            # Get channel count for this QSFP
            transceiver_type = self.qsfp_data[qsfp_num].get("transceiver_type", 0)
            channel_count = get_transceiver_channel_count(transceiver_type)

            # QSFP Port Frame
            gauge_frame0 = Gtk.Frame()
            gauge_frame0.set_shadow_type(
                Gtk.ShadowType.ETCHED_IN
            )  # or ETCHED_OUT, IN, OUT, NONE
            label = Gtk.Label(label=f"{str(qsfp_num + 1)}")
            gauge_frame0.add(label)
            qsfp_monitor_grid.attach(gauge_frame0, 0, row_idx + 1, 1, 1)

            # Temperature Frame
            temp_thresholds = {
                "high_alarm": self.qsfp_data[qsfp_num].get("temp_ha", 0),
                "high_warning": self.qsfp_data[qsfp_num].get("temp_hw", 0),
                "low_warning": self.qsfp_data[qsfp_num].get("temp_lw", 0),
                "low_alarm": self.qsfp_data[qsfp_num].get("temp_la", 0),
            }
            temp_ha = self.qsfp_data[qsfp_num].get("temp_ha", 0)
            temp_la = self.qsfp_data[qsfp_num].get("temp_la", 0)

            # Create a temperature upper and lower limit using the thresholds
            temp_range = (temp_ha - temp_la) * 0.10
            if 100 < (temp_ha + temp_range):
                temp_upper_limit = 100
            else:
                temp_upper_limit = temp_ha + temp_range

            temp_lower_limit = temp_la - temp_range

            # Create the temperature gauge
            self.temp_gauge = MonitorGauge(
                "", "°C", temp_thresholds, (temp_lower_limit, temp_upper_limit)
            )
            self.temp_gauge.set_value(self.qsfp_data[qsfp_num].get("temp", 0))

            # Create a container for the gauge to ensure proper alignment
            gauge_container_temp = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
            gauge_container_temp.set_halign(Gtk.Align.CENTER)
            gauge_container_temp.pack_start(self.temp_gauge, False, False, 0)

            # Create a frame around the gauge container
            gauge_frame_temp = Gtk.Frame()
            gauge_frame_temp.set_shadow_type(
                Gtk.ShadowType.ETCHED_IN
            )  # or ETCHED_OUT, IN, OUT, NONE
            gauge_frame_temp.add(gauge_container_temp)

            # Attach gauge to grid
            qsfp_monitor_grid.attach(gauge_frame_temp, 1, row_idx + 1, 1, 1)

            # Vcc gauge
            vcc_thresholds = {
                "high_alarm": self.qsfp_data[qsfp_num].get("vcc_ha", 0),
                "high_warning": self.qsfp_data[qsfp_num].get("vcc_hw", 0),
                "low_warning": self.qsfp_data[qsfp_num].get("vcc_lw", 0),
                "low_alarm": self.qsfp_data[qsfp_num].get("vcc_la", 0),
            }
            vcc_ha = self.qsfp_data[qsfp_num].get("vcc_ha", 0)
            vcc_la = self.qsfp_data[qsfp_num].get("vcc_la", 0)

            # Create a vcc upper and lower limit using the thresholds
            vcc_range = (vcc_ha - vcc_la) * 0.10
            vcc_upper_limit = vcc_ha + vcc_range
            vcc_lower_limit = vcc_la - vcc_range

            # Create the vcc gauge
            self.vcc_gauge = MonitorGauge(
                "", "V", vcc_thresholds, (vcc_lower_limit, vcc_upper_limit)
            )
            self.vcc_gauge.set_value(self.qsfp_data[qsfp_num].get("vcc", 0))

            # Create a container for the gauge to ensure proper alignment
            gauge_container_vcc = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
            gauge_container_vcc.set_halign(Gtk.Align.CENTER)
            gauge_container_vcc.pack_start(self.vcc_gauge, False, False, 0)

            # Create a frame around the gauge container
            gauge_frame_vcc = Gtk.Frame()
            gauge_frame_vcc.set_shadow_type(
                Gtk.ShadowType.ETCHED_IN
            )  # or ETCHED_OUT, IN, OUT, NONE
            gauge_frame_vcc.add(gauge_container_vcc)

            # Attach gauge to grid
            qsfp_monitor_grid.attach(gauge_frame_vcc, 2, row_idx + 1, 1, 1)

            for i in range(channel_count):
                # Rx Power gauge
                rx_thresholds = {
                    "high_alarm": self.qsfp_data[qsfp_num].get("rx_pwr_ha", 0),
                    "high_warning": self.qsfp_data[qsfp_num].get("rx_pwr_hw", 0),
                    "low_warning": self.qsfp_data[qsfp_num].get("rx_pwr_lw", 0),
                    "low_alarm": self.qsfp_data[qsfp_num].get("rx_pwr_la", 0),
                }
                rx_ha = self.qsfp_data[qsfp_num].get("rx_pwr_ha", 0)
                rx_la = self.qsfp_data[qsfp_num].get("rx_pwr_la", 0)

                # Create a rx upper and lower limit using the thresholds
                rx_range = (rx_ha - rx_la) * 0.10
                rx_upper_limit = rx_ha + rx_range
                rx_lower_limit = rx_la - rx_range

                # Create the rx gauge
                self.rx_gauge = MonitorGauge(
                    "Rx Power", "μW", rx_thresholds, (rx_lower_limit, rx_upper_limit)
                )

                # Get RX value and on/off status based on channel index
                rx_values = [
                    self.qsfp_data[qsfp_num].get("rx1", 0),
                    self.qsfp_data[qsfp_num].get("rx2", 0),
                    self.qsfp_data[qsfp_num].get("rx3", 0),
                    self.qsfp_data[qsfp_num].get("rx4", 0),
                ]
                rx_onoff = [
                    self.qsfp_data[qsfp_num].get("rx1_onoff", 0),
                    self.qsfp_data[qsfp_num].get("rx2_onoff", 0),
                    self.qsfp_data[qsfp_num].get("rx3_onoff", 0),
                    self.qsfp_data[qsfp_num].get("rx4_onoff", 0),
                ]

                if i < len(rx_values):
                    self.rx_gauge.set_value(rx_values[i])
                    rx_is_on = rx_onoff[i]
                else:
                    self.rx_gauge.set_value(0)
                    rx_is_on = 0

                if rx_is_on == 1:
                    # Create a container for the gauge to ensure proper alignment
                    gauge_container_rx = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
                    gauge_container_rx.set_halign(Gtk.Align.CENTER)
                    gauge_container_rx.pack_start(self.rx_gauge, False, False, 0)

                    # Create a frame around the gauge container
                    gauge_frame_rx = Gtk.Frame()
                    gauge_frame_rx.set_shadow_type(
                        Gtk.ShadowType.ETCHED_IN
                    )  # or ETCHED_OUT, IN, OUT, NONE
                    gauge_frame_rx.add(gauge_container_rx)

                else:
                    # Create a frame around the gauge container
                    gauge_frame_rx = Gtk.Frame()
                    gauge_frame_rx.set_shadow_type(
                        Gtk.ShadowType.ETCHED_IN
                    )  # or ETCHED_OUT, IN, OUT, NONE
                    label = Gtk.Label(label="Rx is off")
                    label.set_markup("<b>Rx is off</b>")
                    label.set_halign(Gtk.Align.START)
                    label.set_margin_start(8)
                    label.set_margin_end(8)
                    gauge_frame_rx.add(label)

                # Attach gauge to grid
                qsfp_monitor_grid.attach(gauge_frame_rx, 3 + i, row_idx + 1, 1, 1)

            for i in range(channel_count):
                # Tx Bias gauge
                tx_thresholds = {
                    "high_alarm": self.qsfp_data[qsfp_num].get("tx_bias_ha", 0),
                    "high_warning": self.qsfp_data[qsfp_num].get("tx_bias_hw", 0),
                    "low_warning": self.qsfp_data[qsfp_num].get("tx_bias_lw", 0),
                    "low_alarm": self.qsfp_data[qsfp_num].get("tx_bias_la", 0),
                }
                tx_ha = self.qsfp_data[qsfp_num].get("tx_bias_ha", 0)
                tx_la = self.qsfp_data[qsfp_num].get("tx_bias_la", 0)

                # Create a tx upper and lower limit using the thresholds
                tx_range = (tx_ha - tx_la) * 0.10
                tx_upper_limit = tx_ha + tx_range
                tx_lower_limit = tx_la - tx_range

                # Create the tx gauge
                self.tx_gauge = MonitorGauge(
                    "Tx Bias", "mA", tx_thresholds, (tx_lower_limit, tx_upper_limit)
                )

                # Get TX value and on/off status based on channel index
                tx_values = [
                    self.qsfp_data[qsfp_num].get("tx1", 0),
                    self.qsfp_data[qsfp_num].get("tx2", 0),
                    self.qsfp_data[qsfp_num].get("tx3", 0),
                    self.qsfp_data[qsfp_num].get("tx4", 0),
                ]
                tx_onoff = [
                    self.qsfp_data[qsfp_num].get("tx1_onoff", 0),
                    self.qsfp_data[qsfp_num].get("tx2_onoff", 0),
                    self.qsfp_data[qsfp_num].get("tx3_onoff", 0),
                    self.qsfp_data[qsfp_num].get("tx4_onoff", 0),
                ]

                if i < len(tx_values):
                    self.tx_gauge.set_value(tx_values[i])
                    tx_is_on = tx_onoff[i]
                else:
                    self.tx_gauge.set_value(0)
                    tx_is_on = 0

                if tx_is_on == 1:
                    # Create a container for the gauge to ensure proper alignment
                    gauge_container_tx = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
                    gauge_container_tx.set_halign(Gtk.Align.CENTER)
                    gauge_container_tx.pack_start(self.tx_gauge, False, False, 0)

                    # Create a frame around the gauge container
                    gauge_frame_tx = Gtk.Frame()
                    gauge_frame_tx.set_shadow_type(
                        Gtk.ShadowType.ETCHED_IN
                    )  # or ETCHED_OUT, IN, OUT, NONE
                    gauge_frame_tx.add(gauge_container_tx)
                else:
                    # Create a frame around the gauge container
                    gauge_frame_tx = Gtk.Frame()
                    gauge_frame_tx.set_shadow_type(
                        Gtk.ShadowType.ETCHED_IN
                    )  # or ETCHED_OUT, IN, OUT, NONE
                    label = Gtk.Label(label="Tx is off")
                    label.set_markup("<b>Tx is off</b>")
                    label.set_halign(Gtk.Align.START)
                    label.set_margin_start(8)
                    label.set_margin_end(8)
                    gauge_frame_tx.add(label)

                # Attach to grid (TX columns follow RX columns)
                tx_column = 3 + max_channels + i
                qsfp_monitor_grid.attach(gauge_frame_tx, tx_column, row_idx + 1, 1, 1)

            # Fill empty frames for QSFPs with fewer channels than max
            for i in range(channel_count, max_channels):
                # Empty RX column
                empty_frame_rx = Gtk.Frame()
                empty_frame_rx.set_shadow_type(Gtk.ShadowType.ETCHED_IN)
                label = Gtk.Label(label="N/A")
                label.set_markup("<b>N/A</b>")
                label.set_halign(Gtk.Align.START)
                label.set_margin_start(8)
                label.set_margin_end(8)
                empty_frame_rx.add(label)
                qsfp_monitor_grid.attach(empty_frame_rx, 3 + i, row_idx + 1, 1, 1)

                # Empty TX column
                empty_frame_tx = Gtk.Frame()
                empty_frame_tx.set_shadow_type(Gtk.ShadowType.ETCHED_IN)
                label = Gtk.Label(label="N/A")
                label.set_markup("<b>N/A</b>")
                label.set_halign(Gtk.Align.START)
                label.set_margin_start(8)
                label.set_margin_end(8)
                empty_frame_tx.add(label)
                tx_column = 3 + max_channels + i
                qsfp_monitor_grid.attach(empty_frame_tx, tx_column, row_idx + 1, 1, 1)

        box.pack_start(qsfp_monitor_grid, True, True, 0)

        return box

    def create_card_and_power_section(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)

        # Title with status
        title_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        title = Gtk.Label(label="Card")
        title.set_markup(
            f"<span size='14000' weight='bold'>{self.device_info['board']}</span>"
        )
        status_dot = Gtk.Label(label="●")
        if f"{self.device_info['brd_state']}" == "On":
            status_dot.get_style_context().add_class("status-online")
        uptime_seconds = float(self.device_info["board_uptime"])
        uptime_seconds = uptime_seconds // 1000
        hours = int(uptime_seconds // 3600)
        minutes = int((uptime_seconds % 3600) // 60)
        seconds = int(uptime_seconds % 60)

        formatted_time = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        time_label = Gtk.Label(label=formatted_time)

        title_box.pack_start(title, False, False, 0)
        title_box.pack_start(status_dot, False, False, 0)
        title_box.pack_start(time_label, False, False, 0)
        box.pack_start(title_box, False, False, 0)

        # Combined card and power data - Table-like layout
        combined_grid = Gtk.Grid()
        combined_grid.set_row_homogeneous(False)
        combined_grid.set_column_homogeneous(False)
        combined_grid.set_row_spacing(0)
        combined_grid.set_column_spacing(0)

        # Define combined data with the new column order
        rail_12v_w = self.device_info["rail_12v_v"] * self.device_info["rail_12v_i"]
        rail_3v3aux_w = (
            self.device_info["rail_3v3aux_v"] * self.device_info["rail_3v3aux_i"]
        )
        combined_data = [
            ("Tpex", f"{self.device_info['pex_temp']} °C"),
            ("Tcpu", f"{self.device_info['cpu_temp']} °C"),
            (
                "Slot 3.3V",
                f"{self.device_info['main_3v3']:.2f} V",
            ),
            (
                "Slot 12V",
                f"{self.device_info['rail_12v_v']:.2f} V"
                f" | {self.device_info['rail_12v_i']:.2f} A"
                f" | {rail_12v_w:.1f} W",
            ),
            (
                "Slot 3.3Vaux",
                f"{self.device_info['rail_3v3aux_v']:.2f} V"
                f" | {self.device_info['rail_3v3aux_i']:.2f} A"
                f" | {rail_3v3aux_w:.1f} W",
            ),
            ("3.3V", f"{self.device_info['main_3v3']:.2f} V"),
            ("1.8VSB", f"{self.device_info['cpu_1v8']:.2f} V"),
            ("1.8V", f"{self.device_info['pex_1v8']:.2f} V"),
            ("0.9V", f"{self.device_info['pex_0v9']:.2f} V"),
            ("0.9VA", f"{self.device_info['pex_0v9analog']:.2f} V"),
        ]

        # Create header row with frames (matching QSFP table style)
        for col, (label_text, _) in enumerate(combined_data):
            frame = Gtk.Frame()
            frame.set_shadow_type(Gtk.ShadowType.ETCHED_IN)
            header = Gtk.Label(label=label_text)
            header.set_markup(f"<b>{label_text}</b>")
            header.set_halign(Gtk.Align.CENTER)
            header.set_valign(Gtk.Align.CENTER)
            header.set_margin_start(8)
            header.set_margin_end(8)
            header.set_margin_top(5)
            header.set_margin_bottom(5)
            frame.add(header)
            combined_grid.attach(frame, col, 0, 1, 1)

        # Create value row with frames (matching QSFP table style)
        for col, (_, value_text) in enumerate(combined_data):
            frame = Gtk.Frame()
            frame.set_shadow_type(Gtk.ShadowType.ETCHED_IN)
            value = Gtk.Label(label=value_text)
            value.set_halign(Gtk.Align.CENTER)
            value.set_valign(Gtk.Align.CENTER)
            value.set_line_wrap(True)
            value.set_line_wrap_mode(Pango.WrapMode.WORD)
            value.set_margin_start(8)
            value.set_margin_end(8)
            value.set_margin_top(5)
            value.set_margin_bottom(5)
            frame.add(value)
            combined_grid.attach(frame, col, 1, 1, 1)

        box.pack_start(combined_grid, False, False, 0)

        box.pack_start(self.create_running_status_grid(), False, False, 0)
        return box

    @staticmethod
    def format_duration_ms(value: object) -> str:
        """Format a millisecond count as HH:MM:SS, passing non-numbers through."""
        if not isinstance(value, int):
            return str(value)
        total = value // 1000
        return f"{total // 3600:02d}:{(total % 3600) // 60:02d}:{total % 60:02d}"

    def create_running_status_grid(self) -> Gtk.Box:
        """Running Status: run time, time since reset, reset count, reset
        length and PCIe enumeration time."""
        status_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        title = Gtk.Label(label="Running Status")
        title.set_markup("<b>Running Status</b>")
        title.set_halign(Gtk.Align.START)
        status_box.pack_start(title, False, False, 0)

        grid = Gtk.Grid()
        status_data = [
            ("Time", self.format_duration_ms(self.device_info["run_time"])),
            ("Since Reset", self.format_duration_ms(self.device_info["since_reset"])),
            ("Resets", str(self.device_info["reset_cnt"])),
            ("Reset Length", f"{self.device_info['reset_len']} ms"),
            ("PCIe Enum Time", f"{self.device_info['enum_time']} ms"),
        ]
        for col, (label_text, value_text) in enumerate(status_data):
            for row, text in enumerate((label_text, value_text)):
                frame = Gtk.Frame()
                frame.set_shadow_type(Gtk.ShadowType.ETCHED_IN)
                label = Gtk.Label(label=text)
                if row == 0:
                    label.set_markup(f"<b>{text}</b>")
                label.set_halign(Gtk.Align.CENTER)
                label.set_margin_start(8)
                label.set_margin_end(8)
                label.set_margin_top(5)
                label.set_margin_bottom(5)
                frame.add(label)
                grid.attach(frame, col, row, 1, 1)
        status_box.pack_start(grid, False, False, 0)
        return status_box

    def create_dip_switches_section(self):
        switch_cnt = self.device_info.get("dip_sw_cnt", 0)

        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)

        title = Gtk.Label(label="DIP Switches")
        title.set_markup("<span size='14000' weight='bold'>DIP Switches</span>")
        title.set_halign(Gtk.Align.START)
        main_box.pack_start(title, False, False, 0)

        sub_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=30)
        sub_box.set_halign(Gtk.Align.START)

        if switch_cnt > 1:
            # DIP2 section
            sw2_setting = self.device_info["sw2_setting"]
            s2_states = [bool((sw2_setting >> i) & 1) for i in range(8)]
            self.s2_bank = DipSwitchBank("S2", 8, s2_states)
            sub_box.pack_start(self.s2_bank, False, False, 0)

        # DIP1 section
        sw1_setting = self.device_info["sw1_setting"]
        s1_states = [bool((sw1_setting >> i) & 1) for i in range(8)]
        self.s1_bank = DipSwitchBank("S1", 8, s1_states)
        sub_box.pack_start(self.s1_bank, False, False, 0)

        main_box.pack_start(sub_box, False, False, 0)

        return main_box

    def create_firmware_content(self):
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scrolled.get_style_context().add_class("content-area")
        self.firmware_page = FirmwarePage()
        scrolled.add(self.firmware_page)
        # FirmwarePage builds its own device combo; widen it to fit its items
        for combo in self._find_combo_boxes(self.firmware_page):
            self.fit_combo_to_content(combo)
        return scrolled


class HostAdapterApp(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="com.example.hostadapter")

    def create_main_window(self):
        """Create the main window after successful authorization"""
        window = HostAdapterInfoWindow()
        window.set_application(self)
        window.show_all()

    def do_activate(self):
        if os.getuid() != 0:
            dialog = Gtk.MessageDialog(
                transient_for=None,
                flags=0,
                message_type=Gtk.MessageType.WARNING,
                buttons=Gtk.ButtonsType.OK_CANCEL,
                text="Root privileges required",
            )
            dialog.format_secondary_text(
                "This application requires root privileges to access PCI devices. "
                "Please run with 'sudo' or ensure your user "
                "has access to PCIe device resources"
            )

            response = dialog.run()
            dialog.destroy()

            if response == Gtk.ResponseType.CANCEL:
                self.quit()
                return  # Exit without creating window

        else:
            self.create_main_window()


def main():
    try:
        app = HostAdapterApp()
        app.run(sys.argv)
    except KeyboardInterrupt:
        print("\nApplication interrupted by user. Exiting gracefully.")
        sys.exit(0)


if __name__ == "__main__":
    main()
