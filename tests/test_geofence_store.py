"""Checks for persisted, single-polygon geofences."""

import tempfile
import unittest

from modules.geofence_store import list_geofences, load_geofence, normalize_geofence, save_geofence


def rectangle():
    return {"type": "Polygon", "coordinates": [[
        [12.0, 45.0], [12.0001, 45.0], [12.0001, 45.0001],
        [12.0, 45.0001], [12.0, 45.0],
    ]]}


class GeofenceStoreTests(unittest.TestCase):
    def test_save_list_and_reload(self):
        with tempfile.TemporaryDirectory() as directory:
            filename = save_geofence(directory, "Vigneto Nord", rectangle())
            self.assertTrue(filename.endswith(".geojson"))
            self.assertEqual(list_geofences(directory)[0]["filename"], filename)
            feature = load_geofence(directory, filename)
            self.assertEqual(feature["properties"]["name"], "Vigneto Nord")
            self.assertEqual(feature["geometry"]["type"], "Polygon")

    def test_rejects_crossing_and_traversal(self):
        crossing = {"type": "Polygon", "coordinates": [[
            [12.0, 45.0], [12.0001, 45.0001], [12.0, 45.0001],
            [12.0001, 45.0], [12.0, 45.0],
        ]]}
        with self.assertRaisesRegex(ValueError, "intersecante|degenerato"):
            normalize_geofence(crossing)
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "Nome file"):
                load_geofence(directory, "../other.geojson")


if __name__ == "__main__":
    unittest.main()
