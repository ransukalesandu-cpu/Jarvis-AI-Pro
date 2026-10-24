"""Tests for one-time pairing by the native Android client."""

from fastapi.testclient import TestClient

from dashboard.server import DashboardServer


def test_native_pair_consumes_one_time_code_and_enables_device_login():
    dashboard = DashboardServer()
    pairing_code = dashboard.new_key()

    with TestClient(dashboard.app) as client:
        paired = client.post("/api/native-pair", json={"pin": pairing_code})

        assert paired.status_code == 200
        payload = paired.json()
        assert payload["ok"] is True
        device_token = payload["device_token"]
        assert isinstance(device_token, str)
        assert len(device_token) >= 32
        assert device_token in dashboard._device_sessions

        # A paired device exchanges its persistent token for a fresh short-lived
        # bearer token before it opens the audio WebSocket.
        login = client.post("/api/device-login", json={"device_token": device_token})
        assert login.status_code == 200
        login_payload = login.json()
        assert login_payload["ok"] is True
        assert login_payload["token"] in dashboard._tokens

        # Pairing codes are one-time and can't create a second device token.
        replay = client.post("/api/native-pair", json={"pin": pairing_code})
        assert replay.status_code == 401
        assert "device_token" not in replay.json()


def test_native_pair_rejects_unknown_code():
    dashboard = DashboardServer()

    with TestClient(dashboard.app) as client:
        response = client.post("/api/native-pair", json={"pin": "ABC234"})

    assert response.status_code == 401
    assert response.json()["ok"] is False
