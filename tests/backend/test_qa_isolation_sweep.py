"""QA ISO-01/02/04/05: child B attacks child A's resources on EVERY route with an id path param
(route list from OpenAPI, so new routes are covered). A's state must be byte-identical afterwards."""

from __future__ import annotations

import re
import uuid

from test_qa_security_sweeps import api_routes

BODIES = {
    "PATCH": {"revision": 1, "name": "pwned", "duration_seconds": 60, "archived": True},
    "PUT": {"completed": True, "revision": 1, "quality_status": "confirmed", "status": "no_walk"},
    "POST": {"revision": 1, "activity_date": "2026-10-05", "duration_seconds": 600, "upgrade_code": "meadow"},
    "DELETE": None,
}


def snapshot(a, act_ids):
    out = {"wallet": a.get("/api/v1/wallet").json(), "worlds": a.get("/api/v1/worlds").json(),
           "chores": a.get("/api/v1/chores").json()}
    for i in act_ids:
        out[i] = (a.get(f"/api/v1/activities/{i}").json(), a.get(f"/api/v1/activities/{i}/entries").json(),
                  a.get(f"/api/v1/activities/{i}/timer").json() if "timer" in str(i) or True else None)
    return out


def test_child_b_cannot_read_or_mutate_child_a_by_uuid(make_api):
    a, b = make_api(), make_api()
    math = a.activity("math")
    bag = a.activity("bag")
    a.timer(math["id"], "start", math["timer"]["revision"])
    entry = a.post(f"/api/v1/activities/{math['id']}/entries",
                   json={"activity_date": "2026-10-05", "duration_seconds": 900, "note": "A-private-note"}).json()
    a_ids = {"activity_id": math["id"], "entry_id": entry["id"]}
    before = {k: v for k, v in snapshot(a, [math["id"]]).items()}
    del before[math["id"]]  # timer elapsed changes with time; compare revision explicitly below
    tested = 0
    for method, path in api_routes():
        params = re.findall(r"\{(\w+)\}", path)
        if not any(p in a_ids for p in params):
            continue
        for chore_variant in ([math["id"], bag["id"]] if "activity_id" in params else [None]):
            url = path
            for p in params:
                val = {"activity_id": chore_variant, "entry_id": entry["id"], "date": "2026-10-06",
                       "cmd": "start", "theme_code": "settlers"}.get(p, str(uuid.uuid4()))
                url = url.replace("{" + p + "}", str(val))
            kw = {"headers": {"Idempotency-Key": uuid.uuid4().hex}}
            if method == "DELETE":
                kw["params"] = {"revision": 1}
            elif method != "GET":
                kw["json"] = BODIES[method]
            r = b.request(method, url, **kw)
            tested += 1
            assert r.status_code in (404, 422), (method, url, r.status_code, r.text[:200])
            assert "A-private-note" not in r.text and entry["id"] not in r.text, (method, url)
    assert tested >= 12
    after = snapshot(a, [math["id"]])
    t = after.pop(math["id"])
    assert after == before
    assert t[0]["name"] == "Математика" and t[0]["archived_at"] is None
    assert [e["id"] for e in t[1]["items"]] == [entry["id"]] and t[1]["items"][0]["revision"] == 1
    assert t[2]["state"] == "running" and t[2]["revision"] == 1


def test_lists_of_b_contain_no_a_ids(make_api):
    a, b = make_api(), make_api()
    a_acts = {x["id"] for x in a.get("/api/v1/activities").json()["items"]}
    blob = "".join(b.get(p).text for p in ("/api/v1/activities", "/api/v1/dashboard", "/api/v1/chores",
                                         "/api/v1/timers", "/api/v1/wallet", "/api/v1/rewards", "/api/v1/worlds",
                                         "/api/v1/analytics/time?group_by=activity", "/api/v1/me"))
    assert not any(i in blob for i in a_acts) and str(a.user_id) not in blob
