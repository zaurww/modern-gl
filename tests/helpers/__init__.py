"""What several test modules share: builders, fixtures, keys typed into the window.

A test module imports from here, never from another test module; the fixtures are
registered for all tests in `tests/conftest.py` (`pytest_plugins`)."""
