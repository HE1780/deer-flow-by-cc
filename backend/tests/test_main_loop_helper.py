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
