"""Auto-discover declarative tools from a controlled package directory."""

from __future__ import annotations

import importlib
import pkgutil
from pathlib import Path

from codereviewer.tools.declarative import is_declarative_tool
from codereviewer.tools.registry import ToolRegistry


def discover_and_register(
    registry: ToolRegistry,
    *,
    package: str,
    directory: str,
) -> int:
    """Import modules in one directory and register all declarative tools found."""

    registered = 0
    dir_path = Path(directory)

    for module_info in pkgutil.iter_modules([str(dir_path)]):
        if module_info.name.startswith("_"):
            continue

        module = importlib.import_module(f"{package}.{module_info.name}")
        for attr_name in dir(module):
            attr = getattr(module, attr_name)
            if not is_declarative_tool(attr):
                continue
            registry.register(attr)
            registered += 1

    return registered
