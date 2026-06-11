# tests/test_sel.py — Auswahl-/Pager-Logik der Display-Firmware (display/sel.py).
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "display"))
from sel import resolve_page


def test_no_selection_keeps_position():
    # Ohne Auswahl bleibt der bisherige Index erhalten (altes Verhalten).
    assert resolve_page(["a", "b", "c"], None, 1) == 1

def test_selection_follows_reorder():
    # Angewaehlte Session "b" rutscht durch Reorder von Index 1 auf 2 -> folgt.
    assert resolve_page(["b", "a", "c"], "b", 1) == 0
    assert resolve_page(["a", "c", "b"], "b", 1) == 2

def test_selection_survives_insert_before():
    # Neue Session vorne eingefuegt -> "b" wandert von 1 nach 2, Auswahl folgt.
    assert resolve_page(["new", "a", "b"], "b", 1) == 2

def test_selection_survives_remove_before():
    # Session vor der Auswahl endet -> "c" rueckt von 2 auf 1, Auswahl folgt.
    assert resolve_page(["b", "c"], "c", 2) == 1

def test_lost_selection_clamps_to_range():
    # Angewaehlte Session ist weg -> prev_page wird auf gueltigen Bereich geklemmt.
    assert resolve_page(["a", "b"], "gone", 5) == 1
    assert resolve_page(["a", "b"], "gone", 0) == 0

def test_empty_list_returns_zero():
    assert resolve_page([], "b", 3) == 0
    assert resolve_page([], None, 0) == 0

def test_prev_page_clamped_when_no_match_and_out_of_range():
    assert resolve_page(["a", "b", "c"], None, 9) == 2
    assert resolve_page(["a", "b", "c"], None, -1) == 0
