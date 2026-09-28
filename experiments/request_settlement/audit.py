"""Fail-closed audit of both independently observed admission fences."""

import math
import re

from autonomy_lab.procedures import require


def settled(receipts, instances, epoch, dispatched, known_admitted, known_downstream=frozenset()):
    require(type(epoch) is int and epoch > 0, "Invalid epoch")
    require(set(receipts) == set(instances) == {"quote", "inventory"}, "Missing service receipt")
    require(
        all(type(i) is int and 0 <= i < 128 for i in dispatched | known_admitted),
        "Invalid offered identity",
    )
    require(
        known_admitted <= dispatched and known_downstream <= known_admitted, "Unissued admission"
    )
    identities = {}
    for service in ("quote", "inventory"):
        r = receipts[service]
        require(
            set(r)
            == {
                "instance",
                "epoch",
                "closed",
                "downstream_instance",
                "admitted",
                "finished",
                "operations",
            },
            "Receipt schema differs",
        )
        require(
            type(r["instance"]) is str
            and re.fullmatch("[0-9a-f]{32}", r["instance"]) is not None
            and r["instance"] == instances[service]
            and type(r["epoch"]) is int
            and r["epoch"] == epoch,
            "Instance or epoch changed",
        )
        require(r["closed"] is True, "Admission remains open")
        require(type(r["operations"]) is dict, "Invalid operation ledger")
        expected_downstream = instances["inventory"] if service == "quote" else None
        require(r["downstream_instance"] == expected_downstream, "Downstream identity differs")
        require(
            type(r["admitted"]) is int
            and type(r["finished"]) is int
            and r["admitted"] == r["finished"] == len(r["operations"]) <= 128,
            "Outstanding or missing operations",
        )
        ids = set()
        for key, op in r["operations"].items():
            require(
                type(key) is str and key.isascii() and key.isdecimal() and str(int(key)) == key,
                "Invalid operation identity",
            )
            identity = int(key)
            require(identity in dispatched, "Unissued operation")
            require(
                set(op) == {"state", "started", "finished"} and op["state"] == "finished",
                "Operation not terminal",
            )
            require(
                all(
                    type(op[k]) in (int, float) and math.isfinite(op[k]) and op[k] >= 0
                    for k in ("started", "finished")
                )
                and op["finished"] >= op["started"],
                "Invalid terminal time",
            )
            ids.add(identity)
        identities[service] = ids
    require(known_admitted <= identities["quote"], "Known admission missing")
    require(identities["inventory"] <= identities["quote"], "Uncorrelated downstream work")
    require(known_downstream <= identities["inventory"], "Known downstream admission missing")
    return {"settled": True, "epoch": epoch, "admitted": {k: len(v) for k, v in identities.items()}}
