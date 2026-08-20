"""Shirt-label resolution for screenshot-extracted squads (api.resolve)."""

from __future__ import annotations

import pandas as pd

from api.resolve import Resolver, norm

# a pool with every naming hazard the screenshot set surfaced: dotted initials,
# accents, eszett, apostrophes, hyphens, FPL-style disambiguated web_names
# ("Sarr" vs "P.M.Sarr"), and one true same-position collision (Kamara)
POOL = [
    (1, "Bruno Borges Fernandes", "B.Fernandes", "Man Utd", "MID", 120, 45.0),
    (2, "Ismaïla Sarr", "Sarr", "Crystal Palace", "MID", 65, 30.0),
    (3, "Pape Matar Sarr", "P.M.Sarr", "Spurs", "MID", 55, 20.0),
    (4, "Dominic Calvert-Lewin", "Calvert-Lewin", "Leeds", "FWD", 60, 25.0),
    (5, "Dara O'Shea", "O'Shea", "Ipswich", "DEF", 45, 15.0),
    (6, "João Pedro Junqueira de Jesus", "João Pedro", "Chelsea", "FWD", 75, 35.0),
    (7, "Pascal Groß", "Groß", "Brighton", "MID", 60, 28.0),
    (8, "Virgil van Dijk", "Virgil", "Liverpool", "DEF", 60, 33.0),
    (9, "Aboubakar Kamara", "Kamara", "Aston Villa", "MID", 50, 10.0),
    (10, "Glen Kamara", "Kamara", "Leicester", "MID", 48, 12.0),
    (11, "Erling Haaland", "Haaland", "Man City", "FWD", 155, 60.0),
]


def _resolver() -> Resolver:
    return Resolver(
        pd.DataFrame(
            POOL, columns=["code", "player", "web_name", "team", "position", "price", "xpts"]
        )
    )


def test_norm_folds_accents_case_and_punctuation():
    assert norm("João Pedro") == "joao pedro"
    assert norm("Groß") == "gross"
    assert norm("O'Shea") == norm("OShea") == "oshea"
    assert norm("B.Fernandes") == norm("B. Fernandes") == "b fernandes"
    assert norm("Calvert-Le…") == norm("Calvert-Le") == "calvert le"


def test_exact_web_name_is_unique_despite_lookalikes():
    # FPL disambiguates its own web_names — "Sarr" must NOT collide with "P.M.Sarr"
    r = _resolver()
    res = r.resolve("Sarr", "MID")
    assert res["status"] == "ok" and res["match"]["code"] == 2
    res = r.resolve("P.M.Sarr", "MID")
    assert res["status"] == "ok" and res["match"]["code"] == 3


def test_accented_labels_match_unaccented_queries_and_back():
    r = _resolver()
    assert r.resolve("Joao Pedro", "FWD")["match"]["code"] == 6
    assert r.resolve("Gross", "MID")["match"]["code"] == 7
    assert r.resolve("O'Shea", "DEF")["match"]["code"] == 5


def test_truncated_label_resolves_via_prefix():
    r = _resolver()
    for label in ("Calvert-Le…", "Calvert-Le...", "Calvert-Lewin"):
        res = r.resolve(label, "FWD")
        assert res["status"] == "ok" and res["match"]["code"] == 4, label


def test_full_name_token_matches():
    res = _resolver().resolve("Fernandes", "MID")
    assert res["status"] == "ok" and res["match"]["code"] == 1


def test_misread_row_falls_back_to_full_pool():
    res = _resolver().resolve("Haaland", "MID")  # wrong band, name unambiguous
    assert res["status"] == "ok" and res["match"]["code"] == 11


def test_true_collision_is_ambiguous_until_kit_hint_breaks_it():
    r = _resolver()
    res = r.resolve("Kamara", "MID")
    assert res["status"] == "ambiguous"
    assert {c["code"] for c in res["candidates"]} == {9, 10}
    hinted = r.resolve("Kamara", "MID", team_hint="Leicester")
    assert hinted["status"] == "ok" and hinted["match"]["code"] == 10
    assert hinted["method"].endswith("+kit")


def test_wrong_kit_hint_cannot_override_a_unique_match():
    # hints are tiebreakers only — a unique name match ignores a bad hint
    res = _resolver().resolve("Haaland", "FWD", team_hint="Chelsea")
    assert res["status"] == "ok" and res["match"]["code"] == 11


def test_typo_falls_through_to_fuzzy():
    res = _resolver().resolve("Halaand", "FWD")
    assert res["match"]["code"] == 11 and res["method"] == "fuzzy"


def test_gibberish_and_empty_resolve_to_none():
    r = _resolver()
    assert r.resolve("Zzyzx Qwerty", "MID")["status"] == "none"
    assert r.resolve("", "MID")["status"] == "none"
