#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import threading
from typing import Any, Dict, List, Optional

_lock = threading.Lock()
_slots: Dict[str, List[Dict[str, Any]]] = {}
_slot_sports: Dict[str, str] = {}  # slot_name -> sport


def list_slots() -> Dict[str, Any]:
    with _lock:
        return {
            name: {
                "count": len(events),
                "sport": _slot_sports.get(name, "football"),
            }
            for name, events in _slots.items()
        }


def get_slot(slot: str) -> List[Dict[str, Any]]:
    with _lock:
        return list(_slots.get(slot, []))


def get_slot_sport(slot: str) -> str:
    with _lock:
        return _slot_sports.get(slot, "football")


def create_slot(slot: str, sport: str) -> None:
    with _lock:
        if slot not in _slots:
            _slots[slot] = []
        _slot_sports[slot] = sport


def add_game(slot: str, game: Dict[str, Any]) -> List[Dict[str, Any]]:
    with _lock:
        if slot not in _slots:
            _slots[slot] = []
        event_id = str(game.get("event_id") or "")
        if event_id:
            _slots[slot] = [g for g in _slots[slot] if str(g.get("event_id") or "") != event_id]
        _slots[slot].append(game)
        return list(_slots[slot])


def remove_game(slot: str, event_id: str) -> List[Dict[str, Any]]:
    with _lock:
        if slot not in _slots:
            return []
        _slots[slot] = [g for g in _slots[slot] if str(g.get("event_id") or "") != event_id]
        return list(_slots[slot])


def clear_slot(slot: str) -> None:
    with _lock:
        _slots[slot] = []


def delete_slot(slot: str) -> bool:
    with _lock:
        if slot in _slots:
            del _slots[slot]
            _slot_sports.pop(slot, None)
            return True
        return False


def slot_exists(slot: str) -> bool:
    with _lock:
        return slot in _slots
