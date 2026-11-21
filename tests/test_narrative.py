import json
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from rapor import alerts, clean, metrics, narrative, sample, storage

ROOT = Path(__file__).parent.parent
CFG = clean.load_mapping(ROOT / "config" / "mapping.yaml")


@pytest.fixture(scope="module")
def ctx(tmp_path_factory):
    o, p = sample.generate(tmp_path_factory.mktemp("veri"))
    con = storage.build(":memory:", clean.load_orders(o, CFG, clean.Quality()), clean.load_products(p, CFG))
    week = metrics.latest_full_week(con)
    s, e = metrics.week_bounds(week)
    cur = metrics.period(con, s, e)
    prev = metrics.period(con, s - timedelta(days=7), e - timedelta(days=7))
    prod = metrics.products(con, s, e)
    found = alerts.build(cur, prev, prod)
    facts = narrative.build_facts(week, cur, prev, metrics.weekly_series(con, week), prod, found)
    return facts, found


def _resp(payload, stop="end_turn"):
    text = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    return SimpleNamespace(stop_reason=stop, content=[SimpleNamespace(type="text", text=text)])


class FakeClient:
    """Sırayla hazır yanıt döndüren sahte istemci; gönderilen istekleri saklar."""
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        self.calls.append(kw)
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def _good(facts):
    b = facts["bu_hafta"]
    return {"ozet": f"Net kâr {b['net_kar']} oldu, geçen haftaya göre {facts['degisim']['net_kar']}.",
            "oneriler": [{"baslik": "Kulaklık stoğunu yenileyin", "aciklama": "Stokta yok, satış kaçıyor."}]}


def test_facts_have_no_raw_floats(ctx):
    facts, _ = ctx
    blob = json.dumps(facts, ensure_ascii=False)
    assert "e+" not in blob and not any(isinstance(v, float) for v in facts["bu_hafta"].values())


def test_verify_accepts_facts_numbers_and_rejects_invented(ctx):
    facts, _ = ctx
    net = facts["bu_hafta"]["net_kar"]
    assert narrative.verify(f"Net kâr {net}, 3 öneri var.", facts) == []
    assert narrative.verify("Net kâr yaklaşık 27.000 ₺ oldu.", facts) == ["27.000"]
    assert "%12,3" not in facts["degisim"].values()
    assert narrative.verify("Satışlar %12,3 arttı.", facts) == ["12,3"]


def test_ai_path_clean(ctx):
    facts, found = ctx
    client = FakeClient(_resp(_good(facts)))
    n = narrative.write(facts, found, client=client)
    assert n.kaynak == "yapay zeka" and len(client.calls) == 1
    call = client.calls[0]
    assert call["model"] == "claude-opus-5-5"
    assert call["output_config"]["format"]["type"] == "json_schema"
    assert call["fallbacks"] == "default"


def test_invented_number_is_corrected_once(ctx):
    facts, found = ctx
    bad = {"ozet": "Net kâr yaklaşık 27.000 ₺.", "oneriler": []}
    client = FakeClient(_resp(bad), _resp(_good(facts)))
    n = narrative.write(facts, found, client=client)
    assert n.kaynak == "yapay zeka" and len(client.calls) == 2
    assert "27.000" in client.calls[1]["messages"][-1]["content"]


def test_invented_number_twice_falls_back(ctx):
    facts, found = ctx
    bad = {"ozet": "Net kâr yaklaşık 27.000 ₺.", "oneriler": []}
    n = narrative.write(facts, found, client=FakeClient(_resp(bad), _resp(bad)))
    assert n.kaynak == "kural" and "27.000" in n.not_
    assert narrative.verify(narrative._all_text({"ozet": n.ozet, "oneriler": n.oneriler}), facts) == []


def test_refusal_and_garbage_fall_back(ctx):
    facts, found = ctx
    assert narrative.write(facts, found, client=FakeClient(_resp("", stop="refusal"))).kaynak == "kural"
    assert narrative.write(facts, found, client=FakeClient(_resp("bu json değil"))).kaynak == "kural"


def test_missing_credentials_fall_back(ctx):
    facts, found = ctx
    err = TypeError("Could not resolve authentication method. Expected one of api_key ...")
    n = narrative.write(facts, found, client=FakeClient(err))
    assert n.kaynak == "kural" and "anahtar" in n.not_


def test_rule_based_numbers_pass_verify(ctx):
    facts, found = ctx
    n = narrative.rule_based(facts, found)
    assert narrative.verify(narrative._all_text({"ozet": n.ozet, "oneriler": n.oneriler}), facts) == []
    assert n.oneriler and n.oneriler[0]["baslik"] == found[0].title
