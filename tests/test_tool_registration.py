import unittest

from tools import TOOL_SCHEMAS, dispatch_tool


class ToolRegistrationTests(unittest.TestCase):
    def test_all_21_documented_tools_have_unique_schemas(self):
        names = [schema["function"]["name"] for schema in TOOL_SCHEMAS]
        expected = {
            "web_search", "deep_research", "calculate_math", "save_memory",
            "recall_memory", "system_control", "open_application",
            "list_applications", "send_email", "check_email",
            "search_knowledge_base", "add_to_knowledge_base",
            "list_knowledge_base", "browse_url", "browser_search",
            "fill_form", "click_and_read", "send_whatsapp",
            "read_whatsapp", "reply_whatsapp", "whatsapp_status",
        }

        self.assertEqual(len(names), 21)
        self.assertEqual(len(set(names)), len(names))
        self.assertEqual(set(names), expected)

    def test_added_tools_are_dispatchable(self):
        self.assertIn("Apps I can open", dispatch_tool("list_applications", {}))
        self.assertNotEqual("Unknown tool: list_knowledge_base", dispatch_tool("list_knowledge_base", {}))


if __name__ == "__main__":
    unittest.main()
