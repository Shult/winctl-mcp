"""Screen captures: geometry, resizing, formats, grid.

These tests capture the real screen of the machine -- which is harmless, a
capture is a read. They never assert anything about the *content* of the image,
only about its structure: nothing may depend on what is displayed at the time of
the test.
"""

from __future__ import annotations

import io
import warnings

import pytest
from PIL import Image

from winctl import capture


@pytest.fixture(scope="module")
def screens():
    return capture.monitors()


class TestMonitors:
    def test_index_zero_is_the_whole_desktop(self, screens):
        assert screens[0]["index"] == 0
        assert screens[0]["role"] == "full virtual desktop"

    def test_at_least_one_physical_monitor(self, screens):
        assert len(screens) >= 2, "mss always exposes the virtual desktop then the monitors"

    def test_the_virtual_desktop_encloses_every_monitor(self, screens):
        """Coordinates may be negative: that is the whole point of the test."""
        whole = screens[0]
        for screen in screens[1:]:
            assert screen["x"] >= whole["x"]
            assert screen["y"] >= whole["y"]
            assert screen["x"] + screen["width"] <= whole["x"] + whole["width"]
            assert screen["y"] + screen["height"] <= whole["y"] + whole["height"]


    def test_no_deprecated_mss_api(self):
        """`mss.mss()` is deprecated since mss 10.2 and will be removed: a capture
        must go through `mss.MSS()`. Explicit here, so the guard survives a change
        to the suite-wide `filterwarnings`."""
        with warnings.catch_warnings():
            warnings.simplefilter("error", DeprecationWarning)
            capture.monitors()
            capture.grab(monitor=1, max_width=100)


class TestGrab:
    def test_capture_is_decodable_with_consistent_dimensions(self):
        shot = capture.grab(monitor=1, max_width=400)

        image = Image.open(io.BytesIO(shot.png))
        assert image.size == shot.sent_size
        assert shot.sent_size[0] <= 400

    def test_resizing_is_reported_by_the_scale(self):
        shot = capture.grab(monitor=1, max_width=300)

        if shot.real_size[0] > 300:
            assert shot.scale == pytest.approx(300 / shot.real_size[0])
            assert shot.sent_size[0] == 300
        else:
            assert shot.scale == 1.0

    def test_without_a_cap_the_image_is_at_scale_1(self):
        shot = capture.grab(monitor=1, max_width=0)

        assert shot.scale == 1.0
        assert shot.sent_size == shot.real_size

    def test_the_summary_gives_the_conversion_to_real_coordinates(self):
        """This text is what lets the model click accurately: it must be there."""
        shot = capture.grab(monitor=1, max_width=200)

        summary = shot.summary()
        assert "x_real" in summary and "y_real" in summary
        assert str(shot.origin[0]) in summary

    def test_arbitrary_region(self, screens):
        screen = screens[1]
        region = {"x": screen["x"] + 10, "y": screen["y"] + 10, "width": 120, "height": 60}

        shot = capture.grab(region=region, max_width=0)

        assert shot.real_size == (120, 60)
        assert shot.origin == (region["x"], region["y"])
        assert "region" in shot.label

    def test_a_region_wins_over_the_monitor_number(self, screens):
        screen = screens[1]
        shot = capture.grab(monitor=0, region={"x": screen["x"], "y": screen["y"], "width": 50, "height": 50})

        assert shot.real_size == (50, 50)

    @pytest.mark.parametrize("width,height", [(0, 10), (10, 0), (-5, 10)])
    def test_a_degenerate_region_is_refused(self, width, height):
        with pytest.raises(ValueError, match="positive"):
            capture.grab(region={"x": 0, "y": 0, "width": width, "height": height})

    def test_a_missing_monitor_is_refused_with_the_valid_values(self, screens):
        with pytest.raises(ValueError, match=f"0 \\(all\\) to {len(screens) - 1}"):
            capture.grab(monitor=len(screens))

    def test_a_negative_monitor_is_refused(self):
        with pytest.raises(ValueError):
            capture.grab(monitor=-1)


class TestFormats:
    @pytest.mark.parametrize(
        "requested,expected,signature",
        [
            ("jpeg", "jpeg", "JPEG"),
            ("jpg", "jpeg", "JPEG"),
            ("png", "png", "PNG"),
            ("webp", "webp", "WEBP"),
            ("JPEG", "jpeg", "JPEG"),
        ],
    )
    def test_supported_formats(self, requested, expected, signature):
        shot = capture.grab(monitor=1, max_width=200, fmt=requested)

        assert shot.mime == expected
        assert Image.open(io.BytesIO(shot.png)).format == signature

    def test_an_unknown_format_is_refused(self):
        with pytest.raises(ValueError, match="Unknown format"):
            capture.grab(monitor=1, max_width=200, fmt="bmp")


class TestGrid:
    def test_the_grid_changes_the_image_without_changing_its_dimensions(self):
        without = capture.grab(monitor=1, max_width=400, fmt="png")
        with_grid = capture.grab(monitor=1, max_width=400, fmt="png", grid=True, grid_step=100)

        assert with_grid.sent_size == without.sent_size
        assert with_grid.png != without.png

    def test_a_tiny_step_is_raised_to_20_px(self):
        """A 1 px step would draw tens of thousands of lines."""
        shot = capture.grab(monitor=1, max_width=200, grid=True, grid_step=1)

        assert Image.open(io.BytesIO(shot.png)).size == shot.sent_size
