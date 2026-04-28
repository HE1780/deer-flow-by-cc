"""Unit tests for deerflow.runtime.main_loop singleton helper."""
import asyncio
import concurrent.futures
import threading
import time

import pytest

from deerflow.runtime import main_loop as ml


@pytest.fixture(autouse=True)
def _reset_main_loop_state():
    """Each test starts from a clean slate."""
    ml._reset_for_tests()
    yield
    ml._reset_for_tests()


def test_has_main_loop_false_when_not_set():
    assert ml.has_main_loop() is False


def test_set_and_get_main_loop():
    loop = asyncio.new_event_loop()
    try:
        ml.set_main_loop(loop)
        assert ml.has_main_loop() is True
        assert ml.get_main_loop() is loop
    finally:
        loop.close()


def test_get_main_loop_raises_when_unset():
    with pytest.raises(RuntimeError, match="main loop is not registered"):
        ml.get_main_loop()


def test_set_main_loop_idempotent_for_same_loop():
    loop = asyncio.new_event_loop()
    try:
        ml.set_main_loop(loop)
        # Re-setting same loop is a no-op, no exception.
        ml.set_main_loop(loop)
        assert ml.get_main_loop() is loop
    finally:
        loop.close()


def test_set_main_loop_rejects_conflicting_loop():
    loop_a = asyncio.new_event_loop()
    loop_b = asyncio.new_event_loop()
    try:
        ml.set_main_loop(loop_a)
        with pytest.raises(RuntimeError, match="already registered"):
            ml.set_main_loop(loop_b)
    finally:
        loop_a.close()
        loop_b.close()
