#!/usr/bin/env python3

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gdk, GObject, Pango


class DipSwitch(Gtk.DrawingArea):
    """Custom widget representing a single DIP switch"""

    __gsignals__ = {"toggled": (GObject.SignalFlags.RUN_FIRST, None, (bool,))}

    def __init__(self, initial_state=False):
        super().__init__()
        self.state = initial_state
        self.set_size_request(20, 40)
        self.set_can_focus(True)

        # Connect signals
        self.connect("draw", self.on_draw)
        # self.connect('button-press-event', self.on_button_press)
        self.set_events(Gdk.EventMask.BUTTON_PRESS_MASK)

    def on_draw(self, widget, cr):
        """Draw the DIP switch"""
        allocation = widget.get_allocation()
        width = allocation.width
        height = allocation.height

        # Draw switch body (gray rectangle)
        cr.set_source_rgb(0.7, 0.7, 0.7)
        cr.rectangle(2, 2, width - 4, height - 4)
        cr.fill()

        # Draw switch outline
        cr.set_source_rgb(0.3, 0.3, 0.3)
        cr.set_line_width(1)
        cr.rectangle(2, 2, width - 4, height - 4)
        cr.stroke()

        # Draw the switch toggle
        toggle_height = 10
        if self.state:  # ON position (top)
            toggle_y = 8
            cr.set_source_rgb(0.2, 0.8, 0.2)  # Green when ON
        else:  # OFF position (bottom)
            toggle_y = height - toggle_height - 8
            cr.set_source_rgb(0.9, 0.3, 0.3)  # Red when OFF

        cr.rectangle(6, toggle_y, width - 12, toggle_height)
        cr.fill()

        # Draw toggle outline
        cr.set_source_rgb(0.1, 0.1, 0.1)
        cr.set_line_width(1)
        cr.rectangle(6, toggle_y, width - 12, toggle_height)
        cr.stroke()

        return False

    def on_button_press(self, widget, event):
        """Toggle switch state when clicked"""
        self.toggle()
        return True

    def toggle(self):
        """Toggle the switch state"""
        self.state = not self.state
        self.queue_draw()
        self.emit("toggled", self.state)

    def set_state(self, state):
        """Set the switch state"""
        if self.state != state:
            self.state = state
            self.queue_draw()
            self.emit("toggled", self.state)

    def get_state(self):
        """Get the switch state"""
        return self.state


class DipSwitchBank(Gtk.Box):
    """A bank of DIP switches with labels"""

    def __init__(self, name, num_switches=8, initial_states=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=5)

        self.name = name
        self.switches = []

        # Create title label
        title_label = Gtk.Label()
        title_label.set_markup(f"<b>{name}</b>")
        title_label.set_halign(Gtk.Align.START)
        self.pack_start(title_label, False, False, 0)

        # Create switch name and number labels container
        labels_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        labels_box.set_halign(Gtk.Align.CENTER)

        # Position number labels
        numbers_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)
        numbers_box.set_halign(Gtk.Align.CENTER)
        for i in range(1, num_switches + 1):
            num_label = Gtk.Label(str(i))
            num_label.set_size_request(20, -1)
            num_label.set_halign(Gtk.Align.CENTER)
            numbers_box.pack_start(num_label, False, False, 0)

        labels_box.pack_start(numbers_box, False, False, 0)
        self.pack_start(labels_box, False, False, 0)

        # Create switches container
        switches_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)
        switches_box.set_halign(Gtk.Align.CENTER)

        # Create switches
        if initial_states is None:
            initial_states = [False] * num_switches

        for i in range(num_switches):
            switch = DipSwitch(initial_states[i] if i < len(initial_states) else False)
            switch.connect("toggled", self.on_switch_toggled, i)
            self.switches.append(switch)
            switches_box.pack_start(switch, False, False, 0)

        self.pack_start(switches_box, False, False, 0)

        # Create state display labels
        state_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)
        state_box.set_halign(Gtk.Align.CENTER)

        self.state_labels = []
        for i in range(num_switches):
            state_label = Gtk.Label("0" if not initial_states[i] else "1")
            state_label.set_size_request(20, -1)
            state_label.set_halign(Gtk.Align.CENTER)
            font_desc = Pango.FontDescription("monospace")
            state_label.override_font(font_desc)
            self.state_labels.append(state_label)
            state_box.pack_start(state_label, False, False, 0)

        self.pack_start(state_box, False, False, 0)

    def on_switch_toggled(self, switch, state, index):
        """Handle switch toggle"""
        self.state_labels[index].set_text("1" if state else "0")

    def get_states(self):
        """Get all switch states as a list of booleans"""
        return [switch.get_state() for switch in self.switches]

    def get_binary_string(self):
        """Get switch states as a binary string"""
        return "".join("1" if switch.get_state() else "0" for switch in self.switches)

    def get_decimal_value(self):
        """Get switch states as a decimal value"""
        binary_str = self.get_binary_string()
        return int(binary_str, 2)
