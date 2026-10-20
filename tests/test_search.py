"""Tests for the search tool and list pagination."""

from __future__ import annotations

import unittest

import proton_tools as tools


class SearchTool(unittest.TestCase):
    def test_registered(self) -> None:
        self.assertIn("proton_search", [n for n, *_ in tools.TOOLS])

    def test_requires_a_criterion(self) -> None:
        self.assertIn("search by", tools.handle_search({}))

    def test_list_schema_exposes_page(self) -> None:
        self.assertIn("page", tools.PROTON_LIST_SCHEMA["parameters"]["properties"])

    def test_search_schema_fields(self) -> None:
        props = tools.PROTON_SEARCH_SCHEMA["parameters"]["properties"]
        for field in ("query", "sender", "subject", "folder", "unread_only", "has_attachments"):
            self.assertIn(field, props)


if __name__ == "__main__":
    unittest.main()
