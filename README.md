# Inverter Load Manager

A small home inverter can supply **800W**. This app is the referee. People register appliances and ask for them on or off. The server keeps the running total at or under 800W, pauses less important appliances when it has to, and brings those paused appliances back when there is room.

The screen is Next.js. The API is FastAPI. Everything that must survive a restart is in `backend/inverter.db`.

## Run it

Two terminals.

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
uvicorn main:app --reload
```

```powershell
cd frontend
npm run dev
```

Open http://localhost:3000. The API is http://127.0.0.1:8000. Interactive docs are at http://127.0.0.1:8000/docs.

Check the walkthrough on a temporary database (this does not touch `inverter.db`):

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
python walkthrough.py
```

## States

| State | Meaning |
|---|---|
| `running` | Drawing power now. Counts toward the 800W. |
| `off` | The user turned it off. It stays off until a person asks for it again. |
| `shed` | The user wants it on, but the system paused it. It is waiting to come back. It draws nothing. |

Wattage and priority are fixed at registration. Priority **1** is the most important. A bigger number matters less.

`shed_at` is stored only while an appliance is shed. It is an ISO-8601 timestamp, so "shed earlier" still sorts correctly after a restart.

## API

| Method | Path | Success | Failure |
|---|---|---|---|
| `GET` | `/status` | Full picture: every appliance, load, remaining watts | |
| `POST` | `/appliances` | `201` and the new row, which starts `off` | `422` with a reason (blank name, wattage under 1, priority under 1) |
| `DELETE` | `/appliances/{id}` | The deleted row, plus anything that was restored | `404` naming the missing id |
| `POST` | `/appliances/{id}/on` | The appliance, anything shed, anything restored, and a sentence | `404`, or `409` saying what was needed, what was free, what could have been shed, and that nothing changed |
| `POST` | `/appliances/{id}/off` | The appliance is `off`. A shed appliance stops waiting. | `404` |

Every change runs in one SQLite transaction opened with `BEGIN IMMEDIATE`. The write lock is taken before the capacity check, so two requests cannot both decide there is room. Shedding is written before the new appliance is marked running, so the total never passes 800W, not even for a moment. If the request cannot fit, the code raises before any `UPDATE`, and the transaction rolls back.

## How shedding works

Only a **running** appliance with a **strictly larger** priority number can be paused. An equal priority is never shed, even when shedding it would make the request fit.

The server lists every combination of those candidates that would free enough watts, and picks the combination that sheds the **fewest watts**. If two combinations shed the same number of watts, it pauses the less important appliances.

That choice is what the walkthrough's step 5 needs. Fridge (300W, priority 1) is turned on while Iron (700W, priority 2) and Fan (100W, priority 3) are running and nothing is free. Shedding the Fan frees 100W, which is not enough. Shedding the Iron frees 700W, which is enough. Shedding both also works, but it wastes the Fan. The smallest sufficient combination is the Iron alone. The Fan keeps running, the load is 400W, and the Iron is `shed`.

A rejected request calculates that no combination is enough, then changes nothing. Turning the Iron on at 600W (Fridge + TV + Fan) is the example: the TV is the same priority as the Iron, so it is not a candidate, and the Fan's 100W cannot close a 500W gap.

## How restoring works

When a running appliance is turned off or deleted, watts become free. The server then tries to bring `shed` appliances back.

**Order: highest priority first.** Priority 1 is considered before priority 2, and priority 2 before priority 3. If two appliances share a priority, the one with the earlier `shed_at` comes first, then the smaller id. That timestamp lives in SQLite, so the order is the same after a restart.

**If the next appliance does not fit, skip it and try the next one.** Walkthrough step 6 is the guard rail: after the Fan turns off, 500W is free and the Iron needs 700W, so the Iron stays shed. Skipping matters when something else is also waiting. A 700W priority-1 appliance that does not fit should not block a 100W priority-2 appliance that does. The running total is checked before each restore, so this cannot cross 800W.

An appliance the user switched `off` is not in the waiting list. Turning a shed appliance off clears `shed_at` and sets `off`. It will not come back by itself.

### Why this order, and what it gives up

The priority number is the user saying what should stay on. Restoring the most important waiting appliance first follows that. It also matches shedding, which already refuses to pause anything of equal or higher priority.

The cost is that a big important appliance can sit shed while smaller, less important ones come back, because we skip anything that does not fit. The alternative of stopping at the first miss would be simpler, and it would keep the queue strictly in priority order, but it would leave usable watts idle whenever the front of the queue is too big.

Two other orders were considered:

- **Longest waiting first.** Fair to whatever was paused earliest, and `shed_at` already stores that. It can restore a fan while a fridge is still waiting, which fights the priority numbers the user set.
- **Best fit, or "restore as many as possible."** Packs the 800W tightly. It can also leave the fridge shed indefinitely because a handful of small low-priority appliances keep filling the gap.

Highest priority first, skipping what does not fit, keeps the user's ranking and still uses leftover watts. The large-appliance delay is the downside we accept.

Restore also runs after a successful ON. Shedding can free more watts than the new appliance needs, and some other appliance may already have been waiting. A minimum-wattage shed set is never immediately undone: if one of the appliances we just shed now fit, a smaller combination would have been enough, and that combination would have been chosen instead.

## Messages

Each response includes a `message` when the system sheds something, restores something, or refuses a request. The screen shows that sentence above the appliance list. It is not stored. Refreshing the page clears it. The list itself always comes from `GET /status`.
