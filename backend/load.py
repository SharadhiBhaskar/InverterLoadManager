from database import CAPACITY_WATTS


def running_load(appliances):
    return sum(item["wattage"] for item in appliances if item["state"] == "running")


def choose_to_shed(candidates, needed_watts):
    if needed_watts <= 0:
        return []
    if not candidates:
        return None

    best = None
    best_key = None
    count = len(candidates)
    for mask in range(1, 1 << count):
        group = [candidates[index] for index in range(count) if mask & (1 << index)]
        watts = sum(item["wattage"] for item in group)
        if watts < needed_watts:
            continue
        key = (
            watts,
            sum(-item["priority"] for item in group),
            len(group),
            tuple(sorted(item["id"] for item in group)),
        )
        if best_key is None or key < best_key:
            best_key = key
            best = group

    if best is None:
        return None
    best.sort(key=lambda item: (-item["priority"], item["id"]))
    return best


def choose_to_restore(appliances):
    free = CAPACITY_WATTS - running_load(appliances)
    waiting = [item for item in appliances if item["state"] == "shed"]
    waiting.sort(key=lambda item: (item["priority"], item["shed_at"] or "", item["id"]))
    for item in waiting:
        if item["wattage"] <= free:
            return item
    return None


def still_waiting(appliances):
    free = CAPACITY_WATTS - running_load(appliances)
    waiting = [item for item in appliances if item["state"] == "shed" and item["wattage"] > free]
    waiting.sort(key=lambda item: (item["priority"], item["shed_at"] or "", item["id"]))
    return waiting, free
