from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from database import CAPACITY_WATTS, get_connection, list_appliances, transaction
from load import choose_to_restore, choose_to_shed, running_load, still_waiting

app = FastAPI(title="Inverter Load Manager")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class ApplianceCreate(BaseModel):
    name: str = Field(min_length=1)
    wattage: int = Field(gt=0)
    priority: int = Field(ge=1)


def fetch_appliance(connection, appliance_id):
    row = connection.execute(
        """
        SELECT id, name, wattage, priority, state, shed_at
        FROM appliances
        WHERE id = ?
        """,
        (appliance_id,),
    ).fetchone()
    return dict(row) if row else None


def snapshot(connection):
    appliances = list_appliances(connection)
    load_watts = running_load(appliances)
    return {
        "capacity_watts": CAPACITY_WATTS,
        "load_watts": load_watts,
        "remaining_watts": CAPACITY_WATTS - load_watts,
        "appliances": appliances,
    }


def running_lower_priority(appliance, others):
    return [
        item
        for item in others
        if item["id"] != appliance["id"]
        and item["state"] == "running"
        and item["priority"] > appliance["priority"]
    ]


def apply_restore(connection):
    restored = []
    while True:
        pick = choose_to_restore(list_appliances(connection))
        if pick is None:
            break
        connection.execute(
            """
            UPDATE appliances
            SET state = 'running', shed_at = NULL
            WHERE id = ?
            """,
            (pick["id"],),
        )
        pick["state"] = "running"
        pick["shed_at"] = None
        restored.append(pick)
    return restored


def waiting_notes(connection):
    waiting, free = still_waiting(list_appliances(connection))
    return [
        f"{item['name']} stayed shed: it needs {item['wattage']}W and only {free}W is free."
        for item in waiting
    ]


def rejection_message(appliance, free_watts, candidates):
    can_free = sum(item["wattage"] for item in candidates)
    if candidates:
        listed = ", ".join(
            f"{item['name']} ({item['wattage']}W, priority {item['priority']})"
            for item in candidates
        )
        reason = f"Can shed: {listed}, freeing {can_free}W."
    else:
        reason = "Nothing running has a lower priority, so nothing can be shed."
    return (
        f"{appliance['name']} needs {appliance['wattage']}W, "
        f"but only {free_watts}W is free. {reason} Nothing was changed."
    )


@app.get("/status")
def status():
    connection = get_connection()
    try:
        return snapshot(connection)
    finally:
        connection.close()


@app.post("/appliances", status_code=201)
def create_appliance(body: ApplianceCreate):
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Name cannot be blank.")

    connection = get_connection()
    try:
        with transaction(connection):
            cursor = connection.execute(
                """
                INSERT INTO appliances (name, wattage, priority, state, shed_at)
                VALUES (?, ?, ?, 'off', NULL)
                """,
                (name, body.wattage, body.priority),
            )
            appliance = fetch_appliance(connection, cursor.lastrowid)
            message = f"{name} registered. It stays off until you turn it on."
        appliance["message"] = message
        return appliance
    finally:
        connection.close()


@app.delete("/appliances/{appliance_id}")
def delete_appliance(appliance_id: int):
    connection = get_connection()
    try:
        with transaction(connection):
            appliance = fetch_appliance(connection, appliance_id)
            if appliance is None:
                raise HTTPException(
                    status_code=404,
                    detail=f"No appliance with id {appliance_id}.",
                )
            was_running = appliance["state"] == "running"
            connection.execute("DELETE FROM appliances WHERE id = ?", (appliance_id,))
            restored = apply_restore(connection) if was_running else []
            notes = waiting_notes(connection) if was_running else []

        message = f"{appliance['name']} deleted."
        if restored:
            names = " and ".join(item["name"] for item in restored)
            message += f" {names} restored."
        if notes:
            message += " " + " ".join(notes)
        return {"deleted": appliance, "restored": restored, "message": message}
    finally:
        connection.close()


@app.post("/appliances/{appliance_id}/on")
def turn_on(appliance_id: int):
    connection = get_connection()
    try:
        with transaction(connection):
            appliance = fetch_appliance(connection, appliance_id)
            if appliance is None:
                raise HTTPException(
                    status_code=404,
                    detail=f"No appliance with id {appliance_id}.",
                )
            if appliance["state"] == "running":
                return {
                    "appliance": appliance,
                    "shed": [],
                    "restored": [],
                    "message": f"{appliance['name']} is already running.",
                }

            others = list_appliances(connection)
            free_watts = CAPACITY_WATTS - running_load(others)
            shed = []

            if appliance["wattage"] > free_watts:
                candidates = running_lower_priority(appliance, others)
                chosen = choose_to_shed(candidates, appliance["wattage"] - free_watts)
                if chosen is None:
                    raise HTTPException(
                        status_code=409,
                        detail=rejection_message(appliance, free_watts, candidates),
                    )

                shed_at = datetime.now(timezone.utc).isoformat()
                for item in chosen:
                    connection.execute(
                        """
                        UPDATE appliances
                        SET state = 'shed', shed_at = ?
                        WHERE id = ?
                        """,
                        (shed_at, item["id"]),
                    )
                    item["state"] = "shed"
                    item["shed_at"] = shed_at
                    shed.append(item)

            connection.execute(
                """
                UPDATE appliances
                SET state = 'running', shed_at = NULL
                WHERE id = ?
                """,
                (appliance_id,),
            )
            appliance["state"] = "running"
            appliance["shed_at"] = None
            restored = apply_restore(connection)

        if shed:
            names = " and ".join(item["name"] for item in shed)
            message = f"{names} shed to make room for {appliance['name']}."
        else:
            message = f"{appliance['name']} is running."
        if restored:
            names = " and ".join(item["name"] for item in restored)
            message += f" {names} restored."
        return {
            "appliance": appliance,
            "shed": shed,
            "restored": restored,
            "message": message,
        }
    finally:
        connection.close()


@app.post("/appliances/{appliance_id}/off")
def turn_off(appliance_id: int):
    connection = get_connection()
    try:
        with transaction(connection):
            appliance = fetch_appliance(connection, appliance_id)
            if appliance is None:
                raise HTTPException(
                    status_code=404,
                    detail=f"No appliance with id {appliance_id}.",
                )
            if appliance["state"] == "off":
                return {
                    "appliance": appliance,
                    "restored": [],
                    "message": f"{appliance['name']} is already off.",
                }

            was_running = appliance["state"] == "running"
            was_shed = appliance["state"] == "shed"
            connection.execute(
                """
                UPDATE appliances
                SET state = 'off', shed_at = NULL
                WHERE id = ?
                """,
                (appliance_id,),
            )
            restored = apply_restore(connection) if was_running else []
            notes = waiting_notes(connection) if was_running else []

            appliance["state"] = "off"
            appliance["shed_at"] = None

        if was_shed:
            message = (
                f"{appliance['name']} turned off. "
                "It was waiting to come back, and will stay off."
            )
        else:
            message = f"{appliance['name']} turned off."
        if restored:
            names = " and ".join(item["name"] for item in restored)
            message += f" {names} restored."
        if notes:
            message += " " + " ".join(notes)
        return {"appliance": appliance, "restored": restored, "message": message}
    finally:
        connection.close()
