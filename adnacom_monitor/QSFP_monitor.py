#!/usr/bin/env python3

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk
import cairo


class MonitorGauge(Gtk.DrawingArea):
    def __init__(self, title, unit, thresholds, value_range):
        super().__init__()

        self.title = title
        self.unit = unit

        # Thresholds
        self.high_alarm = thresholds["high_alarm"]
        self.high_warning = thresholds["high_warning"]
        self.low_warning = thresholds["low_warning"]
        self.low_alarm = thresholds["low_alarm"]

        # Value range for display
        self.value_min = value_range[0]
        self.value_max = value_range[1]

        # Current values (list for multi-channel support)
        self.current_values = [value_range[0] + (value_range[1] - value_range[0]) * 0.5]
        self.display_value = [value_range[0] + (value_range[1] - value_range[0]) * 0.5]

        # Set minimum size
        width = 120
        self.set_size_request(width, 150)

        # Connect drawing signal
        self.connect("draw", self.on_draw)

    def set_value(self, value):
        """Update the current value and redraw"""
        # Clamp value to gauge limits
        clamped_value = max(self.value_min, min(self.value_max, value))
        self.current_values = clamped_value
        self.display_value = value
        self.queue_draw()

    def value_to_y(self, value, height):
        """Convert value to y coordinate"""
        # A module that reports all-zero thresholds yields an empty range;
        # pin the marker to the bottom instead of dividing by zero
        value_span = self.value_max - self.value_min
        if value_span <= 0:
            return height
        # Normalize value to 0-1 range
        normalized = (value - self.value_min) / value_span
        # Convert to y coordinate (flip because y=0 is at top)
        return height - (normalized * height)

    def format_value(self, value):
        """Format value based on unit"""
        if self.unit == "μW":
            return f"{value}"
        elif self.unit == "mA":
            return f"{value:.1f}"
        elif self.unit == "V":
            return f"{value:.2f}"
        elif self.unit == "°C":
            return f"{value:.1f}"
        return f"{value:.2f}"

    def calculate_label_positions(self, threshold_positions, gauge_height, font_size=9):
        """
        Calculate non-overlapping positions for threshold labels

        Args:
            threshold_positions: List of (value, ideal_y) tuples
            gauge_height: Height of the gauge area
            font_size: Font size for calculating label height

        Returns:
            List of (value, adjusted_y) tuples
        """
        if not threshold_positions:
            return []

        # Estimate label height (approximate)
        label_height = font_size + 2
        min_spacing = label_height + 2  # Minimum space between labels

        # Sort by ideal y position (top to bottom)
        sorted_positions = sorted(threshold_positions, key=lambda x: x[1])

        # Start with the first label at its ideal position
        adjusted_positions = [(sorted_positions[0][0], sorted_positions[0][1])]

        # Adjust subsequent labels to avoid overlap
        for i in range(1, len(sorted_positions)):
            value, ideal_y = sorted_positions[i]
            prev_value, prev_y = adjusted_positions[-1]

            # Calculate minimum allowed position based on previous label
            min_allowed_y = prev_y + min_spacing

            # Use the maximum of ideal position and minimum allowed position
            adjusted_y = max(ideal_y, min_allowed_y)

            # Make sure we don't go beyond the gauge bounds
            max_allowed_y = gauge_height - label_height / 2
            adjusted_y = min(adjusted_y, max_allowed_y)

            adjusted_positions.append((value, adjusted_y))

        # Second pass: if labels are pushed to the bottom, try to compress upward
        for i in range(len(adjusted_positions) - 2, -1, -1):
            value, current_y = adjusted_positions[i]
            next_value, next_y = adjusted_positions[i + 1]

            # Calculate maximum allowed position based on next label
            max_allowed_y = next_y - min_spacing

            # If current label can be moved up without violating constraints
            if current_y > max_allowed_y:
                # Find the ideal position for this label
                ideal_y = None
                for orig_value, orig_y in threshold_positions:
                    if orig_value == value:
                        ideal_y = orig_y
                        break

                if ideal_y is not None:
                    # Move to the better of ideal or maximum allowed position
                    new_y = max(ideal_y, max_allowed_y)
                    # Make sure we don't go above the gauge
                    new_y = max(new_y, label_height / 2)
                    adjusted_positions[i] = (value, new_y)

        return adjusted_positions

    def draw_threshold_label_with_line(
        self, cr, value, label_text, label_x, label_y, threshold_y, gauge_x, gauge_width
    ):
        """
        Draw a threshold label with a connecting line to the actual threshold position
        """
        # Draw the label
        cr.move_to(label_x, label_y + 3)
        cr.show_text(label_text)

        # Draw a connecting line if label position differs from threshold position
        if (
            abs(label_y - threshold_y) > 5
        ):  # Only draw line if positions differ by more than 5 pixels
            cr.set_source_rgb(0.6, 0.6, 0.6)
            cr.set_line_width(0.5)

            # Draw line from label to threshold position
            text_extents = cr.text_extents(label_text)
            line_start_x = label_x + text_extents.width + 2

            # Draw line to the gauge
            cr.move_to(line_start_x, label_y)
            cr.line_to(gauge_x - 2, threshold_y)
            cr.stroke()

            # Reset color for next elements
            cr.set_source_rgb(0, 0, 0)

    def on_draw(self, widget, cr):
        """Draw the monitoring gauge"""
        allocation = widget.get_allocation()
        width = allocation.width
        height = allocation.height

        # Margins
        margin = 5
        gauge_height = height - 2 * margin
        gauge_y = margin

        # Calculate gauge width and positions for multiple channels
        gauge_width = 20
        gauge_x = (width - gauge_width) / 2

        # Draw title
        cr.set_source_rgb(0, 0, 0)
        cr.select_font_face("Arial", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
        cr.set_font_size(10)

        text_extents = cr.text_extents(self.title)
        title_x = (width - text_extents.width) / 2
        cr.move_to(title_x, 0)
        cr.show_text(self.title)

        # Calculate y positions for thresholds
        high_alarm_y = self.value_to_y(self.high_alarm, gauge_height)
        high_warning_y = self.value_to_y(self.high_warning, gauge_height)
        low_warning_y = self.value_to_y(self.low_warning, gauge_height)
        low_alarm_y = self.value_to_y(self.low_alarm, gauge_height)

        current_gauge_x = gauge_x

        current_value_y = self.value_to_y(self.current_values, gauge_height)

        # Draw background
        cr.set_source_rgb(0.9, 0.9, 0.9)
        cr.rectangle(current_gauge_x, gauge_y, gauge_width, gauge_height)
        cr.fill()

        # Draw value zones
        # High alarm zone (red)
        cr.set_source_rgb(0.8, 0.2, 0.2)
        cr.rectangle(current_gauge_x, gauge_y, gauge_width, high_alarm_y + gauge_y)
        cr.fill()

        # High warning zone (orange)
        cr.set_source_rgb(1.0, 0.6, 0.2)
        cr.rectangle(
            current_gauge_x,
            high_alarm_y + gauge_y,
            gauge_width,
            high_warning_y - high_alarm_y,
        )
        cr.fill()

        # Normal zone (green)
        cr.set_source_rgb(0.2, 0.8, 0.2)
        cr.rectangle(
            current_gauge_x,
            high_warning_y + gauge_y,
            gauge_width,
            low_warning_y - high_warning_y,
        )
        cr.fill()

        # Low warning zone (orange)
        cr.set_source_rgb(1.0, 0.6, 0.2)
        cr.rectangle(
            current_gauge_x,
            low_warning_y + gauge_y,
            gauge_width,
            low_alarm_y - low_warning_y,
        )
        cr.fill()

        # Low alarm zone (red)
        cr.set_source_rgb(0.8, 0.2, 0.2)
        cr.rectangle(
            current_gauge_x,
            low_alarm_y + gauge_y,
            gauge_width,
            gauge_height - low_alarm_y,
        )
        cr.fill()

        # Draw border
        cr.set_source_rgb(0.3, 0.3, 0.3)
        cr.set_line_width(1)
        cr.rectangle(current_gauge_x, gauge_y, gauge_width, gauge_height)
        cr.stroke()

        # Draw value indicator line
        cr.set_source_rgb(0, 0, 0)
        cr.set_line_width(2)
        cr.move_to(current_gauge_x - 2, current_value_y + gauge_y)
        cr.line_to(current_gauge_x + gauge_width + 2, current_value_y + gauge_y)
        cr.stroke()

        # Calculate non-overlapping label positions
        threshold_data = [
            (self.high_alarm, high_alarm_y),
            (self.high_warning, high_warning_y),
            (self.low_warning, low_warning_y),
            (self.low_alarm, low_alarm_y),
        ]

        adjusted_positions = self.calculate_label_positions(
            threshold_data, gauge_height + gauge_y
        )

        # Draw threshold labels with anti-overlap positioning
        label_x = margin
        cr.set_source_rgb(0, 0, 0)
        cr.set_font_size(9)

        # Create a mapping from values to original y positions for line drawing
        value_to_threshold_y = {
            self.high_alarm: high_alarm_y,
            self.high_warning: high_warning_y,
            self.low_warning: low_warning_y,
            self.low_alarm: low_alarm_y,
        }

        for value, adjusted_y in adjusted_positions:
            label_text = f"{self.format_value(value)}{self.unit}"
            threshold_y = value_to_threshold_y[value]

            self.draw_threshold_label_with_line(
                cr,
                value,
                label_text,
                label_x,
                adjusted_y + gauge_y,
                threshold_y + gauge_y,
                gauge_x,
                gauge_width,
            )

        # Draw threshold indicator lines
        cr.set_source_rgb(0.4, 0.4, 0.4)
        cr.set_line_width(1)

        line_start = gauge_x
        line_end = gauge_x + gauge_width

        # Draw horizontal lines at threshold positions
        threshold_lines = [high_alarm_y, high_warning_y, low_warning_y, low_alarm_y]
        for line_y in threshold_lines:
            cr.move_to(line_start, line_y + gauge_y)
            cr.line_to(line_end, line_y + gauge_y)
            cr.stroke()

        # Draw current values
        cr.set_font_size(10)

        value_x = (
            gauge_x + gauge_width + 8
        )  # Value label on the right side of the bar, horizontal positioning
        value_y = (
            current_value_y + 8
        )  # Value label on the right side of the bar, vertical positioning
        value_text = f"{self.format_value(self.display_value)}{self.unit}"

        cr.move_to(value_x, value_y)
        cr.show_text(value_text)

        return False
