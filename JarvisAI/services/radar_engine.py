"""
Jarvis AI Pro - Resilient OpenSky Radar Engine
Manages API rate-limiting, geospatial bounding boxes, and in-memory TTL caching.
"""

import json
import logging
import math
import time
import urllib.request
from typing import Dict, Any, List

logger = logging.getLogger("Jarvis.RadarEngine")


class ResilientRadarEngine:
    def __init__(self, cache_ttl_sec: int = 60):
        self.cache_ttl = cache_ttl_sec
        self._cache: Dict[str, Dict[str, Any]] = {}
        self.last_request_time = 0.0

    @staticmethod
    def _calc_bbox(lat: float, lon: float, radius_km: float = 50.0):
        """Computes bounding box (lamin, lomin, lamax, lomax) for OpenSky query."""
        lat_delta = radius_km / 111.0
        lon_delta = radius_km / (111.0 * math.cos(math.radians(lat)))
        return lat - lat_delta, lon - lon_delta, lat + lat_delta, lon + lon_delta

    def fetch_nearby_flights(self, lat: float, lon: float, radius_km: float = 50.0) -> List[Dict[str, Any]]:
        cache_key = f"{round(lat, 2)}:{round(lon, 2)}"
        now = time.time()

        # Serve from local cache if within TTL to protect OpenSky quota
        if cache_key in self._cache:
            entry = self._cache[cache_key]
            if now - entry["timestamp"] < self.cache_ttl:
                logger.info("[RADAR] Returning cached radar vectors.")
                return entry["data"]

        # Prevent rate limiting (enforce minimum 10-second spacing between network requests)
        if now - self.last_request_time < 10.0:
            logger.warning("[RADAR] Request throttled locally to protect quota.")
            return self._cache.get(cache_key, {}).get("data", [])

        lamin, lomin, lamax, lomax = self._calc_bbox(lat, lon, radius_km)
        url = (
            f"https://opensky-network.org/api/states/all?"
            f"lamin={lamin:.4f}&lomin={lomin:.4f}&lamax={lamax:.4f}&lomax={lomax:.4f}"
        )

        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Jarvis-AI-Pro-Client"})
            with urllib.request.urlopen(req, timeout=8.0) as resp:
                self.last_request_time = time.time()
                data = json.loads(resp.read().decode())
                
                states = data.get("states") or []
                parsed_aircraft = []

                for s in states:
                    parsed_aircraft.append({
                        "icao24": s[0],
                        "callsign": (s[1] or "UNKN").strip(),
                        "country": s[2],
                        "longitude": s[5],
                        "latitude": s[6],
                        "altitude_m": s[7],
                        "velocity_mps": s[9],
                        "heading": s[10]
                    })

                self._cache[cache_key] = {
                    "timestamp": now,
                    "data": parsed_aircraft
                }
                return parsed_aircraft

        except Exception as err:
            logger.error(f"[RADAR] Failed to pull live telemetry: {err}")
            # Gracefully return stale data if present
            return self._cache.get(cache_key, {}).get("data", [])
