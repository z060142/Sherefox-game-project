import json

from sherefox_ref.trace import ROUTES, run_route


def test_traces_deterministic_and_serialisable():
    for name in ROUTES:
        a = json.dumps(run_route(name), ensure_ascii=False, sort_keys=True)
        b = json.dumps(run_route(name), ensure_ascii=False, sort_keys=True)
        assert a == b
        assert json.loads(a)["rounds"][-1]["after"]["outcome"] == "win"
