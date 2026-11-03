import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

PORT = 8011
BASE = f"http://127.0.0.1:{PORT}"


def request(method, path, body=None):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(
        BASE + path,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req) as response:
            raw = response.read().decode()
            return response.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as error:
        raw = error.read().decode()
        payload = json.loads(raw) if raw else None
        return error.code, payload


def wait_until_up(process):
    for _ in range(50):
        if process.poll() is not None:
            raise RuntimeError("Server exited before it was ready.")
        try:
            with socket.create_connection(("127.0.0.1", PORT), timeout=0.2):
                return
        except OSError:
            time.sleep(0.1)
    raise RuntimeError("Server did not start.")


def start_server(database_path):
    env = os.environ.copy()
    env["INVERTER_DB"] = str(database_path)
    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", str(PORT)],
        cwd=Path(__file__).parent,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        wait_until_up(process)
    except Exception:
        process.kill()
        raise
    return process


def stop_server(process):
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def by_name(status):
    return {item["name"]: item for item in status["appliances"]}


def expect(condition, label, status=None):
    if condition:
        print(f"ok  {label}")
        return
    print(f"FAIL {label}")
    if status is not None:
        print(json.dumps(status, indent=2))
    raise SystemExit(1)


def register(name, wattage, priority):
    code, body = request("POST", "/appliances", {"name": name, "wattage": wattage, "priority": priority})
    expect(code == 201, f"register {name} -> 201", body)
    return body


def turn(name, appliance_id, direction):
    return request("POST", f"/appliances/{appliance_id}/{direction}")


def main():
    with tempfile.TemporaryDirectory() as folder:
        database_path = Path(folder) / "walkthrough.db"
        process = start_server(database_path)
        try:
            fridge = register("Fridge", 300, 1)
            tv = register("TV", 200, 2)
            fan = register("Fan", 100, 3)
            iron = register("Iron", 700, 2)

            code, _ = turn("Fridge", fridge["id"], "on")
            expect(code == 200, "Fridge on")
            code, _ = turn("TV", tv["id"], "on")
            expect(code == 200, "TV on")
            code, _ = turn("Fan", fan["id"], "on")
            expect(code == 200, "Fan on")

            code, status = request("GET", "/status")
            expect(status["load_watts"] == 600, "step 1 load is 600", status)
            states = by_name(status)
            expect(
                all(states[name]["state"] == "running" for name in ("Fridge", "TV", "Fan")),
                "step 1 Fridge, TV, Fan running",
                status,
            )
            expect(states["Iron"]["state"] == "off", "step 1 Iron is off", status)

            code, body = turn("Iron", iron["id"], "on")
            expect(code == 409, "step 2 Iron rejected", body)
            expect("Nothing was changed" in body["detail"], "step 2 explains why", body)
            expect("Fan" in body["detail"] and "TV" not in body["detail"], "step 2 can shed only Fan", body)
            code, status = request("GET", "/status")
            expect(status["load_watts"] == 600, "step 2 load still 600", status)
            expect(by_name(status)["Fan"]["state"] == "running", "step 2 Fan was not shed", status)

            code, body = turn("TV", tv["id"], "off")
            expect(code == 200, "step 3 TV off", body)
            code, status = request("GET", "/status")
            expect(status["load_watts"] == 400, "step 3 load is 400", status)
            expect(by_name(status)["Iron"]["state"] == "off", "step 3 nothing restored", status)

            code, _ = turn("Fridge", fridge["id"], "off")
            code, status = request("GET", "/status")
            expect(status["load_watts"] == 100, "step 4 only Fan is running", status)

            code, body = turn("Iron", iron["id"], "on")
            expect(code == 200, "step 4 Iron on", body)
            code, status = request("GET", "/status")
            expect(status["load_watts"] == 800, "step 4 load is exactly 800", status)
            expect(by_name(status)["Iron"]["state"] == "running", "step 4 Iron running", status)

            code, body = turn("Fridge", fridge["id"], "on")
            expect(code == 200, "step 5 Fridge on", body)
            expect("Iron shed to make room for Fridge" in body["message"], "step 5 message", body)
            code, status = request("GET", "/status")
            states = by_name(status)
            expect(status["load_watts"] == 400, "step 5 load is 400", status)
            expect(states["Fridge"]["state"] == "running", "step 5 Fridge running", status)
            expect(states["Fan"]["state"] == "running", "step 5 Fan still running", status)
            expect(states["TV"]["state"] == "off", "step 5 TV still off", status)
            expect(states["Iron"]["state"] == "shed", "step 5 Iron shed", status)
            expect(states["Iron"]["shed_at"], "step 5 Iron remembers when it was shed", status)

            code, body = turn("Fan", fan["id"], "off")
            expect(code == 200, "step 6 Fan off", body)
            expect("stayed shed" in body["message"], "step 6 says Iron does not fit", body)
            code, status = request("GET", "/status")
            states = by_name(status)
            expect(status["load_watts"] == 300, "step 6 load is 300", status)
            expect(status["remaining_watts"] == 500, "step 6 500W free", status)
            expect(states["Iron"]["state"] == "shed", "step 6 Iron stays shed", status)
            expect(states["Fan"]["state"] == "off", "step 6 Fan stays off", status)

            before = request("GET", "/status")[1]
            stop_server(process)
            process = start_server(database_path)
            code, after = request("GET", "/status")
            expect(after["load_watts"] == before["load_watts"], "step 7 load survived restart", after)
            for name in ("Fridge", "TV", "Fan", "Iron"):
                expect(
                    by_name(after)[name]["state"] == by_name(before)[name]["state"],
                    f"step 7 {name} is still {by_name(before)[name]['state']}",
                    after,
                )

            code, body = turn("Iron", iron["id"], "off")
            expect(code == 200, "explicit off clears a shed appliance", body)
            stop_server(process)
            process = start_server(database_path)
            code, status = request("GET", "/status")
            expect(by_name(status)["Iron"]["state"] == "off", "Iron stays off after restart", status)

            code, body = request("POST", "/appliances", {"name": " ", "wattage": 10, "priority": 1})
            expect(code == 422, "blank name is 422", body)
            code, body = request("DELETE", "/appliances/9999")
            expect(code == 404 and "9999" in body["detail"], "missing id is 404", body)
        finally:
            if process.poll() is None:
                stop_server(process)


if __name__ == "__main__":
    main()
    print("Walkthrough passed.")
