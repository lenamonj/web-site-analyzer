#!/usr/bin/env python3
"""
Offline tests for report_charts.py.

Rendering tests are skipped when matplotlib is missing; the panel-selection
logic is pure and always tested. Run from this directory:
    python -m unittest test_report_charts
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import report_charts as rc

TREND = {
    "quarters": ["2025-Q4", "2026-Q1", "2026-Q2", "2026-Q3"],
    "series": {
        "overall_score": [0.61, 0.68, None, 0.84],
        "security_score": [0.55, 0.7, 0.8, 0.9],
        "seo_score": [0.8, 0.8, 0.85, 0.9],
        "median_lcp_ms": [3400, None, 2600, 2100],
        "median_weight_kb": [3100.0, 2900.0, 2500.0, 2400.0],
        "broken_links": [9, 7, 4, 3],
    },
    "latest_delta": {},
}


class TestPanelSelection(unittest.TestCase):
    def test_drawable_needs_two_measured_points(self):
        self.assertTrue(rc.drawable([1, None, 2]))
        self.assertFalse(rc.drawable([None, None, 5]))
        self.assertFalse(rc.drawable([]))
        self.assertFalse(rc.drawable(None))

    def test_metric_panels_require_two_measured_quarters(self):
        series = {"median_lcp_ms": [None, 2100, None],
                  "broken_links": [3, 2, 1]}
        keys = [key for key, _, _ in rc.metric_panels(series)]
        self.assertEqual(keys, ["broken_links"])


@unittest.skipUnless(rc.HAVE_MPL, "matplotlib not installed")
class TestRenderTrendCharts(unittest.TestCase):
    def test_renders_three_pngs_with_captions(self):
        with tempfile.TemporaryDirectory() as tmp:
            charts = rc.render_trend_charts(TREND, tmp, "acme-example")
            self.assertEqual([Path(c["path"]).name for c in charts],
                             ["acme-example_trend_overall.png",
                              "acme-example_trend_categories.png",
                              "acme-example_trend_metrics.png"])
            for c in charts:
                self.assertTrue(c["caption"])
                self.assertGreater(Path(c["path"]).stat().st_size, 5000)

    def test_sparse_series_render_nothing(self):
        trend = {"quarters": ["2026-Q1", "2026-Q2", "2026-Q3"],
                 "series": {"overall_score": [None, None, 0.8],
                            "median_lcp_ms": [None, None, 2100]},
                 "latest_delta": {}}
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(rc.render_trend_charts(trend, tmp, "x"), [])

    def test_ten_categories_render_ragged_grid(self):
        cats = ["security_score", "seo_score", "performance_score",
                "tls_score", "dns_email_score", "accessibility_score",
                "design_score", "links_score", "privacy_score",
                "readability_score"]
        trend = {"quarters": ["2026-Q1", "2026-Q2", "2026-Q3"],
                 "series": {k: [0.5, 0.6, 0.7] for k in cats},
                 "latest_delta": {}}
        with tempfile.TemporaryDirectory() as tmp:
            charts = rc.render_trend_charts(trend, tmp, "ragged")
            self.assertEqual([Path(c["path"]).name for c in charts],
                             ["ragged_trend_categories.png"])
            self.assertGreater(Path(charts[0]["path"]).stat().st_size, 5000)

    def test_rising_metrics_endpoint_at_maximum(self):
        trend = {"quarters": ["2026-Q1", "2026-Q2", "2026-Q3"],
                 "series": {"median_lcp_ms": [1800, 2400, 3100],
                            "median_weight_kb": [1900.0, 2400.0, 2900.0],
                            "broken_links": [2, 5, 9]},
                 "latest_delta": {}}
        with tempfile.TemporaryDirectory() as tmp:
            charts = rc.render_trend_charts(trend, tmp, "rising")
            self.assertEqual([Path(c["path"]).name for c in charts],
                             ["rising_trend_metrics.png"])
            self.assertGreater(Path(charts[0]["path"]).stat().st_size, 5000)


if __name__ == "__main__":
    unittest.main()
