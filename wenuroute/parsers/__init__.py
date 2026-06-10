"""Parsers package — exports all parsers and a registry."""

from wenuroute.parsers.android import AndroidParser
from wenuroute.parsers.base import BaseParser
from wenuroute.parsers.flutter import FlutterParser
from wenuroute.parsers.html import HtmlParser
from wenuroute.parsers.nodejs import NodejsParser
from wenuroute.parsers.python import PythonParser
from wenuroute.parsers.react import ReactParser

ALL_PARSERS: list[type[BaseParser]] = [
    HtmlParser,
    ReactParser,
    PythonParser,
    NodejsParser,
    FlutterParser,
    AndroidParser,
]

__all__ = [
    "BaseParser",
    "HtmlParser",
    "ReactParser",
    "PythonParser",
    "NodejsParser",
    "FlutterParser",
    "AndroidParser",
    "ALL_PARSERS",
]
