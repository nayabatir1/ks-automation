"""Loads the game definition: the Task subclass in game.py (its jobs come from jobs/)."""
import importlib
import inspect

from core.task import Task


def load_tasks() -> dict[str, Task]:
    """Returns {name: task} for every Task subclass defined in game.py (normally just Kingshot)."""
    module = importlib.import_module("game")
    found = {obj.task_name(): obj()
             for _, obj in inspect.getmembers(module, inspect.isclass)
             if issubclass(obj, Task) and obj is not Task and obj.__module__ == module.__name__}
    return dict(sorted(found.items(), key=lambda kv: (kv[1].priority, kv[0])))
