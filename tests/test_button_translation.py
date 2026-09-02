"""蓝牙取消配对按钮的实体翻译契约测试。"""
import ast
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components" / "my_ir"


class ButtonTranslationTests(unittest.TestCase):
    """确保按钮名称来自 HA 翻译资源，而不是 Python 硬编码。"""

    def test_bluetooth_unpair_name_uses_translation_key(self):
        tree = ast.parse((COMPONENT / "button.py").read_text(encoding="utf-8-sig"))
        target = next(
            node for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "BluetoothUnpairButton"
        )
        assignments = {
            item.targets[0].id: item.value
            for item in target.body
            if isinstance(item, ast.Assign)
            and len(item.targets) == 1
            and isinstance(item.targets[0], ast.Name)
        }
        self.assertEqual(assignments["_attr_translation_key"].value, "unpair")
        self.assertNotIn("_attr_name", assignments)

        expected = {
            "strings.json": "Delete and Unpair",
            "translations/en.json": "Delete and Unpair",
            "translations/zh-Hans.json": "Delete and Unpair",
        }
        for relative_path, name in expected.items():
            content = json.loads((COMPONENT / relative_path).read_text(encoding="utf-8-sig"))
            self.assertEqual(content["entity"]["button"]["unpair"]["name"], name)


if __name__ == "__main__":
    unittest.main()
