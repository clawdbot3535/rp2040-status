# Auswahl-Logik fuer die Session-Pager-Navigation.
# Bewusst hardware-frei gehalten, damit sie auf dem Host getestet werden kann
# (display/main.py importiert sie; beide werden aufs ESP32 geflasht).


def resolve_page(keys, sel_key, prev_page):
    """Liefert den page-Index, der die angewaehlte Session unter dem Cursor haelt.

    keys:      geordnete Liste der Session-Keys des neuen Frames
    sel_key:   per Wisch angewaehlter Session-Key (oder None = keine Auswahl)
    prev_page: bisheriger page-Index

    Ist eine Session angewaehlt und noch vorhanden, folgt der Index ihrer neuen
    Position (robust gegen Reorder UND Add/Remove). Sonst wird prev_page auf den
    gueltigen Bereich geklemmt — das alte, rein positionale Verhalten.
    """
    n = len(keys)
    if n == 0:
        return 0
    if sel_key is not None:
        try:
            return keys.index(sel_key)
        except ValueError:
            pass
    if prev_page < 0:
        return 0
    if prev_page >= n:
        return n - 1
    return prev_page
